"""
Service Architecture 维度 - 服务通信与韧性分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)             | 分值 | 评分标准                                                   |
| ------------------------ | ---- | ---------------------------------------------------------- |
| comm_pattern_diversity   | 0-6  | 通信模式多样性：混合模式(6)/主要同步(3)/单一混乱(1)/无(0)  |
| svc_discovery_dynamic    | 7    | 动态服务发现：自动注册/注销到注册中心，无需硬编码 IP       |
| comm_load_balancing      | 6    | 客户端/服务端负载均衡：智能负载均衡策略                    |
| comm_circuit_breaker     | 8    | 熔断与降级：配置熔断器防止级联雪崩                         |
| comm_retry_safety        | 5    | 安全重试机制：指数退避+抖动，仅幂等操作触发                |
| comm_service_mesh        | 3    | 服务网格(可选高阶)：引入 Service Mesh 下沉通信逻辑         |
"""
from ...core.analyzer import Analyzer, ScoreResult
from ...schema.k8s import K8sServiceRecord, IstioVirtualServiceRecord, IstioDestinationRuleRecord
from ...schema.apm import ApmTopologyMetricsRecord, ApmExternalMessageRecord


class CommPatternDiversity(Analyzer):
    """
    通信模式多样性分析器
    
    评估标准：
    - 混合模式 (6): 同步 (REST/gRPC) 与异步 (MQ/Event) 结合得当，核心链路异步化
    - 主要同步 (3): 大部分为同步调用
    - 单一/混乱 (1): 仅有一种模式或混用不当
    - 无 (0): 无
    
    数据来源：
    - APM Topology：分析调用类型分布（HTTP/RPC vs MQ）
    - APM External Message：MQ 类型的外部调用，统计异步调用比例
    """
    
    def key(self) -> str:
        return "comm_pattern_diversity"
    
    def dimension(self) -> str:
        return "Service Architecture"
    
    def category(self) -> str:
        return "服务通信与韧性"
    
    def max_score(self) -> int:
        return 6
    
    def required_data(self) -> list[str]:
        return ["apm.topology.metrics"]
    
    def optional_data(self) -> list[str]:
        return ["apm.external.message"]
    
    def analyze(self, store) -> ScoreResult:
        topology: list[ApmTopologyMetricsRecord] = store.get("apm.topology.metrics")
        
        if not topology:
            return self._not_evaluated("未获取到服务拓扑数据")
        
        # 统计调用类型
        sync_calls = 0  # HTTP/gRPC/Dubbo
        async_calls = 0  # MQ
        total_calls = 0
        
        for m in topology:
            call_type = m.call_type.upper() if m.call_type else ""
            count = m.call_count or 1
            total_calls += count
            
            if any(t in call_type for t in ["HTTP", "GRPC", "DUBBO", "RPC"]):
                sync_calls += count
            elif any(t in call_type for t in ["MQ", "KAFKA", "ROCKET", "RABBIT"]):
                async_calls += count
        
        # 从 external.message 获取异步调用数据
        if store.available("apm.external.message"):
            messages: list[ApmExternalMessageRecord] = store.get("apm.external.message")
            for msg in messages:
                async_calls += msg.call_count
                total_calls += msg.call_count
        
        evidence = [
            f"总调用数: {total_calls}",
            f"同步调用: {sync_calls}",
            f"异步调用: {async_calls}"
        ]
        
        if total_calls == 0:
            return self._not_scored("无调用数据", evidence)
        
        async_ratio = async_calls / total_calls if total_calls > 0 else 0
        evidence.append(f"异步调用占比: {async_ratio:.1%}")
        
        # 评分逻辑
        if sync_calls > 0 and async_calls > 0 and async_ratio >= 0.2:
            # 混合模式：同步+异步，异步占比>=20%
            return self._scored(6, "混合模式：同步与异步结合得当", evidence)
        elif sync_calls > 0 and async_calls > 0:
            # 有异步但占比较低
            return self._scored(4, "有异步调用但占比较低", evidence)
        elif sync_calls > 0:
            # 主要同步
            return self._scored(3, "主要同步：大部分为同步调用", evidence)
        elif async_calls > 0:
            # 仅异步
            return self._scored(2, "单一模式：仅有异步调用", evidence)
        else:
            return self._not_scored("未检测到明确的通信模式", evidence)


