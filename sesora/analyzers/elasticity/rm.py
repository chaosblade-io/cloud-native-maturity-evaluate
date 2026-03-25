"""
Elasticity 维度 - 资源管理能力 (Resource Management) 分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)         | 分值 | 评分标准                                                         |
| rm_isolation         | 6    | 实现了命名空间、节点池或租户级别的资源隔离，防止吵闹邻居效应     |
| rm_quota             | 6    | 对所有命名空间/项目设置了明确的 ResourceQuota                    |
| rm_reservation       | 6    | 关键业务拥有 Guaranteed QoS 等级或专属节点池/预留实例保障        |
| rm_dynamic_alloc     | 7    | 支持混合部署（在线/离线混部）或基于潮汐效应的动态资源超卖/回收   |
"""
from ...core.analyzer import Analyzer, ScoreResult
from ...schema.k8s import K8sNamespaceRecord, K8sNodeRecord, K8sResourceQuotaRecord, K8sPodRecord, \
    K8sNetworkPolicyRecord


class RmIsolationAnalyzer(Analyzer):
    """
    资源隔离分析器
    
    评估标准：实现了命名空间、节点池或租户级别的资源隔离，防止"吵闹邻居"效应
    
    数据来源：
    - UModel：k8s.namespace entity_set，Namespace 列表
    - UModel：k8s.node entity_set（labels 字段包含节点池信息）
    - 判断是否使用了多节点池隔离
    """

    def key(self) -> str:
        return "rm_isolation"

    def dimension(self) -> str:
        return "Elasticity"

    def category(self) -> str:
        return "资源管理能力"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return ["k8s.namespace.list", "k8s.node.list", "k8s.networkpolicy.list", "k8s.resourcequota.list"]

    def analyze(self, store) -> ScoreResult:
        namespaces: list[K8sNamespaceRecord] = store.get("k8s.namespace.list")
        nodes: list[K8sNodeRecord] = store.get("k8s.node.list")

        net_pols: list[K8sNetworkPolicyRecord] = store.get("k8s.networkpolicy.list")
        quotas: list[K8sResourceQuotaRecord] = store.get("k8s.resourcequota.list")

        evidence = []
        score = 0

        # --- 1. 命名空间隔离 (最高 3 分) ---
        system_namespaces = {"default", "kube-system", "kube-public", "kube-node-lease", "istio-system", "monitoring"}
        user_namespaces = [ns for ns in namespaces if ns.name not in system_namespaces]

        ns_score = 0
        if len(user_namespaces) == 0:
            evidence.append("✗ 未划分业务命名空间 (所有负载可能在 default 中)")
        else:
            ns_score += 1
            evidence.append(f"✓ 已划分 {len(user_namespaces)} 个业务命名空间")

            quota_ns_count = len(
                set(q.namespace for q in quotas if q.namespace not in system_namespaces))
            quota_ratio = quota_ns_count / len(user_namespaces) if user_namespaces else 0

            quota_quality_score = 0
            quality_details = []

            for q in quotas:
                if q.namespace in system_namespaces:
                    continue
                hard = q.hard or {}
                has_cpu_limit = any(k in hard for k in ["limits.cpu", "cpu", "requests.cpu"])
                has_mem_limit = any(k in hard for k in ["limits.memory", "memory", "requests.memory"])
                has_pod_limit = "pods" in hard

                quality_points = sum([has_cpu_limit, has_mem_limit, has_pod_limit])
                if quality_points >= 2:
                    quota_quality_score += 1
                    quality_details.append(f"{q.namespace}: 完整")
                elif quality_points == 1:
                    quality_details.append(f"{q.namespace}: 部分")

            if quota_ratio >= 0.8:
                quality_ratio = quota_quality_score / quota_ns_count if quota_ns_count > 0 else 0
                if quality_ratio >= 0.6:
                    ns_score += 1
                    evidence.append(
                        f"✓ ResourceQuota 覆盖完善且配置质量高 ({quota_quality_score}/{quota_ns_count} 高质量)")
                else:
                    ns_score += 0.5
                    evidence.append(f"⚠️ ResourceQuota 覆盖完善但质量一般，建议补充 limits.cpu/memory")
            elif quota_ratio > 0:
                ns_score += 0.3
                evidence.append(f"⚠️ 仅 {quota_ns_count}/{len(user_namespaces)} 个命名空间配置了 ResourceQuota")
            else:
                evidence.append("✗ 未配置 ResourceQuota (存在资源争抢风险)")

            pol_ns_count = len(
                set(p.namespace for p in net_pols if p.namespace not in system_namespaces))
            pol_ratio = pol_ns_count / len(user_namespaces) if user_namespaces else 0

            strict_pol_count = 0
            for pol in net_pols:
                if pol.namespace in system_namespaces:
                    continue

                ingress_rules = pol.ingress_rules or []
                egress_rules = pol.egress_rules or []

                has_effective_rules = len(ingress_rules) > 0 or len(egress_rules) > 0
                is_not_allow_all = not any(
                    (r.get("from") == [] or r.get("from") is None) and not r.get("namespaceSelector")
                    for r in ingress_rules
                )

                if has_effective_rules and is_not_allow_all:
                    strict_pol_count += 1

            if pol_ratio >= 0.8:
                strict_ratio = strict_pol_count / pol_ns_count if pol_ns_count > 0 else 0
                if strict_ratio >= 0.5:
                    ns_score += 1
                    evidence.append(f"✓ NetworkPolicy 覆盖完善且策略严格 ({strict_pol_count}/{pol_ns_count})")
                else:
                    ns_score += 0.5
                    evidence.append(f"⚠️ NetworkPolicy 覆盖完善但策略较宽松，建议收紧规则")
            elif pol_ratio > 0:
                ns_score += 0.3
                evidence.append(f"⚠️ 仅 {pol_ns_count}/{len(user_namespaces)} 个命名空间配置了 NetworkPolicy")
            else:
                evidence.append("✗ 未配置 NetworkPolicy (网络扁平，无隔离)")

        score += min(ns_score, 3)

        # --- 2. 节点池隔离 (最高 3 分) ---
        node_pools_map = {}
        pool_label_keys = [
            "node.kubernetes.io/nodepool", "agentpool", "node-pool", "nodepool",
            "alibabacloud.com/nodepool-id", "eks.amazonaws.com/nodegroup",
            "gke.googleusercontent.com/nodepool"
        ]

        for node in nodes:
            pool_name = "default-unlabeled"
            for key in pool_label_keys:
                if key in (node.labels or {}):
                    pool_name = node.labels[key]
                    break

            if pool_name not in node_pools_map:
                node_pools_map[pool_name] = {"count": 0, "has_taint": False}

            node_pools_map[pool_name]["count"] += 1

            if node.taints and len(node.taints) > 0:
                node_pools_map[pool_name]["has_taint"] = True

        pool_count = len(node_pools_map)
        tainted_pool_count = len(
            [p for p, info in node_pools_map.items() if info["has_taint"] and p != "default-unlabeled"])

        pool_score = 0
        if pool_count <= 1:
            evidence.append("✗ 单节点池架构，无物理隔离")
        else:
            evidence.append(f"✓ 检测到 {pool_count} 个节点池")

            pool_score += 1

            if tainted_pool_count >= 1:
                pool_score += 2
                evidence.append(f"✓ 发现 {tainted_pool_count} 个节点池配置了污点 (Taints)，具备专用调度能力")
            else:
                evidence.append("⚠️ 节点池未配置污点 (Taints)，Pod 可能跨池调度，物理隔离失效")

        score += min(pool_score, 3)

        final_score = min(round(score), 6)

        if final_score >= 5:
            conclusion = "资源隔离架构完善 (多命名空间+配额+网络策略+专用节点池)"
        elif final_score >= 4:
            conclusion = "资源隔离良好，但部分细节需优化 (如补充网络策略或污点)"
        elif final_score >= 2:
            conclusion = "具备基础隔离框架，但缺乏关键防护 (Quota/NetworkPolicy/Taints)"
            if ns_score < 2:
                conclusion += " (强烈建议配置 ResourceQuota)"
            if pool_score < 2:
                conclusion += " (建议配置节点污点以实现物理隔离)"
        elif final_score > 0:
            conclusion = "资源隔离严重不足，存在高风险的吵闹邻居效应"
        else:
            return self._not_scored("未实施任何资源隔离措施", evidence)

        return self._scored(final_score, conclusion, evidence)


