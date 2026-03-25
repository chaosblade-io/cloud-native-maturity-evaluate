"""
Resilience 维度 - 高可用性 (High Availability) 分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)              | 分值 | 评分标准                                                       |
| ha_redundancy             | 7    | 冗余设计：所有关键组件至少双副本/主从模式运行，无单点故障       |
| ha_multi_zone             | 8    | 多可用区部署：应用实例均匀分布在至少 2 个不同的可用区           |
| ha_load_balancing         | 5    | 负载均衡：入口流量和内部服务间调用均通过负载均衡器分发         |
| ha_global_dist            | 5    | 全球/多活分布：(高阶项) 跨地域的流量调度或异地多活架构         |
"""
from sesora.core.analyzer import Analyzer, ScoreResult
from sesora.schema.k8s import K8sDeploymentRecord, K8sStatefulSetRecord, K8sNodeRecord, K8sIngressRecord, K8sServiceRecord
from sesora.schema.rds_oss import GtmAddressPoolRecord


class HaRedundancyAnalyzer(Analyzer):
    """
    冗余设计分析器
    
    评估标准：所有关键组件（应用、DB、中间件）是否至少以双副本/主从模式运行，无单点故障 (SPOF)
    
    数据来源：
    - UModel：kube_deployment_spec_replicas，检查所有 Deployment 的副本数
    - UModel：kube_statefulset_replicas，检查 StatefulSet 副本数
    """

    def key(self) -> str:
        return "ha_redundancy"

    def dimension(self) -> str:
        return "Resilience"

    def category(self) -> str:
        return "高可用性"

    def max_score(self) -> int:
        return 7

    def required_data(self) -> list[str]:
        return ["k8s.deployment.list"]

    def optional_data(self) -> list[str]:
        return ["k8s.statefulset.list"]

    def analyze(self, store) -> ScoreResult:
        deployments: list[K8sDeploymentRecord] = store.get("k8s.deployment.list")

        all_workloads = []
        for d in deployments:
            all_workloads.append({
                "name": f"{d.namespace}/{d.name}",
                "replicas": d.replicas,
                "type": "Deployment"
            })

        if store.available("k8s.statefulset.list"):
            statefulsets: list[K8sStatefulSetRecord] = store.get("k8s.statefulset.list")
            for s in statefulsets:
                all_workloads.append({
                    "name": f"{s.namespace}/{s.name}",
                    "replicas": s.replicas,
                    "type": "StatefulSet"
                })

        if not all_workloads:
            return self._not_evaluated("未发现任何工作负载")

        total_count = len(all_workloads)

        high_availability = []
        basic_redundancy = []
        single_point = []
        zero_replicas = []

        for w in all_workloads:
            replicas = w["replicas"]
            if replicas >= 3:
                high_availability.append(w)
            elif replicas == 2:
                basic_redundancy.append(w)
            elif replicas == 1:
                single_point.append(w)
            else:
                zero_replicas.append(w)

        score = 0.0
        evidence = []
        warnings = []

        # --- 1. 高可用覆盖率评分（最高 3 分）---
        ha_count = len(high_availability)
        ha_ratio = ha_count / total_count

        if ha_ratio >= 0.7:
            score += 3.0
            evidence.append(f"✓ 高可用部署优秀: {ha_count}/{total_count} ({ha_ratio:.0%}) ≥3副本")
        elif ha_ratio >= 0.5:
            score += 2.0
            evidence.append(f"✓ 高可用部署良好: {ha_count}/{total_count} ({ha_ratio:.0%}) ≥3副本")
        elif ha_ratio >= 0.3:
            score += 1.0
            evidence.append(f"ℹ️ 高可用部署中等: {ha_count}/{total_count} ({ha_ratio:.0%}) ≥3副本")
            warnings.append("高可用部署（≥3副本）比例偏低")
        else:
            warnings.append(f"高可用部署严重不足 ({ha_ratio:.0%})，建议关键服务至少3副本")
            evidence.append(f"⚠️ 高可用部署不足: {ha_count}/{total_count} ({ha_ratio:.0%}) ≥3副本")

        # --- 2. 基本冗余覆盖率评分（最高 2 分）---
        basic_count = len(basic_redundancy)
        basic_ratio = basic_count / total_count

        if basic_ratio >= 0.5:
            score += 2.0
            evidence.append(f"✓ 基本冗余良好: {basic_count}/{total_count} ({basic_ratio:.0%}) 2副本")
        elif basic_ratio >= 0.3:
            score += 1.0
            evidence.append(f"ℹ️ 基本冗余中等: {basic_count}/{total_count} ({basic_ratio:.0%}) 2副本")
        elif basic_count > 0:
            score += 0.5
            evidence.append(f"⚠️ 基本冗余较少: {basic_count}/{total_count} ({basic_ratio:.0%}) 2副本")

        # --- 3. 单点风险检查（扣分项）---
        single_count = len(single_point)
        single_ratio = single_count / total_count

        if single_count > 0:
            if single_ratio <= 0.1:
                score -= 0.5
                warnings.append(f"存在少量单点风险: {single_count} 个单副本工作负载")
            elif single_ratio <= 0.2:
                score -= 1.0
                warnings.append(f"单点风险较高: {single_count} 个单副本工作负载 ({single_ratio:.0%})")
            elif single_ratio <= 0.3:
                score -= 1.5
                warnings.append(f"单点风险严重: {single_count} 个单副本工作负载 ({single_ratio:.0%})")
            else:
                score -= 2.0
                warnings.append(
                    f"单点风险极高: {single_count} 个单副本工作负载 ({single_ratio:.0%})，系统存在严重可用性隐患")

            evidence.append(f"⚠️ 单点风险: {single_count}/{total_count} ({single_ratio:.0%}) 单副本")

        if zero_replicas:
            warnings.append(f"发现 {len(zero_replicas)} 个零副本工作负载，可能处于异常状态")
            evidence.append(f"⚠️ 零副本异常: {len(zero_replicas)} 个")

        for w in high_availability[:3]:
            evidence.append(f"✅ {w['type']} {w['name']}: {w['replicas']} 副本")

        for w in basic_redundancy[:2]:
            evidence.append(f"✓ {w['type']} {w['name']}: 2 副本")

        for w in single_point[:3]:
            evidence.append(f"⚠️ {w['type']} {w['name']}: 单副本（单点风险）")

        final_score = max(min(round(score, 1), 7), 0)

        if final_score >= 6:
            status_msg = "冗余设计成熟：高可用部署全面，单点风险可控"
        elif final_score >= 4.5:
            status_msg = "冗余设计良好：基本满足高可用要求，少量单点需关注"
        elif final_score >= 3:
            status_msg = "冗余设计基础：存在单点风险，建议提升关键服务副本数"
        elif final_score >= 1.5:
            status_msg = "冗余设计薄弱：单点风险较高，系统可用性存隐患"
        else:
            status_msg = "冗余设计缺失：大量单点故障风险，亟需改进"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(round(final_score), status_msg, evidence)