class SvcDiscoveryDynamic(Analyzer):
    """
    动态服务发现分析器
    
    评估标准：服务实例上下线是否自动注册/注销到注册中心 (如 K8s DNS, Consul, Nacos)，调用方无需硬编码 IP。
    
    数据来源：
    - K8s Service：K8s Service 列表的存在性说明使用了 K8s DNS 服务发现
    - 辅助验证：检查 APM 数据中服务调用的目标地址是否为服务名而非硬编码 IP
    """
    
    def key(self) -> str:
        return "svc_discovery_dynamic"
    
    def dimension(self) -> str:
        return "Service Architecture"
    
    def category(self) -> str:
        return "服务通信与韧性"
    
    def max_score(self) -> int:
        return 7
    
    def required_data(self) -> list[str]:
        return ["k8s.service.list"]

    def analyze(self, store) -> ScoreResult:
        services: list[K8sServiceRecord] = store.get("k8s.service.list")

        if not services:
            return self._not_scored("未配置 K8s Service", [])

        evidence = [f"K8s Service 总数: {len(services)}"]

        # 分类统计
        cluster_ip_services = [s for s in services if s.type == "ClusterIP" and s.cluster_ip != "None"]
        headless_services = [s for s in services if s.cluster_ip == "None"]
        external_services = [s for s in services if s.type in ("LoadBalancer", "NodePort")]

        services_with_selector = [s for s in services if s.selector]
        services_without_selector = [s for s in services if not s.selector]

        # 构建详细证据
        if cluster_ip_services:
            evidence.append(f"标准 ClusterIP 服务 (内部 VIP): {len(cluster_ip_services)} 个")
        if headless_services:
            evidence.append(f"Headless 服务 (StatefulSet/Direct Pod IP): {len(headless_services)} 个")
        if external_services:
            evidence.append(f"外部暴露服务 (LB/NodePort): {len(external_services)} 个")

        if services_without_selector:
            evidence.append(f"⚠️ 无 Selector 服务 (需手动管理 Endpoints): {len(services_without_selector)} 个")
        else:
            evidence.append("✅ 所有服务均配置了 Selector，启用自动服务发现")

        if services_with_selector and len(services_with_selector) == len(services):
            return self._scored(
                7,
                "动态服务发现完备（K8s DNS），无硬编码 IP，架构规范",
                evidence
            )
        elif services_with_selector:
            ratio = len(services_with_selector) / len(services)
            msg = f"混合模式：{int(ratio * 100)}% 的服务使用自动发现，部分服务需手动维护 Endpoints"
            return self._scored(5, msg, evidence)
        else:
            return self._scored(3, "已创建 Service 但未配置 Selector，未利用自动服务发现机制", evidence)

class CommLoadBalancing(Analyzer):
    """
    客户端/服务端负载均衡分析器
    
    评估标准：是否在网关或服务网格层面实现了智能负载均衡 (如加权轮询、最小连接数、就近访问)。
    
    数据来源：
    - K8s Ingress：负载均衡流量指标
    - ASM DestinationRule：trafficPolicy.loadBalancer 配置
    """
    
    def key(self) -> str:
        return "comm_load_balancing"
    
    def dimension(self) -> str:
        return "Service Architecture"
    
    def category(self) -> str:
        return "服务通信与韧性"
    
    def max_score(self) -> int:
        return 6
    
    def required_data(self) -> list[str]:
        return ["k8s.service.list"]
    
    def optional_data(self) -> list[str]:
        return ["k8s.istio.destination_rule.list", "k8s.ingress.list"]
    
    def analyze(self, store) -> ScoreResult:
        services: list[K8sServiceRecord] = store.get("k8s.service.list")
        
        if not services:
            return self._not_evaluated("未配置 K8s Service")
        
        evidence = [f"K8s Service 数量: {len(services)}"]
        score = 2  # 基础分：有 K8s 默认的负载均衡
        
        # 检查 Istio DestinationRule 的负载均衡配置
        if store.available("k8s.istio.destination_rule.list"):
            rules: list[IstioDestinationRuleRecord] = store.get("k8s.istio.destination_rule.list")
            
            lb_configured = []
            for rule in rules:
                if rule.traffic_policy:
                    lb = rule.traffic_policy.get("loadBalancer", {})
                    if lb:
                        lb_configured.append(rule)
            
            if lb_configured:
                evidence.append(f"Istio 负载均衡配置: {len(lb_configured)} 个")
                score += 3
        
        # 检查 Ingress 配置
        if store.available("k8s.ingress.list"):
            from ...schema.k8s import K8sIngressRecord
            ingresses: list[K8sIngressRecord] = store.get("k8s.ingress.list")
            
            # 检查 annotations 中的负载均衡配置
            lb_annotations = ["nginx.ingress.kubernetes.io/upstream-hash-by",
                            "nginx.ingress.kubernetes.io/load-balance"]
            
            lb_ingresses = [i for i in ingresses 
                          if any(ann in i.annotations for ann in lb_annotations)]
            
            if lb_ingresses:
                evidence.append(f"Ingress 负载均衡配置: {len(lb_ingresses)} 个")
                score += 1
        
        score = min(score, 6)
        
        if score >= 5:
            return self._scored(6, "智能负载均衡配置完善", evidence)
        elif score >= 3:
            return self._scored(score, "有负载均衡配置", evidence)
        else:
            return self._scored(score, "使用默认负载均衡", evidence)


