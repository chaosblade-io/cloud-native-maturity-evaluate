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
from ...schema import IstioGatewayRecord
from ...schema.k8s import K8sServiceRecord, IstioVirtualServiceRecord, IstioDestinationRuleRecord, K8sIngressRecord
from ...schema.apm import ApmTopologyMetricsRecord, ApmExternalMessageRecord
from ...schema.codeup import CodeupRepoFileTreeRecord
import re


class CommPatternDiversityAnalyzer(Analyzer):
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

    评分细则（满分 6 分）：
    - 基础通信能力：有同步调用 (+1)
    - 异步化程度：异步占比 >=20% (+2)
    - 异步质量：使用持久化消息队列 (+1)
    - 场景合理性：核心链路异步化（长链路/削峰场景）(+2)
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

        evidence = []
        raw_score = 0

        # ========== 1. 详细统计调用类型 ==========
        http_calls = 0
        grpc_calls = 0
        rpc_calls = 0

        kafka_calls = 0
        rocketmq_calls = 0
        rabbitmq_calls = 0
        other_mq_calls = 0

        total_calls = 0

        for m in topology:
            call_type = m.call_type.upper() if m.call_type else ""
            count = m.call_count or 1
            total_calls += count

            if "HTTP" in call_type or "REST" in call_type:
                http_calls += count
            elif "GRPC" in call_type:
                grpc_calls += count
            elif any(t in call_type for t in ["DUBBO", "RPC", "THRIFT"]):
                rpc_calls += count
            elif "KAFKA" in call_type:
                kafka_calls += count
            elif "ROCKET" in call_type:
                rocketmq_calls += count
            elif "RABBIT" in call_type:
                rabbitmq_calls += count
            elif any(t in call_type for t in ["MQ", "MESSAGE", "EVENT"]):
                other_mq_calls += count

        if store.available("apm.external.message"):
            messages: list[ApmExternalMessageRecord] = store.get("apm.external.message")
            for msg in messages:
                msg_count = msg.call_count or 0
                msg_type = (msg.mq_type or "").upper()
                if "KAFKA" in msg_type:
                    kafka_calls += msg_count
                elif "ROCKET" in msg_type:
                    rocketmq_calls += msg_count
                elif "RABBIT" in msg_type:
                    rabbitmq_calls += msg_count
                else:
                    other_mq_calls += msg_count
                total_calls += msg_count

        sync_calls = http_calls + grpc_calls + rpc_calls
        async_calls = kafka_calls + rocketmq_calls + rabbitmq_calls + other_mq_calls

        evidence.append(f"总调用数: {total_calls}")

        if total_calls == 0:
            return self._not_scored("无调用数据", evidence)

        # ========== 2. 基础通信能力评分 (+1分) ==========
        if sync_calls > 0:
            raw_score += 1
            sync_details = []
            if http_calls > 0:
                sync_details.append(f"HTTP/REST({http_calls})")
            if grpc_calls > 0:
                sync_details.append(f"gRPC({grpc_calls})")
            if rpc_calls > 0:
                sync_details.append(f"RPC({rpc_calls})")
            evidence.append(f"同步调用: {sync_calls} - {', '.join(sync_details)}")
        else:
            evidence.append("警告: 无同步调用")

        # ========== 3. 异步化程度评分 (+2分) ==========
        async_ratio = async_calls / total_calls if total_calls > 0 else 0
        evidence.append(f"异步调用占比: {async_ratio:.1%}")

        if async_calls > 0:
            async_details = []
            if kafka_calls > 0:
                async_details.append(f"Kafka({kafka_calls})")
            if rocketmq_calls > 0:
                async_details.append(f"RocketMQ({rocketmq_calls})")
            if rabbitmq_calls > 0:
                async_details.append(f"RabbitMQ({rabbitmq_calls})")
            if other_mq_calls > 0:
                async_details.append(f"其他MQ({other_mq_calls})")
            evidence.append(f"异步调用: {async_calls} - {', '.join(async_details)}")

            if async_ratio >= 0.3:
                raw_score += 2
                evidence.append("异步化程度: 优秀 (>=30%)")
            elif async_ratio >= 0.2:
                raw_score += 2
                evidence.append("异步化程度: 良好 (>=20%)")
            elif async_ratio >= 0.1:
                raw_score += 1
                evidence.append("异步化程度: 一般 (>=10%)")
            else:
                evidence.append("异步化程度: 较低 (<10%)")
        else:
            evidence.append("无异步调用")

        # ========== 4. 异步质量评分 (+1分) ==========
        persistent_mq_calls = kafka_calls + rocketmq_calls
        if persistent_mq_calls > 0 and async_calls > 0:
            persistent_ratio = persistent_mq_calls / async_calls
            if persistent_ratio >= 0.5:
                raw_score += 1
                evidence.append("异步质量: 使用持久化消息队列 (Kafka/RocketMQ)")
            else:
                evidence.append("异步质量: 部分使用非持久化队列，建议评估可靠性")
        elif async_calls > 0:
            evidence.append("异步质量: 未使用持久化消息队列，存在可靠性风险")

        # ========== 5. 场景合理性评分 (+2分) ==========
        if kafka_calls > 0 or rocketmq_calls > 0:
            if async_ratio >= 0.2:
                raw_score += 2
                evidence.append("场景合理性: 核心链路已异步化（削峰/解耦场景）")
            else:
                raw_score += 1
                evidence.append("场景合理性: 有异步基础设施，建议扩大异步化范围")
        elif async_calls > 0 and async_ratio >= 0.2:
            raw_score += 1
            evidence.append("场景合理性: 有异步调用，建议评估核心链路可靠性")
        else:
            evidence.append("场景合理性: 核心链路仍为同步调用")

        if raw_score >= 6:
            final_score = 6
            conclusion = "混合模式优秀：同步与异步结合得当，核心链路异步化"
        elif raw_score >= 5:
            final_score = 5
            conclusion = "混合模式良好：异步化程度较高，建议优化队列选型"
        elif raw_score >= 4:
            final_score = 4
            conclusion = "混合模式一般：有异步调用但质量或场景合理性待提升"
        elif raw_score >= 3:
            final_score = 3
            conclusion = "主要同步：建议对核心链路进行异步化改造"
        elif raw_score >= 2:
            final_score = 2
            conclusion = "同步为主：异步化程度较低"
        elif raw_score >= 1:
            final_score = 1
            conclusion = "单一模式：仅有同步调用"
        else:
            final_score = 0
            conclusion = "无有效通信数据"

        if sync_calls == 0 and async_calls > 0:
            if kafka_calls > 0 or rocketmq_calls > 0:
                final_score = max(final_score, 4)
                conclusion = "纯异步架构：基于持久化消息队列（适合 IoT/日志场景）"
            else:
                final_score = max(final_score, 3)
                conclusion = "纯异步架构：建议评估是否需要同步查询接口"

        return self._scored(final_score, conclusion, evidence)