class RmQuotaAnalyzer(Analyzer):
    """
    资源配额分析器
    
    评估标准：对所有命名空间/项目设置了明确的 ResourceQuota (CPU/Mem/PVC数量限制)
    
    数据来源：
    - kube-state-metrics：kube_resourcequota_hard、kube_resourcequota_used
    - ACK API：GET /api/v1/namespaces/{ns}/resourcequotas
    """

    def key(self) -> str:
        return "rm_quota"

    def dimension(self) -> str:
        return "Elasticity"

    def category(self) -> str:
        return "资源管理能力"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return ["k8s.resourcequota.list", "k8s.namespace.list"]

    def analyze(self, store) -> ScoreResult:
        quotas: list[K8sResourceQuotaRecord] = store.get("k8s.resourcequota.list")
        namespaces: list[K8sNamespaceRecord] = store.get("k8s.namespace.list")

        system_namespaces = {"default", "kube-system", "kube-public", "kube-node-lease"}
        user_namespaces = [ns for ns in namespaces if ns.name not in system_namespaces]

        if not user_namespaces:
            return self._not_scored("未发现业务命名空间")

        if not quotas:
            return self._not_scored(
                "未配置 ResourceQuota",
                [f"共 {len(user_namespaces)} 个业务命名空间，均未设置配额"]
            )

        ns_with_quota = set(q.namespace for q in quotas)
        user_ns_names = set(ns.name for ns in user_namespaces)
        covered_ns = ns_with_quota & user_ns_names

        coverage = len(covered_ns) / len(user_namespaces) if user_namespaces else 0

        evidence = [
            f"ResourceQuota 数量: {len(quotas)}",
            f"覆盖业务命名空间: {len(covered_ns)}/{len(user_namespaces)} ({coverage * 100:.0f}%)"
        ]

        high_quality_count = 0
        medium_quality_count = 0
        basic_quality_count = 0

        for q in quotas:
            if q.namespace in system_namespaces:
                continue

            hard = q.hard or {}

            has_limits_cpu = "limits.cpu" in hard
            has_limits_memory = "limits.memory" in hard
            has_requests_cpu = "requests.cpu" in hard or "cpu" in hard
            has_requests_memory = "requests.memory" in hard or "memory" in hard
            has_pods = "pods" in hard

            if has_limits_cpu and has_limits_memory:
                high_quality_count += 1
            elif has_requests_cpu or has_requests_memory:
                medium_quality_count += 1
            elif has_pods:
                basic_quality_count += 1

        total_user_quotas = high_quality_count + medium_quality_count + basic_quality_count

        high_quality_ratio = high_quality_count / total_user_quotas if total_user_quotas > 0 else 0
        medium_quality_ratio = medium_quality_count / total_user_quotas if total_user_quotas > 0 else 0

        if high_quality_count > 0:
            evidence.append(f"✓ 高质量配额 (含 limits): {high_quality_count} 个")
        if medium_quality_count > 0:
            evidence.append(f"⚠️ 中等质量配额 (仅 requests): {medium_quality_count} 个 (建议补充 limits)")
        if basic_quality_count > 0:
            evidence.append(f"ℹ️ 基础配额 (仅 pods): {basic_quality_count} 个")

        score = 0.0

        coverage_score = coverage * 3
        score += coverage_score

        quality_bonus = high_quality_ratio * 2
        score += quality_bonus

        medium_bonus = medium_quality_ratio * 0.5
        score += medium_bonus

        if coverage >= 1.0:
            score += 1
            evidence.append("✓ 所有业务命名空间均已配置 ResourceQuota")

        final_score = min(round(score), 6)

        if final_score >= 5:
            conclusion = "ResourceQuota 配置完善，覆盖度高且质量优秀 (含 limits 限制)"
        elif final_score >= 4:
            conclusion = "ResourceQuota 配置良好，建议补充 limits 限制以增强资源隔离"
        elif final_score >= 3:
            conclusion = "ResourceQuota 具备基础覆盖，建议提升覆盖度并补充 limits"
        elif final_score >= 2:
            conclusion = "ResourceQuota 配置不足，存在资源争抢风险"
        elif final_score > 0:
            conclusion = "ResourceQuota 严重缺失，强烈建议完善配置"
        else:
            return self._not_scored("业务命名空间未配置有效的 ResourceQuota", evidence)

        evidence.append(f"综合评分: {score:.1f} → {final_score}分")

        return self._scored(final_score, conclusion, evidence)