class CommCircuitBreaker(Analyzer):
    """
    熔断与降级分析器
    
    评估标准：服务间调用是否配置了熔断器，在依赖方故障时快速失败或返回默认值，防止级联雪崩。
    
    数据来源：
    - ASM DestinationRule：outlierDetection 字段，检查熔断配置
    - APM Metrics：Istio 运行时指标，可观察熔断事件是否发生过
    """
    
    def key(self) -> str:
        return "comm_circuit_breaker"
    
    def dimension(self) -> str:
        return "Service Architecture"
    
    def category(self) -> str:
        return "服务通信与韧性"
    
    def max_score(self) -> int:
        return 8
    
    def required_data(self) -> list[str]:
        return ["k8s.istio.destination_rule.list"]
    
    def analyze(self, store) -> ScoreResult:
        rules: list[IstioDestinationRuleRecord] = store.get("k8s.istio.destination_rule.list")
        
        if not rules:
            return self._not_scored("未配置 Istio DestinationRule", [])
        
        evidence = [f"DestinationRule 总数: {len(rules)}"]
        
        # 检查 outlierDetection（熔断配置）
        circuit_breaker_rules = []
        for rule in rules:
            if rule.traffic_policy:
                outlier = rule.traffic_policy.get("outlierDetection", {})
                if outlier:
                    circuit_breaker_rules.append(rule)
        
        if not circuit_breaker_rules:
            return self._not_scored("未配置熔断策略", evidence)
        
        evidence.append(f"配置熔断: {len(circuit_breaker_rules)} 个")
        ratio = len(circuit_breaker_rules) / len(rules)
        evidence.append(f"熔断覆盖率: {ratio:.1%}")
        
        # 评分逻辑
        if ratio >= 0.8:
            return self._scored(8, "熔断配置完善，防止级联雪崩", evidence)
        elif ratio >= 0.5:
            return self._scored(6, "大部分服务配置熔断", evidence)
        elif ratio >= 0.2:
            return self._scored(4, "部分服务配置熔断", evidence)
        else:
            return self._scored(2, "少量服务配置熔断", evidence)


class CommRetrySafety(Analyzer):
    """
    安全重试机制分析器
    
    评估标准：重试策略是否包含指数退避 (Backoff) 和抖动 (Jitter)，且仅在幂等操作或特定错误码下触发。
    
    数据来源：
    - ASM VirtualService：retries 字段，检查 retryOn（重试条件）、attempts（次数）、perTryTimeout（单次超时）配置
    """
    
    def key(self) -> str:
        return "comm_retry_safety"
    
    def dimension(self) -> str:
        return "Service Architecture"
    
    def category(self) -> str:
        return "服务通信与韧性"
    
    def max_score(self) -> int:
        return 5
    
    def required_data(self) -> list[str]:
        return ["k8s.istio.virtual_service.list"]

    def analyze(self, store) -> ScoreResult:
        vs_list: list[IstioVirtualServiceRecord] = store.get("k8s.istio.virtual_service.list")

        if not vs_list:
            return self._not_scored("未配置 Istio VirtualService", [])

        evidence = [f"VirtualService 总数: {len(vs_list)}"]

        retry_configured = []
        safe_retry_configured = []
        unsafe_vs_names = []  # 用于记录不安全的 VS 名称，方便排查

        for vs in vs_list:
            vs_has_retry = False
            vs_is_safe = False

            # 修复点 1: 遍历所有路由，而不是遇到第一个就 break
            for route in vs.http_routes:
                retries = route.get("retries", {})
                if not retries:
                    continue

                vs_has_retry = True

                # 检查是否有超时控制 (通常意味着有退避机制)
                # 修复点 2: 移除脆弱的 str(retries) 检查，仅依赖标准字段
                has_backoff = "perTryTimeout" in retries

                # 检查 retryOn 条件
                retry_on = retries.get("retryOn", "")

                # 修复点 3: 处理默认情况。如果未指定 retryOn，Istio 默认重试 5xx 和 connect-failure，视为安全
                if not retry_on:
                    is_safe_condition = True
                else:
                    safe_conditions = ["5xx", "connect-failure", "retriable", "gateway-error"]
                    is_safe_condition = any(c in retry_on for c in safe_conditions)

                if has_backoff or is_safe_condition:
                    vs_is_safe = True
                if not (has_backoff or is_safe_condition):
                    vs_is_safe = False
                    break
            has_any_retry = False
            all_retry_routes_safe = True

            for route in vs.http_routes:
                retries = route.get("retries", {})
                if not retries:
                    continue

                has_any_retry = True

                has_backoff = "perTryTimeout" in retries
                retry_on = retries.get("retryOn", "")

                if not retry_on:
                    is_safe_condition = True  # 默认安全
                else:
                    safe_conditions = ["5xx", "connect-failure", "retriable", "gateway-error"]
                    is_safe_condition = any(c in retry_on for c in safe_conditions)

                if not (has_backoff or is_safe_condition):
                    all_retry_routes_safe = False
                    break  # 发现一个不安全的配置，该 VS 判定为不安全

            if has_any_retry:
                retry_configured.append(vs)
                if all_retry_routes_safe:
                    safe_retry_configured.append(vs)
                else:
                    unsafe_vs_names.append(vs.name)  # 记录名称

        if not retry_configured:
            return self._not_scored("未配置重试策略", evidence)

        evidence.append(f"配置重试: {len(retry_configured)} 个")
        evidence.append(f"安全重试配置: {len(safe_retry_configured)} 个")

        if unsafe_vs_names:
            evidence.append(
                f"存在不安全配置的服务: {', '.join(unsafe_vs_names[:5])}{'...' if len(unsafe_vs_names) > 5 else ''}")

        # 评分逻辑
        total_retry_count = len(retry_configured)
        safe_count = len(safe_retry_configured)

        if total_retry_count == 0:
            # 理论上前面已经返回了，这里做防御性编程
            return self._not_scored("未配置安全重试机制", evidence)

        if safe_count >= total_retry_count * 0.8:
            return self._scored(5, "安全重试机制完善（指数退避+条件触发）", evidence)
        elif safe_count > 0:
            return self._scored(3, "有重试配置，部分包含安全策略", evidence)
        else:
            return self._scored(2, "有重试配置，但缺少安全策略", evidence)

