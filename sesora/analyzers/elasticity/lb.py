"""
Elasticity 维度 - 负载分发能力 (Load Distribution) 分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)      | 分值   | 评分标准                                                       |
| lb_capability     | 2-8    | 无/基础(L4):2分, 高级(L7路径/域名):5分, 全局/智能(GSLB):8分    |
| lb_algorithms     | 2-6    | 仅轮询:2分, +加权/最少连接:+2分, +一致性哈希/内容路由:+2分     |
| traffic_mgmt      | 0-12   | 流量治理策略覆盖度，每项约2分（流量分流/金丝雀/蓝绿/熔断等）   |
"""
from ...core.analyzer import Analyzer, ScoreResult
from ...schema.k8s import K8sIngressRecord, K8sServiceRecord, IstioVirtualServiceRecord, IstioDestinationRuleRecord
from ...schema.rds_oss import AlbListenerRecord, GtmAddressPoolRecord


class LbCapabilityAnalyzer(Analyzer):
    """
    负载均衡能力分析器
    
    评估标准（分层评分）：
    - 无/基础 (L4 Only): 2分
    - 高级 (L7, 基于路径/域名): 5分
    - 全局/智能 (GSLB, 延迟路由): 8分
    
    数据来源：
    - UModel：k8s.ingress entity_set，检查 Ingress 资源
    - ACK API：检查是否部署了 ALB Ingress Controller（L7）
    - GTM API：检查是否使用了全局流量管理
    """

    def key(self) -> str:
        return "lb_capability"

    def dimension(self) -> str:
        return "Elasticity"

    def category(self) -> str:
        return "负载分发能力"

    def max_score(self) -> int:
        return 8

    def required_data(self) -> list[str]:
        return ["k8s.service.list"]

    def optional_data(self) -> list[str]:
        return ["k8s.ingress.list", "alb.listener.list", "gtm.address_pool.list"]

    def analyze(self, store) -> ScoreResult:
        services: list[K8sServiceRecord] = store.get("k8s.service.list")

        if not services:
            return self._not_evaluated("未发现 K8s Service，无负载均衡基础")

        evidence = []
        current_score = 0
        has_l4 = False
        has_l7 = False
        has_gslb = False
        l7_security_level = 0

        # --- 1. L4 分析 ---
        lb_services = [s for s in services if s.type == "LoadBalancer"]
        nodeport_services = [s for s in services if s.type == "NodePort"]

        if lb_services:
            evidence.append(f"L4 LoadBalancer: {len(lb_services)} 个")
            has_l4 = True
        elif nodeport_services:
            evidence.append(f"L4 NodePort: {len(nodeport_services)} 个 (生产环境不推荐)")
            has_l4 = True
        else:
            evidence.append("仅内部 ClusterIP 服务 (无对外暴露能力)")

        # --- 2. L7 Ingress 分析 ---
        if store.available("k8s.ingress.list"):
            ingresses: list[K8sIngressRecord] = store.get("k8s.ingress.list")
            if ingresses:
                has_l7 = True
                tls_count = len([i for i in ingresses if i.tls_enabled])
                total_ingress = len(ingresses)

                evidence.append(f"L7 Ingress: {total_ingress} 个")

                if tls_count == total_ingress:
                    l7_security_level = 3
                    evidence.append("  ✓ 所有 Ingress 已启用 TLS (安全)")
                elif tls_count > 0:
                    l7_security_level = 2
                    evidence.append(f"  ⚠️ 仅 {tls_count}/{total_ingress} 个 Ingress 启用 TLS (存在明文风险)")
                else:
                    l7_security_level = 1
                    evidence.append("  ❌ 所有 Ingress 均未启用 TLS (高危)")

        # --- 3. ALB 分析 (作为 L7 能力的增强证据) ---
        alb_security_level = 0
        if store.available("alb.listener.list"):
            alb_listeners: list[AlbListenerRecord] = store.get("alb.listener.list")
            if alb_listeners:
                https_count = len([l for l in alb_listeners if l.listener_protocol in ("HTTPS", "QUIC", "TLS")])
                total_alb = len(alb_listeners)

                evidence.append(f"ALB 监听器: {total_alb} 个")

                if https_count == total_alb:
                    alb_security_level = 3
                    evidence.append("  ✓ ALB 全链路 HTTPS/QUIC 加密")
                elif https_count > 0:
                    alb_security_level = 2
                    evidence.append(f"  ⚠️ 仅 {https_count}/{total_alb} 个 ALB 监听器为 HTTPS")
                else:
                    alb_security_level = 1
                    evidence.append("  ❌ ALB 均为 HTTP 明文")

        # --- 4. GSLB 分析 ---
        gslb_healthy = False
        if store.available("gtm.address_pool.list"):
            gtm_pools: list[GtmAddressPoolRecord] = store.get("gtm.address_pool.list")
            if gtm_pools:
                has_gslb = True
                healthy_gtm = len([g for g in gtm_pools if g.monitor_status == 'OPEN'])

                if healthy_gtm == len(gtm_pools):
                    gslb_healthy = True
                    evidence.append(f"GSLB 全局流量管理: {len(gtm_pools)} 个地址池 (含健康检查)")
                else:
                    evidence.append(f"GSLB: {len(gtm_pools)} 个地址池 (部分缺失健康检查)")

        # --- 5. 平滑评分计算 ---
        if has_l4:
            current_score = 2

        if has_l7:
            l7_scores = {1: 2.5, 2: 3.5, 3: 5.0}
            current_score = max(current_score, l7_scores.get(l7_security_level, 2))

        if alb_security_level >= 2 and has_l7:
            current_score = max(current_score, min(5.0 + (alb_security_level - 1) * 0.8, 7.0))
        elif alb_security_level == 3 and not has_l7:
            current_score = max(current_score, 5.0)

        if has_gslb:
            if gslb_healthy:
                if current_score >= 5:
                    current_score = 8
                elif current_score >= 2:
                    current_score = min(current_score + 3, 7)
                else:
                    current_score = 5
            else:
                current_score = min(current_score + 1.5, 6.5)

        final_score = round(current_score)

        if has_gslb and gslb_healthy and current_score >= 7.5:
            conclusion = "具备全局智能负载均衡能力 (GSLB + 全链路加密)"
        elif has_gslb and current_score >= 5:
            conclusion = "具备全局流量管理能力，但底层负载均衡能力有待加强"
        elif current_score >= 5:
            conclusion = "具备高级 L7 负载均衡能力"
            if l7_security_level < 3 or alb_security_level < 3:
                conclusion += " (建议完善全链路加密)"
        elif current_score >= 3:
            conclusion = "具备基础负载均衡能力"
            if has_l7 and l7_security_level < 3:
                conclusion += " (存在 TLS 配置隐患)"
        elif has_l4:
            conclusion = "仅具备基础 L4 负载均衡 (LoadBalancer/NodePort)"
        else:
            conclusion = "仅具备内部服务发现能力 (ClusterIP)"

        evidence.append(f"综合评分: {current_score:.1f} → {final_score}分")

        return self._scored(final_score, conclusion, evidence)