class SvcDiscoveryDynamicAnalyzer(Analyzer):
    """
    动态服务发现分析器

    评估标准：服务实例上下线是否自动注册/注销到注册中心 (如 K8s DNS, Consul, Nacos)，调用方无需硬编码 IP。

    数据来源：
    - K8s Service：服务类型、Selector 配置、Endpoints 状态
    - APM Topology：验证调用目标是否为服务名而非硬编码 IP
    - 代码库：检测配置文件中的硬编码 IP

    评分细则（满分 7 分）：
    - 基础服务发现：使用 K8s DNS (+2)
    - 自动注册能力：Selector 配置完善 (+2)
    - 无硬编码 IP：APM/代码验证通过 (+2)
    - 高级特性：服务网格/多集群发现 (+1)
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

    def optional_data(self) -> list[str]:
        return ["apm.topology.metrics", "codeup.repo.file_tree"]

    def analyze(self, store) -> ScoreResult:
        services: list[K8sServiceRecord] = store.get("k8s.service.list")

        if not services:
            return self._not_scored("未配置 K8s Service", [])

        evidence = []
        raw_score = 0

        # ========== 1. 基础服务发现能力 (+2分) ==========
        cluster_ip_services = [s for s in services if s.type == "ClusterIP" and s.cluster_ip != "None"]
        headless_services = [s for s in services if s.cluster_ip == "None"]
        external_name_services = [s for s in services if s.type == "ExternalName"]
        external_services = [s for s in services if s.type in ("LoadBalancer", "NodePort")]

        evidence.append(f"K8s Service 总数: {len(services)}")

        if cluster_ip_services:
            evidence.append(f"标准 ClusterIP 服务: {len(cluster_ip_services)} 个")
            raw_score += 1

        if headless_services:
            evidence.append(f"Headless 服务: {len(headless_services)} 个 (StatefulSet/Direct Pod IP)")
            raw_score += 1

        if external_name_services:
            evidence.append(f"ExternalName 服务: {len(external_name_services)} 个 (外部服务映射)")

        if external_services:
            evidence.append(f"外部暴露服务: {len(external_services)} 个")

        # ========== 2. 自动注册能力 (+2分) ==========
        services_with_selector = [s for s in services if s.selector]
        services_without_selector = [s for s in services if not s.selector]

        non_external_services = [s for s in services if s.type != "ExternalName"]
        selector_coverage = len(services_with_selector) / len(non_external_services) if non_external_services else 0

        if selector_coverage >= 0.9:
            raw_score += 2
            evidence.append(f"自动注册: 优秀 ({selector_coverage:.0%} 服务配置 Selector)")
        elif selector_coverage >= 0.7:
            raw_score += 1
            evidence.append(f"自动注册: 良好 ({selector_coverage:.0%} 服务配置 Selector)")
        elif selector_coverage >= 0.5:
            raw_score += 1
            evidence.append(f"自动注册: 一般 ({selector_coverage:.0%} 服务配置 Selector)")
        else:
            evidence.append(f"自动注册: 较差 ({selector_coverage:.0%} 服务配置 Selector)")

        if services_without_selector:
            non_external_no_selector = [s for s in services_without_selector if s.type != "ExternalName"]
            if non_external_no_selector:
                evidence.append(f"⚠️ 无 Selector 服务: {len(non_external_no_selector)} 个 (需手动管理 Endpoints)")

        # ========== 3. 无硬编码 IP 验证 (+2分) ==========
        hardcoded_ip_found = False

        if store.available("apm.topology.metrics"):
            topology: list[ApmTopologyMetricsRecord] = store.get("apm.topology.metrics")

            ip_pattern = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b')
            hardcoded_targets = []

            for metric in topology:
                target = metric.target_service
                call = metric.call

                if ip_pattern.match(target) or ip_pattern.search(call):
                    hardcoded_targets.append(target or call)

            if hardcoded_targets:
                hardcoded_ip_found = True
                unique_ips = list(set(hardcoded_targets))[:3]
                evidence.append(f"⚠️ APM 检测到硬编码 IP 调用: {', '.join(unique_ips)}")
            else:
                evidence.append("✅ APM 验证：未发现硬编码 IP 调用")
                raw_score += 1
        else:
            evidence.append("未获取 APM 数据，无法验证硬编码 IP")

        if store.available("codeup.repo.file_tree"):
            file_tree = store.get("codeup.repo.file_tree")
            config_files_with_ip = []

            ip_pattern = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')

            for f in file_tree:
                if not f.name:
                    continue
                if any(f.name.endswith(ext) for ext in ['.yaml', '.yml', '.json', '.properties', '.conf']):
                    if ip_pattern.search(f.name):
                        config_files_with_ip.append(f.name)

            if config_files_with_ip:
                hardcoded_ip_found = True
                evidence.append(f"⚠️ 配置文件名包含 IP: {', '.join(config_files_with_ip[:2])}")
            elif not hardcoded_ip_found:
                evidence.append("✅ 代码库检查：未发现明显硬编码 IP 配置")
                raw_score += 1

        if hardcoded_ip_found:
            evidence.append("建议：将硬编码 IP 改为服务名，使用 K8s DNS 解析")

        # ========== 4. 高级服务发现特性 (+1分) ==========
        has_mesh_enhancement = False

        istio_services = []
        for s in services:
            selector = s.selector
            if isinstance(selector, dict):
                for k, v in selector.items():
                    if 'istio' in str(k).lower() or 'istio' in str(v).lower():
                        istio_services.append(s.name)
                        break

        if istio_services:
            has_mesh_enhancement = True
            evidence.append(f"服务网格增强: {len(istio_services)} 个服务有 Istio 标签")

        multi_cluster = any(
            'cluster' in (s.name or '').lower() or
            any('cluster' in ip.lower() for ip in (s.external_ips or []))
            for s in external_name_services
        )

        if multi_cluster:
            has_mesh_enhancement = True
            evidence.append("多集群发现: 检测到跨集群服务映射")

        if has_mesh_enhancement:
            raw_score += 1
        else:
            evidence.append("高级特性: 未检测到服务网格或多集群发现")

        if raw_score >= 7:
            final_score = 7
            conclusion = "动态服务发现完备：K8s DNS + 无硬编码 IP + 高级特性"
        elif raw_score >= 6:
            final_score = 6
            conclusion = "动态服务发现优秀：基础完善，建议增加高级特性"
        elif raw_score >= 5:
            final_score = 5
            conclusion = "动态服务发现良好：基本完备，建议优化硬编码 IP"
        elif raw_score >= 4:
            final_score = 4
            conclusion = "动态服务发现一般：有基础能力，建议完善 Selector 配置"
        elif raw_score >= 3:
            final_score = 3
            conclusion = "动态服务发现起步：基础配置存在，需优化"
        elif raw_score >= 2:
            final_score = 2
            conclusion = "动态服务发现有限：部分服务配置正确"
        elif raw_score >= 1:
            final_score = 1
            conclusion = "动态服务发现较差：需要全面改造"
        else:
            final_score = 0
            conclusion = "未建立动态服务发现机制"

        return self._scored(final_score, conclusion, evidence)


class CommLoadBalancingAnalyzer(Analyzer):
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

        evidence = []
        raw_score = 0

        # ========== 1. 基础负载均衡能力 (+2分) ==========
        evidence.append(f"K8s Service 数量: {len(services)}")

        if len(services) > 0:
            raw_score += 1
            evidence.append("基础能力: K8s 默认 Round-Robin 负载均衡")

        # ========== 2. 服务网格负载均衡 (+2分) ==========
        istio_lb_count = 0
        istio_advanced_lb = 0

        if store.available("k8s.istio.destination_rule.list"):
            rules: list[IstioDestinationRuleRecord] = store.get("k8s.istio.destination_rule.list")

            for rule in rules:
                if rule.traffic_policy:
                    lb = rule.traffic_policy.get("loadBalancer", {})
                    if lb:
                        istio_lb_count += 1
                        lb_type = lb.get("simple", '').upper()
                        if lb_type in ['LEAST_CONN', 'RANDOM', 'PASSTHROUGH']:
                            istio_advanced_lb += 1
                        if lb.get("consistentHash"):
                            istio_advanced_lb += 1

            if istio_lb_count > 0:
                evidence.append(f"Istio 负载均衡: {istio_lb_count} 个 DestinationRule")
                coverage = istio_lb_count / len(services) if services else 0
                if coverage >= 0.5:
                    raw_score += 2
                    evidence.append(f"服务网格覆盖率: 优秀 ({coverage:.0%})")
                elif coverage >= 0.2:
                    raw_score += 1
                    evidence.append(f"服务网格覆盖率: 一般 ({coverage:.0%})")
                else:
                    evidence.append(f"服务网格覆盖率: 较低 ({coverage:.0%})")

                if istio_advanced_lb > 0:
                    evidence.append(f"高级策略: {istio_advanced_lb} 个 (LeastConn/Random/ConsistentHash)")
            else:
                evidence.append("未配置 Istio 负载均衡")
        else:
            evidence.append("未获取 Istio DestinationRule 数据")

        # ========== 3. Ingress 负载均衡 (+1分) ==========
        ingress_lb_count = 0
        ingress_advanced = 0

        if store.available("k8s.ingress.list"):
            ingresses: list[K8sIngressRecord] = store.get("k8s.ingress.list")

            lb_annotations = [
                "nginx.ingress.kubernetes.io/upstream-hash-by",
                "nginx.ingress.kubernetes.io/load-balance",
                "nginx.ingress.kubernetes.io/affinity",
                "traefik.ingress.kubernetes.io/service.sticky.cookie",
                "traefik.ingress.kubernetes.io/router.loadbalancer.method",
                "alb.ingress.kubernetes.io/target-group-attributes",
                "alb.ingress.kubernetes.io/load-balancer-attributes",
                "ingress.kubernetes.io/affinity",
                "ingress.kubernetes.io/session-affinity"
            ]

            for ing in ingresses:
                has_lb_config = any(ann in (ing.annotations or {}) for ann in lb_annotations)
                if has_lb_config:
                    ingress_lb_count += 1
                    for ann_key, ann_val in (ing.annotations or {}).items():
                        if any(adv in str(ann_val).lower() for adv in ['least', 'hash', 'ip_hash', 'consistent']):
                            ingress_advanced += 1
                            break

            if ingress_lb_count > 0:
                raw_score += 1
                evidence.append(f"Ingress 负载均衡: {ingress_lb_count} 个配置")
                if ingress_advanced > 0:
                    evidence.append(f"Ingress 高级策略: {ingress_advanced} 个")
            else:
                evidence.append("未配置 Ingress 负载均衡（使用默认轮询）")
        else:
            evidence.append("未获取 Ingress 数据")

        # ========== 4. 健康检查与故障转移 (+1分) ==========
        health_check_count = 0

        if store.available("k8s.istio.destination_rule.list"):
            rules: list[IstioDestinationRuleRecord] = store.get("k8s.istio.destination_rule.list")
            for rule in rules:
                if rule.traffic_policy:
                    outlier = rule.traffic_policy.get("outlierDetection", {})
                    if outlier:
                        health_check_count += 1

        if health_check_count > 0:
            raw_score += 1
            evidence.append(f"健康检查: {health_check_count} 个服务配置故障检测")
        else:
            evidence.append("健康检查: 未配置主动健康检测")

        if raw_score >= 6:
            final_score = 6
            conclusion = "智能负载均衡配置完善：服务网格 + 高级策略 + 健康检查"
        elif raw_score >= 5:
            final_score = 5
            conclusion = "负载均衡配置良好：建议增加健康检查配置"
        elif raw_score >= 4:
            final_score = 4
            conclusion = "负载均衡配置较好：建议扩大服务网格覆盖"
        elif raw_score >= 3:
            final_score = 3
            conclusion = "负载均衡配置一般：有基础能力，建议优化策略"
        elif raw_score >= 2:
            final_score = 2
            conclusion = "基础负载均衡：使用 K8s 默认轮询"
        elif raw_score >= 1:
            final_score = 1
            conclusion = "负载均衡能力有限"
        else:
            final_score = 0
            conclusion = "未配置负载均衡"

        return self._scored(final_score, conclusion, evidence)


class CommCircuitBreakerAnalyzer(Analyzer):
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

        evidence = []
        raw_score = 0

        # ========== 1. 基础熔断配置检测 ==========
        if not rules:
            evidence.append("未配置 Istio DestinationRule")
            istio_coverage = 0
        else:
            evidence.append(f"DestinationRule 总数: {len(rules)}")

            circuit_breaker_rules = []
            well_configured_rules = []

            for rule in rules:
                if rule.traffic_policy:
                    outlier = rule.traffic_policy.get("outlierDetection", {})
                    if outlier:
                        circuit_breaker_rules.append(rule)

                        has_errors = outlier.get("consecutive5xxErrors")
                        has_interval = outlier.get("interval")
                        has_ejection_time = outlier.get("baseEjectionTime")
                        has_max_ejection = outlier.get("maxEjectionPercent")

                        if has_errors and has_interval and has_ejection_time and has_max_ejection:
                            well_configured_rules.append(rule)

            if circuit_breaker_rules:
                evidence.append(f"配置熔断: {len(circuit_breaker_rules)} 个")
                if well_configured_rules:
                    evidence.append(f"配置完整: {len(well_configured_rules)} 个 (含全部关键参数)")

                istio_coverage = len(circuit_breaker_rules) / len(rules)
                evidence.append(f"熔断覆盖率: {istio_coverage:.1%}")
            else:
                evidence.append("未配置熔断策略 (outlierDetection)")
                istio_coverage = 0

        # ========== 2. 熔断覆盖率评分 (+3分) ==========
        if istio_coverage >= 0.8:
            raw_score += 3
            evidence.append("服务网格熔断: 优秀 (>=80%)")
        elif istio_coverage >= 0.5:
            raw_score += 2
            evidence.append("服务网格熔断: 良好 (>=50%)")
        elif istio_coverage >= 0.2:
            raw_score += 1
            evidence.append("服务网格熔断: 一般 (>=20%)")
        elif istio_coverage > 0:
            raw_score += 1
            evidence.append("服务网格熔断: 起步 (<20%)")
        else:
            evidence.append("服务网格熔断: 未配置")

        # ========== 3. 客户端熔断检测 (+2分) ==========
        client_circuit_breaker_found = False
        client_frameworks = []

        if store.available("codeup.repo.file_tree"):
            file_tree: list[CodeupRepoFileTreeRecord] = store.get("codeup.repo.file_tree")

            cb_frameworks = {
                "hystrix": ["hystrix", "netflix"],
                "resilience4j": ["resilience4j", "circuitbreaker"],
                "sentinel": ["sentinel", "alibaba"],
                "spring-cloud-circuit": ["spring-cloud-starter-circuit"]
            }

            for f in file_tree:
                if not f.name:
                    continue
                name_lower = f.name.lower()

                if any(name_lower.endswith(ext) for ext in ['pom.xml', 'build.gradle', 'package.json']):
                    for framework, keywords in cb_frameworks.items():
                        if any(kw in name_lower for kw in keywords):
                            client_circuit_breaker_found = True
                            if framework not in client_frameworks:
                                client_frameworks.append(framework)

                if f.name.endswith(('.java', '.kt', '.py', '.go')):
                    if any(kw in name_lower for kw in ['hystrixcommand', 'circuitbreaker', 'sentinelresource']):
                        client_circuit_breaker_found = True

            if client_circuit_breaker_found:
                raw_score += 2
                evidence.append(
                    f"客户端熔断: 检测到 {', '.join(client_frameworks) if client_frameworks else '熔断框架'}")
            else:
                evidence.append("客户端熔断: 未检测到客户端熔断配置")
        else:
            evidence.append("客户端熔断: 未获取代码库数据")

        # ========== 4. 降级策略检测 (+2分) ==========
        if store.available("k8s.istio.virtual_service.list"):
            vs_list: list[IstioVirtualServiceRecord] = store.get("k8s.istio.virtual_service.list")

            degradation_count = 0
            for vs in vs_list:
                for route in vs.http_routes:
                    if route.get("fault"):
                        degradation_count += 1
                        break
                    if route.get("timeout"):
                        degradation_count += 1
                        break
                    retries = route.get("retries", {})
                    if retries.get("retryOn"):
                        degradation_count += 1
                        break

            if degradation_count > 0:
                raw_score += 2
                evidence.append(f"降级策略: {degradation_count} 个服务配置故障处理")
            else:
                evidence.append("降级策略: 未配置故障注入/超时/重试策略")
        else:
            evidence.append("降级策略: 未获取 VirtualService 数据")

        # ========== 5. APM 验证熔断效果 (+1分) ==========
        if store.available("apm.topology.metrics"):
            topology: list[ApmTopologyMetricsRecord] = store.get("apm.topology.metrics")

            cb_triggered = False
            for metric in topology:
                error_rate = (metric.error_count / metric.call_count) if metric.call_count > 0 else 0
                if 0.001 < error_rate < 0.05:
                    cb_triggered = True
                    break

            if cb_triggered:
                raw_score += 1
                evidence.append("APM 验证: 熔断机制可能在运行中")
            else:
                evidence.append("APM 验证: 无法确认熔断触发情况")
        else:
            evidence.append("APM 验证: 未获取 APM 数据")

        if raw_score >= 8:
            final_score = 8
            conclusion = "熔断与降级配置完善：网格熔断 + 客户端熔断 + 降级策略"
        elif raw_score >= 7:
            final_score = 7
            conclusion = "熔断配置优秀：建议增加客户端熔断框架"
        elif raw_score >= 6:
            final_score = 6
            conclusion = "熔断配置良好：建议完善降级策略"
        elif raw_score >= 5:
            final_score = 5
            conclusion = "熔断配置较好：建议扩大服务网格覆盖"
        elif raw_score >= 4:
            final_score = 4
            conclusion = "熔断配置一般：有基础能力，建议优化"
        elif raw_score >= 3:
            final_score = 3
            conclusion = "熔断配置起步：建议增加服务网格熔断"
        elif raw_score >= 2:
            final_score = 2
            conclusion = "熔断能力有限：仅有客户端或网格配置"
        elif raw_score >= 1:
            final_score = 1
            conclusion = "熔断配置较差：需要全面改造"
        else:
            final_score = 0
            conclusion = "未配置熔断机制"

        return self._scored(final_score, conclusion, evidence)


class CommRetrySafetyAnalyzer(Analyzer):
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
        evidence = []
        raw_score = 0

        # ========== 1. Istio VirtualService 重试检测 ==========
        vs_list: list[IstioVirtualServiceRecord] = store.get("k8s.istio.virtual_service.list")

        istio_retry_count = 0
        istio_safe_retry = 0
        istio_perfect_retry = 0
        unsafe_vs_details = []

        if vs_list:
            evidence.append(f"VirtualService 总数: {len(vs_list)}")

            for vs in vs_list:
                has_any_retry = False
                all_routes_safe = True
                has_perfect_config = False

                for route in vs.http_routes:
                    retries = route.get("retries", {})
                    if not retries:
                        continue

                    has_any_retry = True
                    attempts = retries.get("attempts", 0)
                    per_try_timeout = retries.get("perTryTimeout", "")
                    retry_on = retries.get("retryOn", "")
                    retry_interval = retries.get("retryInterval", "")

                    safe_conditions = ["5xx", "connect-failure", "retriable", "gateway-error", "refused-stream"]
                    is_safe_condition = not retry_on or any(c in retry_on for c in safe_conditions)

                    dangerous_conditions = ["*", "all", "retriable-status-codes"]
                    is_dangerous = any(c in retry_on for c in dangerous_conditions) if retry_on else False

                    reasonable_attempts = 2 <= attempts <= 4 if attempts else False

                    has_backoff = bool(per_try_timeout or retry_interval)

                    if is_dangerous:
                        all_routes_safe = False
                        unsafe_vs_details.append(f"{vs.name}(危险条件)")
                    elif not is_safe_condition:
                        all_routes_safe = False
                        unsafe_vs_details.append(f"{vs.name}(不安全条件)")
                    elif not reasonable_attempts and attempts > 4:
                        all_routes_safe = False
                        unsafe_vs_details.append(f"{vs.name}(重试次数过多:{attempts})")

                    if is_safe_condition and reasonable_attempts and has_backoff:
                        has_perfect_config = True

                if has_any_retry:
                    istio_retry_count += 1
                    if all_routes_safe:
                        istio_safe_retry += 1
                    if has_perfect_config:
                        istio_perfect_retry += 1

            if istio_retry_count > 0:
                evidence.append(f"Istio 重试配置: {istio_retry_count} 个 VirtualService")
                evidence.append(f"  - 安全配置: {istio_safe_retry} 个")
                evidence.append(f"  - 完美配置(退避+合理次数): {istio_perfect_retry} 个")

                if unsafe_vs_details:
                    evidence.append(f"  - 不安全配置: {', '.join(unsafe_vs_details[:3])}")
            else:
                evidence.append("Istio: 未配置重试策略")
        else:
            evidence.append("Istio: 未获取 VirtualService 数据")

        # ========== 2. 重试覆盖率评分 (+2分) ==========
        if vs_list and istio_retry_count > 0:
            coverage = istio_retry_count / len(vs_list)
            if coverage >= 0.5:
                raw_score += 2
                evidence.append(f"重试覆盖率: 优秀 ({coverage:.0%})")
            elif coverage >= 0.2:
                raw_score += 1
                evidence.append(f"重试覆盖率: 一般 ({coverage:.0%})")
            else:
                evidence.append(f"重试覆盖率: 较低 ({coverage:.0%})")
        elif istio_retry_count > 0:
            raw_score += 1
            evidence.append("重试覆盖率: 有配置但无法计算覆盖率")

        # ========== 3. 安全重试策略评分 (+2分) ==========
        if istio_safe_retry > 0:
            safe_ratio = istio_safe_retry / istio_retry_count if istio_retry_count > 0 else 0
            if safe_ratio >= 0.8:
                raw_score += 2
                evidence.append("安全策略: 优秀 (>=80% 配置安全)")
            elif safe_ratio >= 0.5:
                raw_score += 1
                evidence.append("安全策略: 良好 (>=50% 配置安全)")
            else:
                raw_score += 1
                evidence.append("安全策略: 一般，建议优化重试条件")
        else:
            evidence.append("安全策略: 未配置安全重试条件")

        # ========== 4. 退避机制评分 (+1分) ==========
        if istio_perfect_retry > 0:
            raw_score += 1
            evidence.append("退避机制: 已配置超时/间隔控制")
        elif istio_retry_count > 0:
            evidence.append("退避机制: 建议配置 perTryTimeout 和 retryInterval")

        # ========== 5. 客户端重试框架检测 (+1分) ==========
        client_retry_found = False

        if store.available("codeup.repo.file_tree"):
            file_tree: list[CodeupRepoFileTreeRecord] = store.get("codeup.repo.file_tree")

            retry_frameworks = {
                "spring-retry": ["spring-retry", "@retryable"],
                "resilience4j": ["resilience4j-retry", "@retry"],
                "guava-retrying": ["guava-retrying"],
                "tenacity": ["tenacity"]  # Python
            }

            found_frameworks = []
            for f in file_tree:
                if not f.name:
                    continue
                name_lower = f.name.lower()

                for framework, keywords in retry_frameworks.items():
                    if any(kw in name_lower for kw in keywords):
                        client_retry_found = True
                        if framework not in found_frameworks:
                            found_frameworks.append(framework)

            if client_retry_found:
                raw_score += 1
                evidence.append(f"客户端重试: 检测到 {', '.join(found_frameworks)}")
            else:
                evidence.append("客户端重试: 未检测到重试框架")
        else:
            evidence.append("客户端重试: 未获取代码库数据")

        if raw_score >= 5:
            final_score = 5
            conclusion = "安全重试机制完善：网格重试 + 客户端框架 + 退避策略"
        elif raw_score >= 4:
            final_score = 4
            conclusion = "重试配置良好：建议增加客户端重试框架"
        elif raw_score >= 3:
            final_score = 3
            conclusion = "重试配置较好：建议优化退避机制"
        elif raw_score >= 2:
            final_score = 2
            conclusion = "重试配置一般：建议扩大覆盖范围"
        elif raw_score >= 1:
            final_score = 1
            conclusion = "重试配置起步：有基础能力但需优化"
        else:
            final_score = 0
            conclusion = "未配置重试机制"

        if raw_score == 0:
            return self._not_scored("未配置重试策略", evidence)

        return self._scored(final_score, conclusion, evidence)


class CommServiceMeshAnalyzer(Analyzer):
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
        evidence = []
        raw_score = 0

        services: list[K8sServiceRecord] = store.get("k8s.service.list")
        if not isinstance(services, list):
            services = []

        total_services = len(services)
        evidence.append(f"K8s Service 数量: {total_services}")

        vs_list: list[IstioVirtualServiceRecord] = store.get("k8s.istio.virtual_service.list")
        dr_list: list[IstioDestinationRuleRecord] = store.get("k8s.istio.destination_rule.list")
        gw_list: list[IstioGatewayRecord] = store.get("k8s.istio.gateway.list")

        istio_resource_count = 0
        if vs_list:
            istio_resource_count += len(vs_list)
            evidence.append(f"VirtualService: {len(vs_list)} 个")
        if dr_list:
            istio_resource_count += len(dr_list)
            evidence.append(f"DestinationRule: {len(dr_list)} 个")
        if gw_list:
            istio_resource_count += len(gw_list)
            evidence.append(f"Gateway: {len(gw_list)} 个")

        if istio_resource_count > 0:
            if vs_list and total_services > 0:
                mesh_coverage = len(vs_list) / total_services
                if mesh_coverage >= 0.5:
                    raw_score += 1
                    evidence.append(f"网格覆盖率: 优秀 ({mesh_coverage:.0%})")
                elif mesh_coverage >= 0.2:
                    raw_score += 1
                    evidence.append(f"网格覆盖率: 一般 ({mesh_coverage:.0%})")
                else:
                    evidence.append(f"网格覆盖率: 较低 ({mesh_coverage:.0%})")
            else:
                raw_score += 1
                evidence.append("网格覆盖率: 有 Istio 配置但无法计算覆盖率")
        else:
            evidence.append("未检测到 Istio 配置")

        traffic_management_features = []

        if vs_list:
            canary_count = 0
            for vs in vs_list:
                for route in vs.http_routes:
                    if route.get("route"):
                        destinations = route.get("route", [])
                        if len(destinations) > 1:
                            weights = [d.get("weight", 0) for d in destinations]
                            if any(0 < w < 100 for w in weights):
                                canary_count += 1
                                break

            if canary_count > 0:
                traffic_management_features.append(f"金丝雀发布({canary_count})")

            mirror_count = sum(1 for vs in vs_list if any(
                route.get("mirror") for route in vs.http_routes
            ))
            if mirror_count > 0:
                traffic_management_features.append(f"流量镜像({mirror_count})")

        if dr_list:
            lb_count = sum(1 for dr in dr_list
                           if dr.traffic_policy and dr.traffic_policy.get("loadBalancer"))
            if lb_count > 0:
                traffic_management_features.append(f"负载均衡({lb_count})")

            cb_count = sum(1 for dr in dr_list
                           if dr.traffic_policy and dr.traffic_policy.get("outlierDetection"))
            if cb_count > 0:
                traffic_management_features.append(f"熔断({cb_count})")

        if traffic_management_features:
            raw_score += 1
            evidence.append(f"流量管理: {', '.join(traffic_management_features)}")
        else:
            evidence.append("流量管理: 未检测到高级流量管理功能")

        mtls_count = 0
        if dr_list:
            for dr in dr_list:
                if dr.traffic_policy:
                    tls = dr.traffic_policy.get("tls", {})
                    if tls.get("mode") in ["ISTIO_MUTUAL", "MUTUAL"]:
                        mtls_count += 1

        if mtls_count > 0:
            raw_score += 0.5
            evidence.append(f"mTLS 安全: {mtls_count} 个服务启用双向 TLS")
        else:
            evidence.append("mTLS 安全: 未检测到双向 TLS 配置")

        other_mesh_detected = []

        linkerd_services = 0
        for s in services:
            if s.name and "linkerd" in s.name.lower():
                linkerd_services += 1

        if linkerd_services > 0:
            other_mesh_detected.append(f"Linkerd({linkerd_services})")

        consul_services = sum(1 for s in services
                              if s.name and "consul" in s.name.lower())
        if consul_services > 0:
            other_mesh_detected.append(f"Consul({consul_services})")

        if other_mesh_detected:
            raw_score += 0.5
            evidence.append(f"其他网格: {', '.join(other_mesh_detected)}")

        final_score = min(int(raw_score), 3)

        if final_score >= 3:
            conclusion = "服务网格配置完善：Istio + 流量管理 + mTLS"
        elif final_score >= 2:
            conclusion = "服务网格配置良好：有 Istio 和流量管理功能"
        elif final_score >= 1:
            conclusion = "服务网格配置一般：基础 Istio 已部署"
        elif istio_resource_count > 0:
            conclusion = "服务网格起步：有 Istio 资源但功能未启用"
        elif other_mesh_detected:
            conclusion = f"使用其他服务网格: {', '.join(other_mesh_detected)}"
        else:
            conclusion = "未检测到服务网格配置"

        if final_score == 0 and istio_resource_count == 0 and not other_mesh_detected:
            return self._not_scored("未检测到服务网格 (Istio/Linkerd/Consul) 配置", evidence)

        return self._scored(final_score, conclusion, evidence)


COMM_ANALYZERS = [
    CommPatternDiversityAnalyzer(),
    SvcDiscoveryDynamicAnalyzer(),
    CommLoadBalancingAnalyzer(),
    CommCircuitBreakerAnalyzer(),
    CommRetrySafetyAnalyzer(),
    CommServiceMeshAnalyzer(),
]