class HaMultiZoneAnalyzer(Analyzer):
    """
    多可用区部署分析器
    
    评估标准：应用实例是否均匀分布在至少 2 个不同的可用区 (AZ)，且存储支持跨 AZ 同步
    
    数据来源：
    - UModel：k8s.node entity_set 的 labels 字段，包含 topology.kubernetes.io/zone 标签
    - 通过 Pod-Node 关系可以推算 Pod 的可用区分布
    """

    def key(self) -> str:
        return "ha_multi_zone"

    def dimension(self) -> str:
        return "Resilience"

    def category(self) -> str:
        return "高可用性"

    def max_score(self) -> int:
        return 8

    def required_data(self) -> list[str]:
        return ["k8s.node.list"]

    def analyze(self, store) -> ScoreResult:
        nodes: list[K8sNodeRecord] = store.get("k8s.node.list")

        if not nodes:
            return self._not_evaluated("未发现任何节点")

        zones = {}
        for node in nodes:
            zone = node.zone or node.labels.get("topology.kubernetes.io/zone", "unknown")
            zones[zone] = zones.get(zone, 0) + 1

        known_zones = {z: c for z, c in zones.items() if z != "unknown"}
        unknown_count = zones.get("unknown", 0)

        score = 0.0
        evidence = []
        warnings = []

        zone_count = len(known_zones)
        total_known_nodes = sum(known_zones.values())

        if zone_count == 0:
            if unknown_count > 0:
                warnings.append(f"所有 {unknown_count} 个节点均缺少可用区标签，无法评估多可用区部署")
                evidence.append(f"⚠️ 无法识别可用区: {unknown_count} 个节点")
                return self._scored(0, "无法评估多可用区部署：节点缺少可用区标签", evidence)
            return self._not_scored("无法识别节点的可用区信息", ["无有效节点数据"])

        for zone, count in sorted(known_zones.items(), key=lambda x: -x[1]):
            evidence.append(f"{zone}: {count} 个节点")

        if unknown_count > 0:
            warnings.append(f"{unknown_count} 个节点缺少可用区标签")
            evidence.append(f"⚠️ 未知可用区: {unknown_count} 个节点")

        # --- 1. 可用区数量评分（最高 4 分）---
        if zone_count >= 3:
            score += 4.0
            evidence.append(f"✓ 可用区数量优秀: {zone_count} 个可用区")
        elif zone_count == 2:
            score += 3.0
            evidence.append(f"✓ 可用区数量良好: {zone_count} 个可用区")
        elif zone_count == 1:
            score += 0.5
            warnings.append("所有节点集中在单一可用区，存在严重单点故障风险")
            evidence.append(f"⚠️ 单可用区: 仅 {list(known_zones.keys())[0]}")

        # --- 2. 可用区分布均衡性评分（最高 3 分）---
        if zone_count >= 2 and total_known_nodes > 0:
            zone_counts = list(known_zones.values())
            max_count = max(zone_counts)
            min_count = min(zone_counts)

            balance_ratio = min_count / max_count if max_count > 0 else 0

            if balance_ratio >= 0.8:
                score += 3.0
                evidence.append(f"✓ 分布均衡性优秀: 各可用区节点数差异 ≤20%")
            elif balance_ratio >= 0.6:
                score += 2.0
                evidence.append(f"✓ 分布均衡性良好: 各可用区节点数差异 ≤40%")
            elif balance_ratio >= 0.4:
                score += 1.0
                warnings.append(f"可用区分布不均衡: 最小区/最大区 = {balance_ratio:.0%}")
                evidence.append(f"⚠️ 分布不均衡: {min_count} vs {max_count}")
            else:
                score += 0.5
                warnings.append(f"可用区分布严重不均衡: 最小区仅 {min_count} 节点，最大区 {max_count} 节点")
                evidence.append(f"⚠️ 分布严重不均衡: {min_count} vs {max_count}")

        # --- 3. 单可用区惩罚（扣分项）---
        if zone_count == 1:
            score = min(score, 2.0)

        final_score = max(min(round(score, 1), 8), 0)

        if final_score >= 7:
            status_msg = "多可用区部署成熟：可用区数量充足、分布均衡"
        elif final_score >= 5.5:
            status_msg = "多可用区部署良好：满足高可用基本要求"
        elif final_score >= 4:
            status_msg = "多可用区部署基础：可用区数量或分布有改进空间"
        elif final_score >= 2:
            status_msg = "多可用区部署薄弱：存在单点风险或分布不均衡"
        else:
            status_msg = "多可用区部署缺失：单可用区或无法评估"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(round(final_score), status_msg, evidence)