class LbAlgorithmsAnalyzer(Analyzer):
    """
    负载均衡算法分析器
    
    评估标准（累计评分）：
    - 仅轮询: 2分
    - 支持加权/最少连接: +2分
    - 支持一致性哈希/基于内容路由: +2分
    
    数据来源：
    - ACK API：Service 或 Ingress 的 annotations 字段
    - ALB API：监听器配置，检查调度算法
    - Istio DestinationRule：负载均衡配置
    """

    def key(self) -> str:
        return "lb_algorithms"

    def dimension(self) -> str:
        return "Elasticity"

    def category(self) -> str:
        return "负载分发能力"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return []

    def optional_data(self) -> list[str]:
        return ["k8s.istio.destination_rule.list", "alb.listener.list", "k8s.service.list"]

    def analyze(self, store) -> ScoreResult:
        evidence = []
        algorithms_found = set()
        has_traffic_policy = False

        # 算法等级：0=无配置, 1=轮询, 2=加权/随机, 3=高级(最少连接/哈希)
        algo_level = 0
        total_dr = 0
        dr_with_policy = 0
        dr_with_advanced_lb = 0
        dr_with_outlier = 0

        # --- 1. 检查 Istio DestinationRule ---
        if store.available("k8s.istio.destination_rule.list"):
            rules: list[IstioDestinationRuleRecord] = store.get("k8s.istio.destination_rule.list")
            total_dr = len(rules)

            for rule in rules:
                if not rule.traffic_policy:
                    continue

                dr_with_policy += 1
                has_traffic_policy = True
                tp = rule.traffic_policy

                # 检查熔断配置 (outlierDetection) - 体现流量治理能力
                if tp.get("outlierDetection"):
                    dr_with_outlier += 1

                lb_config = tp.get("loadBalancer", {})

                if "simple" in lb_config:
                    simple_algo = lb_config["simple"].upper()
                    algorithms_found.add(simple_algo)

                    if simple_algo in ("LEAST_CONN", "LEAST_REQUEST"):
                        algo_level = max(algo_level, 3)
                        dr_with_advanced_lb += 1
                    elif simple_algo == "RANDOM":
                        algo_level = max(algo_level, 2)
                    elif simple_algo == "ROUND_ROBIN":
                        algo_level = max(algo_level, 1)

                if lb_config.get("consistentHash"):
                    hash_type = "CONSISTENT_HASH"
                    if "ringHash" in lb_config["consistentHash"]:
                        hash_type = "RING_HASH"
                    elif "maglev" in lb_config["consistentHash"]:
                        hash_type = "MAGLEV"

                    algorithms_found.add(hash_type)
                    algo_level = max(algo_level, 3)
                    dr_with_advanced_lb += 1

            if total_dr > 0:
                evidence.append(
                    f"Istio DestinationRule: {total_dr} 个 "
                    f"(配置流量策略: {dr_with_policy}, 高级算法: {dr_with_advanced_lb}, 熔断: {dr_with_outlier})"
                )

        # --- 2. 检查 ALB 监听器配置 ---
        # 注意：ALB 的调度算法在 ServerGroup 上配置，Listener 只包含协议信息
        # 从 Listener 可以推断：HTTPS/QUIC 支持 SNI/高级路由，HTTP 为基础能力
        alb_https_count = 0
        alb_http_count = 0

        if store.available("alb.listener.list"):
            listeners: list[AlbListenerRecord] = store.get("alb.listener.list")
            if listeners:
                alb_total = len(listeners)

                for listener in listeners:
                    protocol = listener.listener_protocol
                    if protocol in ('HTTPS', 'TLS'):
                        alb_https_count += 1
                    elif protocol == 'HTTP':
                        alb_http_count += 1

                if alb_https_count > 0:
                    evidence.append(
                        f"ALB 监听器: {alb_total} 个 (HTTPS/TLS: {alb_https_count}, HTTP: {alb_http_count})"
                    )
                    algo_level = max(algo_level, 2)
                else:
                    evidence.append(f"ALB 监听器: {alb_total} 个 (均为 HTTP)")

        base_scores = {0: 0, 1: 2, 2: 3, 3: 4}
        current_score = base_scores.get(algo_level, 0)

        total_resources = total_dr
        advanced_resources = dr_with_advanced_lb

        if total_resources > 0 and algo_level >= 2:
            coverage_ratio = advanced_resources / total_resources
            coverage_bonus = min(coverage_ratio * 2, 2)
            current_score += coverage_bonus

        if dr_with_outlier > 0:
            current_score += 0.5
            evidence.append(f"✓ 配置了熔断机制 (outlierDetection): {dr_with_outlier} 个")

        final_score = min(round(current_score), 6)

        if algorithms_found:
            evidence.insert(0, f"检测到的调度策略: {', '.join(sorted(algorithms_found))}")
        else:
            evidence.insert(0, "未识别到明确的负载均衡算法配置")

        evidence.append(f"综合评分: {current_score:.1f} → {final_score}分")

        if final_score >= 5:
            conclusion = "负载均衡算法配置完善，覆盖高级策略且具备熔断等流量治理能力"
        elif final_score >= 4:
            conclusion = "已配置高级负载均衡策略 (最少连接/一致性哈希)，能有效处理复杂流量场景"
        elif final_score >= 3:
            if dr_with_outlier > 0:
                conclusion = "配置了基础算法优化 + 熔断机制，具备较好的流量治理能力"
            else:
                conclusion = "配置了基础算法优化 (加权/随机)，优于默认轮询"
        elif final_score >= 2:
            conclusion = "仅使用默认轮询算法，建议根据业务场景配置更合适的调度策略"
        else:
            if has_traffic_policy:
                conclusion = "配置了流量策略但未明确负载均衡算法，建议检查配置完整性"
            else:
                conclusion = "未配置负载均衡算法，使用默认轮询策略"

        return self._scored(final_score, conclusion, evidence)