class CommServiceMesh(Analyzer):
    """
    服务网格分析器（可选高阶）
    
    评估标准：是否引入 Service Mesh (如 Istio/Linkerd) 将通信逻辑下沉到基础设施层。
    
    数据来源：
    - ACK：检查集群中是否有 Envoy Sidecar 注入（istio-proxy 容器的存在）
    - ASM：检查是否有 Istio 控制平面运行
    """
    
    def key(self) -> str:
        return "comm_service_mesh"
    
    def dimension(self) -> str:
        return "Service Architecture"
    
    def category(self) -> str:
        return "服务通信与韧性"
    
    def max_score(self) -> int:
        return 3
    
    def required_data(self) -> list[str]:
        return ["k8s.service.list"]
    
    def optional_data(self) -> list[str]:
        return ["k8s.istio.virtual_service.list", "k8s.istio.destination_rule.list"]

    def analyze(self, store) -> ScoreResult:
        services = store.get("k8s.service.list", [])
        if not isinstance(services, list):
            services = []

        evidence = [f"K8s Service 数量: {len(services)}"]
        has_mesh = False

        vs_list = store.get("k8s.istio.virtual_service.list", [])
        if vs_list:
            has_mesh = True
            evidence.append(f"VirtualService: {len(vs_list)} 个")

        dr_list = store.get("k8s.istio.destination_rule.list", [])
        if dr_list:
            has_mesh = True
            evidence.append(f"DestinationRule: {len(dr_list)} 个")

        istio_services_count = 0
        for s in services:
            selector = getattr(s, 'selector', None)
            if not isinstance(selector, dict):
                continue

            match_found = False
            for k, v in selector.items():
                k_lower = k.lower()
                v_lower = str(v).lower()
                if k_lower == "istio-injection" or k_lower == "sidecar.istio.io/inject":
                    match_found = True
                    break
                elif ("istio" in k_lower or "sidecar" in k_lower) and len(k_lower) < 20:
                    match_found = True
                    break

            if match_found:
                istio_services_count += 1

        if istio_services_count > 0:
            has_mesh = True
            evidence.append(f"检测到含 Istio 特征标签的服务: {istio_services_count} 个")

        if has_mesh:
            return self._scored(3, "检测到 Service Mesh (Istio) 配置", evidence)
        else:
            return self._not_scored("未检测到明显的 Service Mesh (Istio) 配置", evidence)

# 导出所有分析器
COMM_ANALYZERS = [
    CommPatternDiversity(),
    SvcDiscoveryDynamic(),
    CommLoadBalancing(),
    CommCircuitBreaker(),
    CommRetrySafety(),
    CommServiceMesh(),
]