class HaLoadBalancingAnalyzer(Analyzer):
    """
    负载均衡分析器
    
    评估标准：入口流量和内部服务间调用是否均通过负载均衡器分发，且健康检查正常
    
    数据来源：
    - UModel：k8s.ingress entity_set，Ingress 列表
    - UModel：k8s.metric.ingress_deployment，Ingress 流量分发指标
    """

    def key(self) -> str:
        return "ha_load_balancing"

    def dimension(self) -> str:
        return "Resilience"

    def category(self) -> str:
        return "高可用性"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["k8s.ingress.list", "k8s.service.list"]

    def analyze(self, store) -> ScoreResult:
        ingresses: list[K8sIngressRecord] = store.get("k8s.ingress.list")
        services: list[K8sServiceRecord] = store.get("k8s.service.list")

        score = 0.0
        evidence = []
        warnings = []

        # --- 1. 入口流量负载均衡评分（最高 3 分）---
        ingress_count = len(ingresses)
        has_ingress = ingress_count > 0

        lb_services = [s for s in services if s.type == "LoadBalancer"]
        lb_count = len(lb_services)

        if has_ingress and lb_count > 0:
            score += 3.0
            evidence.append(f"✓ 入口负载均衡完善: {ingress_count} 个 Ingress, {lb_count} 个 LoadBalancer")
        elif has_ingress:
            score += 2.5
            evidence.append(f"✓ 入口负载均衡良好: {ingress_count} 个 Ingress")
        elif lb_count > 0:
            score += 2.0
            evidence.append(f"✓ 入口负载均衡基础: {lb_count} 个 LoadBalancer")
            warnings.append("缺少 Ingress，HTTP/HTTPS 流量路由能力有限")
        else:
            score += 0.0
            warnings.append("未配置 Ingress 或 LoadBalancer，缺少入口流量负载均衡")
            evidence.append("⚠️ 无入口负载均衡配置")

        # --- 2. 内部服务负载均衡评分（最高 2 分）---
        clusterip_services = [s for s in services if s.type == "ClusterIP"]
        headless_services = [s for s in services if s.type == "ClusterIP" and not s.cluster_ip]

        total_services = len(services)
        clusterip_count = len(clusterip_services)
        headless_count = len(headless_services)

        if total_services > 0:
            lb_service_count = clusterip_count - headless_count + lb_count
            internal_lb_ratio = lb_service_count / total_services

            if internal_lb_ratio >= 0.8:
                score += 2.0
                evidence.append(
                    f"✓ 内部负载均衡完善: {lb_service_count}/{total_services} 服务 ({internal_lb_ratio:.0%})")
            elif internal_lb_ratio >= 0.5:
                score += 1.5
                evidence.append(
                    f"✓ 内部负载均衡良好: {lb_service_count}/{total_services} 服务 ({internal_lb_ratio:.0%})")
            elif internal_lb_ratio >= 0.3:
                score += 1.0
                evidence.append(
                    f"ℹ️ 内部负载均衡中等: {lb_service_count}/{total_services} 服务 ({internal_lb_ratio:.0%})")
            elif internal_lb_ratio > 0:
                score += 0.5
                warnings.append(f"内部负载均衡覆盖率偏低 ({internal_lb_ratio:.0%})")
                evidence.append(f"⚠️ 内部负载均衡不足: {lb_service_count}/{total_services} 服务")
            else:
                warnings.append("未发现内部服务负载均衡配置")
                evidence.append("⚠️ 无内部负载均衡")

            if headless_count > 0:
                evidence.append(f"ℹ️ Headless Service: {headless_count} 个（有状态服务，无负载均衡）")

        # --- 3. 配置质量检查 ---
        nodeport_services = [s for s in services if s.type == "NodePort"]
        if nodeport_services:
            score -= 0.5
            warnings.append(
                f"发现 {len(nodeport_services)} 个 NodePort Service，生产环境建议使用 LoadBalancer 或 Ingress")
            evidence.append(f"⚠️ NodePort 配置: {len(nodeport_services)} 个")

        final_score = max(min(round(score, 1), 5), 0)

        if final_score >= 4.5:
            status_msg = "负载均衡成熟：入口和内部流量分发完善"
        elif final_score >= 3.5:
            status_msg = "负载均衡良好：基本满足流量分发需求"
        elif final_score >= 2.5:
            status_msg = "负载均衡基础：存在入口或内部分发不足"
        elif final_score >= 1:
            status_msg = "负载均衡薄弱：流量分发能力有限"
        else:
            status_msg = "负载均衡缺失：缺乏基本的流量分发能力"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(round(final_score), status_msg, evidence)