class TrafficMgmtAnalyzer(Analyzer):
    """
    流量治理分析器
    
    评估标准：流量治理策略覆盖度，每项约 2 分，最高 12 分
    检查项：流量分流、金丝雀、蓝绿、A/B测试、熔断、故障注入/混沌工程
    
    数据来源：
    - ASM API：检查是否存在 VirtualService（流量分割/金丝雀）、DestinationRule（熔断）
    - UModel：k8s.metric.asm，Istio 运行时流量指标
    """

    def key(self) -> str:
        return "traffic_mgmt"

    def dimension(self) -> str:
        return "Elasticity"

    def category(self) -> str:
        return "负载分发能力"

    def max_score(self) -> int:
        return 12

    def required_data(self) -> list[str]:
        return []

    def optional_data(self) -> list[str]:
        return ["k8s.istio.virtual_service.list", "k8s.istio.destination_rule.list"]

    def analyze(self, store) -> ScoreResult:
        has_vs = store.available("k8s.istio.virtual_service.list")
        has_dr = store.available("k8s.istio.destination_rule.list")

        if not has_vs and not has_dr:
            return self._not_scored("未配置 Istio 流量治理", ["未检测到 VirtualService/DestinationRule"])

        vs_list: list[IstioVirtualServiceRecord] = store.get("k8s.istio.virtual_service.list") if has_vs else []
        dr_list: list[IstioDestinationRuleRecord] = store.get("k8s.istio.destination_rule.list") if has_dr else []

        if not vs_list and not dr_list:
            return self._not_scored("Istio 资源列表为空", [])

        evidence_detail = []
        score = 0.0

        # --- 1. 检查 DestinationRule (熔断 + 连接池) ---
        cb_configs = []
        pool_configs = []

        for dr in dr_list:
            policy = dr.traffic_policy or {}

            outlier = policy.get("outlierDetection", {})
            if outlier:
                has_base = outlier.get("consecutive5xxErrors") or outlier.get("consecutiveErrors")
                has_interval = "interval" in outlier
                has_ejection = "baseEjectionTime" in outlier

                cb_quality = sum([has_base, has_interval, has_ejection])
                cb_configs.append({
                    "name": dr.name,
                    "quality": cb_quality,
                    "has_connection_pool": bool(policy.get("connectionPool"))
                })

            if policy.get("connectionPool"):
                pool_configs.append(dr.name)

        if cb_configs:
            avg_quality = sum(c["quality"] for c in cb_configs) / len(cb_configs)
            has_pool_ratio = sum(1 for c in cb_configs if c["has_connection_pool"]) / len(cb_configs)

            cb_score = 1 + avg_quality
            cb_score += has_pool_ratio

            score += min(cb_score, 4)
            evidence_detail.append(f"熔断配置: {len(cb_configs)} 个DR (平均完整度: {avg_quality:.1f}/3)")
            if has_pool_ratio > 0:
                evidence_detail.append(f"  ✓ 含连接池限制: {int(has_pool_ratio * 100)}%")

        # --- 2. 检查 VirtualService (重试、超时、分流、镜像、故障注入) ---
        retry_configs = []
        timeout_configs = []
        canary_configs = []
        mirror_configs = []
        fault_configs = []

        for vs in vs_list:
            routes = vs.http_routes

            for route_data in routes:
                retries = route_data.get("retries", {})
                if retries:
                    attempts = retries.get("attempts", 0)
                    per_try_timeout = retries.get("perTryTimeout")
                    retry_on = retries.get("retryOn", "")

                    safety_score = 0
                    if 0 < attempts <= 5:
                        safety_score += 1
                    if per_try_timeout:
                        safety_score += 1
                    if retry_on:
                        safety_score += 1

                    retry_configs.append({
                        "attempts": attempts,
                        "has_timeout": bool(per_try_timeout),
                        "safety_score": safety_score
                    })

                if route_data.get("timeout"):
                    timeout_configs.append(vs.name)

                destinations = route_data.get("route", [])
                if isinstance(destinations, list) and len(destinations) > 1:
                    weights = [d.get("weight", 0) for d in destinations if isinstance(d, dict)]
                    has_weights = any(w > 0 for w in weights)

                    match_conditions = route_data.get("match", [])
                    has_header_match = any("headers" in m for m in match_conditions if isinstance(m, dict))

                    canary_configs.append({
                        "has_weights": has_weights,
                        "has_header_match": has_header_match,
                        "dest_count": len(destinations)
                    })

                if route_data.get("mirror"):
                    mirror_configs.append(vs.name)

                fault = route_data.get("fault", {})
                if fault and (fault.get("delay") or fault.get("abort")):
                    fault_configs.append(vs.name)

        if retry_configs:
            avg_safety = sum(r["safety_score"] for r in retry_configs) / len(retry_configs)
            retry_score = avg_safety
            score += retry_score

            safe_count = sum(1 for r in retry_configs if r["safety_score"] >= 3)
            evidence_detail.append(
                f"重试策略: {len(retry_configs)} 个 "
                f"(安全配置: {safe_count}, 平均安全分: {avg_safety:.1f}/3)"
            )

        if timeout_configs:
            score += 1.5
            evidence_detail.append(f"超时控制: {len(timeout_configs)} 个VS")

        if canary_configs:
            weighted_count = sum(1 for c in canary_configs if c["has_weights"])
            header_based_count = sum(1 for c in canary_configs if c["has_header_match"])

            canary_score = 1 + (0.5 if weighted_count > 0 else 0) + (0.5 if header_based_count > 0 else 0)
            score += min(canary_score, 2)

            canary_type = []
            if weighted_count > 0:
                canary_type.append("加权")
            if header_based_count > 0:
                canary_type.append("Header匹配")
            evidence_detail.append(
                f"流量分流: {len(canary_configs)} 个 "
                f"({', '.join(canary_type) if canary_type else '简单多版本'})"
            )

        if mirror_configs:
            score += 1.5
            evidence_detail.append(f"流量镜像: {len(mirror_configs)} 个VS")

        if fault_configs:
            score += 1
            evidence_detail.append(f"故障注入: {len(fault_configs)} 个VS (混沌工程能力)")

        # --- 3. 综合评分与封顶 ---
        final_score = min(round(score), 12)

        # --- 4. 构建证据和结论 ---
        evidence = [
                       f"VirtualService: {len(vs_list)} 个",
                       f"DestinationRule: {len(dr_list)} 个",
                   ] + evidence_detail

        has_cb = len(cb_configs) > 0
        has_safe_retry = len(retry_configs) > 0 and avg_safety >= 2 if retry_configs else False

        if final_score >= 9:
            if has_cb and has_safe_retry:
                conclusion = "流量治理能力完善 (熔断、安全重试、超时控制及高级调度齐全)"
            else:
                conclusion = "流量配置丰富，建议补充核心容错机制以提升韧性"
        elif final_score >= 6:
            if has_cb or has_safe_retry:
                conclusion = "具备核心高可用治理能力 (熔断/安全重试)"
            else:
                conclusion = "具备流量调度能力，但缺乏核心容错机制"
        elif final_score >= 3:
            conclusion = "具备基础流量治理能力 (超时/简单分流)"
        elif final_score > 0:
            conclusion = "具备初步流量治理能力，建议完善配置"
        else:
            return self._not_scored("Istio 资源配置不完整，未形成有效治理能力", evidence)

        evidence.append(f"综合评分: {score:.1f} → {final_score}分")

        return self._scored(final_score, conclusion, evidence)


LB_ANALYZERS = [
    LbCapabilityAnalyzer(),
    LbAlgorithmsAnalyzer(),
    TrafficMgmtAnalyzer(),
]