class RmReservationAnalyzer(Analyzer):
    """
    资源预留分析器
    
    评估标准：关键业务拥有 Guaranteed QoS 等级或专属节点池/预留实例保障
    
    数据来源：
    - UModel：kube_pod_container_resource_requests/limits
    - 判断逻辑：若 requests == limits，则为 Guaranteed QoS
    - 检查是否使用了 nodeSelector 或 taints/tolerations 调度到专用资源池
    """

    def key(self) -> str:
        return "rm_reservation"

    def dimension(self) -> str:
        return "Elasticity"

    def category(self) -> str:
        return "资源管理能力"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return ["k8s.pod.list"]

    def analyze(self, store) -> ScoreResult:
        pods: list[K8sPodRecord] = store.get("k8s.pod.list")

        if not pods:
            return self._not_evaluated("未发现 Pod")

        guaranteed_count = 0
        burstable_high_quality = 0
        burstable_low_quality = 0
        besteffort_count = 0

        for p in pods:
            qos = p.qos_class

            if qos == "Guaranteed":
                guaranteed_count += 1
            elif qos == "Burstable":
                req = p.resource_requests or {}
                lim = p.resource_limits or {}

                cpu_reasonable = False
                mem_reasonable = False

                if "cpu" in req and "cpu" in lim:
                    try:
                        req_cpu = self._parse_cpu(req["cpu"])
                        lim_cpu = self._parse_cpu(lim["cpu"])
                        if 1 <= lim_cpu / req_cpu <= 4:
                            cpu_reasonable = True
                    except (ValueError, ZeroDivisionError):
                        pass

                if "memory" in req and "memory" in lim:
                    try:
                        req_mem = self._parse_memory(req["memory"])
                        lim_mem = self._parse_memory(lim["memory"])
                        if 1 <= lim_mem / req_mem <= 4:
                            mem_reasonable = True
                    except (ValueError, ZeroDivisionError):
                        pass

                # 至少有一个资源配置且比例合理才算高质量
                if cpu_reasonable or mem_reasonable:
                    burstable_high_quality += 1
                else:
                    burstable_low_quality += 1

            elif qos == "BestEffort":
                besteffort_count += 1

        total = len(pods)
        guaranteed_ratio = guaranteed_count / total if total else 0
        besteffort_ratio = besteffort_count / total if total else 0
        burstable_high_ratio = burstable_high_quality / total if total else 0
        burstable_low_ratio = burstable_low_quality / total if total else 0

        effective_configured_ratio = (guaranteed_count + burstable_high_quality) / total if total else 0

        dedicated_schedule_count = 0
        for p in pods:
            has_node_selector = bool(p.node_selector)
            has_affinity = bool(p.affinity)

            if has_node_selector or has_affinity:
                dedicated_schedule_count += 1

        dedicated_schedule_ratio = dedicated_schedule_count / total if total else 0

        # --- 构建证据 ---
        evidence = [
            f"Pod 总数: {total}",
            f"Guaranteed (强保障): {guaranteed_count} ({guaranteed_ratio * 100:.1f}%)",
            f"Burstable 高质量 (limits/requests 合理): {burstable_high_quality} ({burstable_high_ratio * 100:.1f}%)",
            f"Burstable 低质量 (limits 过大): {burstable_low_quality} ({burstable_low_ratio * 100:.1f}%)",
            f"BestEffort (无保障): {besteffort_count} ({besteffort_ratio * 100:.1f}%)",
            f"有效资源配置覆盖率: {effective_configured_ratio * 100:.1f}%"
        ]

        # --- 平滑评分计算 ---
        score = 0.0

        # 1. 有效资源配置评分 (最高 3 分)
        # Guaranteed 全分，高质量 Burstable 半分
        config_score = guaranteed_ratio * 3 + burstable_high_ratio * 1.5
        score += min(config_score, 3)

        guaranteed_bonus = guaranteed_ratio * 2
        score += guaranteed_bonus

        if dedicated_schedule_ratio >= 0.3:
            score += 0.5
            evidence.append(f"✓ {dedicated_schedule_count} 个 Pod 配置了调度策略")

        if besteffort_ratio > 0.3:
            penalty = min(besteffort_ratio * 1.5, 1.0)  # 最多扣 1 分
            score -= penalty
            evidence.append(f"⚠️ BestEffort 比例过高 ({besteffort_ratio * 100:.1f}%)，影响稳定性")
        elif besteffort_ratio > 0.1:
            score -= 0.3
            evidence.append(f"⚠️ 存在部分 BestEffort Pod ({besteffort_ratio * 100:.1f}%)")

        if burstable_low_ratio > 0.3:
            score -= 0.5
            evidence.append(f"⚠️ 大量 Burstable Pod 的 limits/requests 比例不合理")

        score = max(score, 0)

        final_score = min(round(score), 6)

        if final_score >= 5:
            conclusion = "资源治理完善：高比例 Guaranteed + 合理的 Burstable 配置，架构稳健"
        elif final_score >= 4:
            conclusion = "资源治理良好：大部分 Pod 有有效资源限制，建议提升 Guaranteed 比例"
        elif final_score >= 3:
            conclusion = "资源治理一般：部分 Pod 资源配置不足，建议完善 limits/requests 配置"
        elif final_score >= 2:
            conclusion = "资源治理较弱：存在较多低质量配置，建议消除 BestEffort 并优化 Burstable"
        elif final_score > 0:
            conclusion = "资源治理不足：大量 Pod 缺乏有效资源保障，集群稳定性风险高"
        else:
            return self._not_scored("资源治理严重缺失：几乎无 Pod 配置有效资源限制", evidence)

        evidence.append(f"综合评分: {score:.1f} → {final_score}分")

        return self._scored(final_score, conclusion, evidence)

    @staticmethod
    def _parse_cpu(cpu_str: str) -> float:
        """解析 CPU 值，返回核心数"""
        if isinstance(cpu_str, (int, float)):
            return float(cpu_str)
        cpu_str = str(cpu_str).strip()
        if cpu_str.endswith("m"):
            return float(cpu_str[:-1]) / 1000
        return float(cpu_str)

    @staticmethod
    def _parse_memory(mem_str: str) -> float:
        """解析内存值，返回 MiB"""
        if isinstance(mem_str, (int, float)):
            return float(mem_str)
        mem_str = str(mem_str).strip().upper()
        units = {"Ki": 1 / 1024, "Mi": 1, "Gi": 1024, "Ti": 1024 * 1024,
                 "K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 * 1024}
        for unit, multiplier in units.items():
            if mem_str.endswith(unit.upper()):
                return float(mem_str[:-len(unit)]) * multiplier
        # 纯数字，假设为字节
        try:
            return float(mem_str) / (1024 * 1024)
        except ValueError:
            return 0


class RmDynamicAllocAnalyzer(Analyzer):
    """
    动态分配分析器
    
    评估标准：支持混合部署（在线/离线业务混部）或基于潮汐效应的动态资源超卖/回收
    
    数据来源：
    - UModel：k8s.metric.ack_cost_insights，集群资源成本和利用率数据
    - 分析集群整体资源利用率曲线
    - ACK API：检查是否使用了 Descheduler 或 FinOps 混部调度器
    """

    def key(self) -> str:
        return "rm_dynamic_alloc"

    def dimension(self) -> str:
        return "Elasticity"

    def category(self) -> str:
        return "资源管理能力"

    def max_score(self) -> int:
        return 7

    def required_data(self) -> list[str]:
        return ["k8s.pod.list", "k8s.node.list"]

    def analyze(self, store) -> ScoreResult:
        pods: list[K8sPodRecord] = store.get("k8s.pod.list")
        nodes: list[K8sNodeRecord] = store.get("k8s.node.list")

        if not pods or not nodes:
            return self._not_evaluated("数据不足，无法评估动态资源分配能力")

        evidence = []
        score = 0.0

        # --- 1. 识别在线/离线业务 ---
        offline_labels = [
            "batch", "cronjob", "job", "offline", "best-effort",
            "spark-role", "flink-role", "hadoop-role", "training"
        ]

        online_pods = []
        offline_pods = []

        for p in pods:
            labels = p.labels or {}
            labels_lower = {k.lower(): v.lower() for k, v in labels.items()}

            is_offline = False
            for label_key in offline_labels:
                if any(label_key in k or label_key in v for k, v in labels_lower.items()):
                    is_offline = True
                    break

            if p.qos_class == "BestEffort":
                is_offline = True

            if is_offline:
                offline_pods.append(p)
            else:
                online_pods.append(p)

        online_ratio = len(online_pods) / len(pods) if pods else 0
        offline_ratio = len(offline_pods) / len(pods) if pods else 0

        evidence.append(f"在线业务 Pod: {len(online_pods)} ({online_ratio * 100:.1f}%)")
        evidence.append(f"离线业务 Pod: {len(offline_pods)} ({offline_ratio * 100:.1f}%)")

        # --- 2. 检查混部情况 (最高 3 分) ---
        mixed_nodes_count = 0
        total_active_nodes = 0

        for node in nodes:
            node_online = [p for p in online_pods if p.node_name == node.name]
            node_offline = [p for p in offline_pods if p.node_name == node.name]

            if node_online or node_offline:
                total_active_nodes += 1

            if node_online and node_offline:
                mixed_nodes_count += 1

        mixed_ratio = mixed_nodes_count / total_active_nodes if total_active_nodes > 0 else 0

        mixed_score = mixed_ratio * 3
        score += mixed_score

        if mixed_nodes_count > 0:
            evidence.append(
                f"✓ {mixed_nodes_count}/{total_active_nodes} 个节点存在在线/离线混部 "
                f"(混部率: {mixed_ratio * 100:.1f}%)"
            )
        else:
            if offline_pods:
                evidence.append("⚠️ 存在离线业务但未与在线业务混部 (可能已物理隔离)")
            else:
                evidence.append("ℹ️ 未检测到离线业务，无混部场景")

        nodes_with_significant_reserved = 0
        reserved_details = []

        for node in nodes:
            cap_cpu = node.capacity.get("cpu", "0")
            alloc_cpu = node.allocatable.get("cpu", "0")

            try:
                cap_cpu_val = self._parse_cpu(str(cap_cpu))
                alloc_cpu_val = self._parse_cpu(str(alloc_cpu))

                if cap_cpu_val > 0:
                    reserved_ratio = (cap_cpu_val - alloc_cpu_val) / cap_cpu_val
                    if reserved_ratio >= 0.05:
                        nodes_with_significant_reserved += 1
                        reserved_details.append(f"{node.name}: {reserved_ratio * 100:.1f}%")
            except (ValueError, TypeError):
                continue

        reserved_node_ratio = nodes_with_significant_reserved / len(nodes) if nodes else 0

        reserved_score = reserved_node_ratio * 2
        score += reserved_score

        if nodes_with_significant_reserved > 0:
            evidence.append(
                f"✓ {nodes_with_significant_reserved}/{len(nodes)} 个节点配置了资源预留 "
                f"(预留率 >= 5%)"
            )
        else:
            evidence.append("✗ 未检测到有效的节点资源预留配置 (预留率 < 5%)")

        # --- 4. 检查混部调度系统特征 (最高 1.5 分) ---
        colocation_systems = {
            "koordinator": ["koordinator", "koord", "colocation-profile"],
            "volcano": ["volcano", "volcano.sh", "batch.volcano.sh"],
            "yunikorn": ["yunikorn", "apache.yunikorn"],
            "descheduler": ["descheduler"]
        }

        detected_systems = []
        for node in nodes:
            labels = node.labels or {}
            annotations = node.annotations or {}

            for system, keywords in colocation_systems.items():
                for k, v in list(labels.items()) + list(annotations.items()):
                    k_lower, v_lower = k.lower(), v.lower()
                    if any(kw in k_lower or kw in v_lower for kw in keywords):
                        if system not in detected_systems:
                            detected_systems.append(system)
                        break

        if detected_systems:
            system_score = min(len(detected_systems) * 0.5, 1.5)
            score += system_score
            evidence.append(f"✓ 检测到混部调度系统: {', '.join(detected_systems)}")
        else:
            evidence.append("ℹ️ 未检测到主流混部调度系统 (Koordinator/Volcano/YuniKorn)")

        # --- 5. BestEffort 风险评估 (惩罚项) ---
        besteffort_pods = [p for p in pods if p.qos_class == "BestEffort"]
        be_ratio = len(besteffort_pods) / len(pods) if pods else 0

        if be_ratio > 0.3:
            penalty = min(be_ratio * 2, 1.5)
            score -= penalty
            evidence.append(f"⚠️ BestEffort Pod 占比 {be_ratio * 100:.1f}%，存在资源竞争风险")
        elif be_ratio > 0.1:
            score -= 0.3
            evidence.append(f"⚠️ 存在部分 BestEffort Pod ({be_ratio * 100:.1f}%)")

        # --- 6. Guaranteed 与 BestEffort 共存风险 ---
        guaranteed_pods = [p for p in pods if p.qos_class == "Guaranteed"]
        if guaranteed_pods and besteffort_pods and mixed_ratio > 0.3:
            if not detected_systems:
                score -= 0.5
                evidence.append("⚠️ Guaranteed 与 BestEffort 混部但无调度系统保护，存在干扰风险")

        score = max(score, 0)
        final_score = min(round(score), 7)

        if final_score >= 6:
            conclusion = "具备成熟的动态资源分配与混部能力 (在线离线共存 + 资源预留 + 专用调度系统)"
        elif final_score >= 4:
            conclusion = "具备基础混部能力，建议完善资源预留或引入混部调度系统"
        elif final_score >= 2:
            conclusion = "具备初步混部特征，需加强资源隔离和调度管理"
        elif final_score > 0:
            conclusion = "动态分配能力较弱，建议优化资源配置和隔离策略"
        else:
            if be_ratio > 0.3:
                return self._not_scored("存在大量低质量 Pod 且无混部管理，资源稳定性风险高", evidence)
            return self._not_scored("未实现动态资源分配或混部部署", evidence)

        evidence.append(f"综合评分: {score:.1f} → {final_score}分")

        return self._scored(final_score, conclusion, evidence)

    @staticmethod
    def _parse_cpu(cpu_str: str) -> float:
        """解析 CPU 值，返回核心数"""
        cpu_str = str(cpu_str).strip()
        if cpu_str.endswith("m"):
            return float(cpu_str[:-1]) / 1000
        try:
            return float(cpu_str)
        except ValueError:
            return 0


RM_ANALYZERS = [
    RmIsolationAnalyzer(),
    RmQuotaAnalyzer(),
    RmReservationAnalyzer(),
    RmDynamicAllocAnalyzer(),
]