class HaGlobalDistAnalyzer(Analyzer):
    """
    全球/多活分布分析器
    
    评估标准：(可选高阶项) 是否实现了跨地域 (Region) 的流量调度或异地多活架构
    
    数据来源：
    - GTM API：地址池配置、健康检查策略、地理路由策略
    """

    def key(self) -> str:
        return "ha_global_dist"

    def dimension(self) -> str:
        return "Resilience"

    def category(self) -> str:
        return "高可用性"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["gtm.address_pool.list"]

    def analyze(self, store) -> ScoreResult:
        pools: list[GtmAddressPoolRecord] = store.get("gtm.address_pool.list")

        score = 0.0
        evidence = []
        warnings = []

        if not pools:
            evidence.append("ℹ️ 未配置 GTM 全局流量管理")
            return self._scored(
                0,
                "未配置全球/多活分布：可选高阶项，当前无跨地域流量调度能力",
                evidence
            )

        total_pools = len(pools)

        # --- 1. 地址池健康状态评分（最高 2 分）---
        active_pools = [p for p in pools if p.monitor_status == "OPEN"]
        inactive_pools = [p for p in pools if p.monitor_status != "OPEN"]

        if active_pools:
            active_ratio = len(active_pools) / total_pools

            if active_ratio >= 0.8:
                score += 2.0
                evidence.append(f"✓ 健康检查完善: {len(active_pools)}/{total_pools} 地址池活跃")
            elif active_ratio >= 0.5:
                score += 1.5
                evidence.append(f"✓ 健康检查良好: {len(active_pools)}/{total_pools} 地址池活跃")
            else:
                score += 0.5
                warnings.append(f"健康检查覆盖率偏低: 仅 {len(active_pools)}/{total_pools} 地址池活跃")
                evidence.append(f"⚠️ 健康检查不足: {len(active_pools)}/{total_pools} 地址池活跃")

            for p in active_pools[:3]:
                strategy_info = f", 策略: {p.lb_strategy}" if p.lb_strategy else ""
                evidence.append(f"✓ 地址池: {p.pool_name}{strategy_info}")
        else:
            warnings.append("所有地址池均未开启健康检查或处于非活跃状态")
            evidence.append(f"⚠️ 无活跃地址池: {total_pools} 个地址池均未开启监控")

        if inactive_pools:
            evidence.append(f"ℹ️ 非活跃地址池: {len(inactive_pools)} 个")

        # --- 2. 多地址池配置评分（最高 2 分）---
        if len(active_pools) >= 3:
            score += 2.0
            evidence.append(f"✓ 多活配置优秀: {len(active_pools)} 个活跃地址池")
        elif len(active_pools) == 2:
            score += 1.5
            evidence.append(f"✓ 多活配置良好: {len(active_pools)} 个活跃地址池")
        elif len(active_pools) == 1:
            score += 0.5
            warnings.append("仅配置单一活跃地址池，无异地多活能力")
            evidence.append(f"⚠️ 单地址池: 仅 {active_pools[0].pool_name} 活跃")

        # --- 3. 负载策略评分（最高 1 分）---
        smart_strategies = ["latency", "geo", "weight", "round_robin"]
        has_smart_strategy = False

        for p in active_pools:
            strategy = (p.lb_strategy or "").lower()
            if any(s in strategy for s in smart_strategies):
                has_smart_strategy = True
                break

        if has_smart_strategy:
            score += 1.0
            evidence.append("✓ 智能负载策略: 已配置基于延迟/地理位置/权重的调度策略")
        else:
            if active_pools:
                warnings.append("未配置智能负载均衡策略（如基于延迟、地理位置的调度）")
                evidence.append("ℹ️ 基础负载策略: 建议配置基于延迟或地理位置的智能调度")

        final_score = max(min(round(score, 1), 5), 0)

        if final_score >= 4.5:
            status_msg = "全球/多活分布成熟：多地址池、健康检查完善、智能调度"
        elif final_score >= 3.5:
            status_msg = "全球/多活分布良好：具备基本的异地多活能力"
        elif final_score >= 2:
            status_msg = "全球/多活分布基础：地址池配置或健康检查有待完善"
        elif final_score >= 1:
            status_msg = "全球/多活分布薄弱：单点配置或健康检查缺失"
        else:
            status_msg = "未配置全球/多活分布：可选高阶项，当前无跨地域能力"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(round(final_score), status_msg, evidence)


HA_ANALYZERS = [
    HaRedundancyAnalyzer(),
    HaMultiZoneAnalyzer(),
    HaLoadBalancingAnalyzer(),
    HaGlobalDistAnalyzer(),
]
