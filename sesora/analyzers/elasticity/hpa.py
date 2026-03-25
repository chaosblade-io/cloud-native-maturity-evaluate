"""
Elasticity 维度 - 水平扩展能力 (Horizontal Scaling) 分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)               | 分值   | 评分标准                                                     |
| hs_implemented             | 8      | 系统架构支持多实例部署，且无状态化设计允许随时增加节点       |
| hs_auto_scaling            | 12     | 配置 HPA/KEDA，且过去 30 天有成功触发的扩缩容记录            |
| hs_triggers_richness       | 0-8    | 仅CPU/内存:2分, +QPS/网络:+3分, +业务指标:+3分               |
| hs_policy_intelligence     | 0-8   | 固定阈值:2分, +预测性缩放:+6分               |
"""
from ...core.analyzer import Analyzer, ScoreResult
from ...schema.k8s import K8sDeploymentRecord, K8sHpaRecord, K8sEventRecord, K8sAhpaMetricsRecord
from datetime import datetime, timedelta, timezone


class HsImplementedAnalyzer(Analyzer):
    """
    水平扩展实现分析器
    
    评估标准：系统架构支持多实例部署，且无状态化设计允许随时增加节点
    
    数据来源：
    - ACK API：Deployment spec.replicas 字段，检查是否 > 1
    - kube-state-metrics：kube_deployment_spec_replicas，统计 replicas=1 的比例
    """

    def key(self) -> str:
        return "hs_implemented"

    def dimension(self) -> str:
        return "Elasticity"

    def category(self) -> str:
        return "水平扩展能力"

    def max_score(self) -> int:
        return 8

    def required_data(self) -> list[str]:
        return ["k8s.deployment.list"]

    def analyze(self, store) -> ScoreResult:
        # Todo: 当前只实现了前两个评估，后续的ARMS和12-Factor App还需要补充
        deployments: list[K8sDeploymentRecord] = store.get("k8s.deployment.list")

        if not deployments:
            return self._not_evaluated("未发现任何 Deployment")

        multi_replica = [d for d in deployments if d.replicas > 1]
        single_replica = [d for d in deployments if d.replicas == 1]

        ratio = len(multi_replica) / len(deployments)

        evidence = [
            f"总 Deployment 数: {len(deployments)}",
            f"多副本 (replicas > 1): {len(multi_replica)}",
            f"单副本 (replicas = 1): {len(single_replica)}"
        ]

        if ratio >= 0.9:
            return self._scored(8, "系统架构支持多实例部署，无状态化设计完善", evidence)
        elif ratio >= 0.8:
            return self._scored(7, "绝大部分工作负载支持水平扩展", evidence)
        elif ratio >= 0.7:
            return self._scored(6, "大部分工作负载支持水平扩展", evidence)
        elif ratio >= 0.6:
            return self._scored(5, "多数工作负载支持水平扩展", evidence)
        elif ratio >= 0.5:
            return self._scored(4, "部分工作负载支持水平扩展", evidence)
        elif ratio >= 0.3:
            return self._scored(3, "少量工作负载支持水平扩展", evidence)
        elif ratio >= 0.1:
            return self._scored(2, "极少数工作负载支持水平扩展", evidence)
        elif ratio > 0:
            return self._scored(1, "几乎无工作负载支持水平扩展", evidence)
        else:
            return self._scored(1, "所有工作负载均为单副本，不支持水平扩展", evidence)


class HsAutoScalingAnalyzer(Analyzer):
    """
    自动扩缩容分析器
    
    评估标准：配置 HPA/KEDA，且过去 30 天有成功触发的扩缩容记录（非静默配置）
    
    数据来源：
    - ACK API：GET /apis/autoscaling/v2/namespaces/{ns}/horizontalpodautoscalers
    - 检索过去30天的扩缩容事件日志（kubectl get events），确认是否有自动触发记录
    """

    def key(self) -> str:
        return "hs_auto_scaling"

    def dimension(self) -> str:
        return "Elasticity"

    def category(self) -> str:
        return "水平扩展能力"

    def max_score(self) -> int:
        return 12

    def required_data(self) -> list[str]:
        return ["k8s.hpa.list"]

    def optional_data(self) -> list[str]:
        return ["k8s.event.list"]

    def analyze(self, store) -> ScoreResult:
        hpas: list[K8sHpaRecord] = store.get("k8s.hpa.list")

        if not hpas:
            return self._not_scored("未配置 HPA 自动伸缩", [])

        active_hpas = [h for h in hpas if h.min_replicas != h.max_replicas]

        if not active_hpas:
            invalid_count = len(hpas) - len(active_hpas)
            return self._not_scored(
                f"HPA 配置无效（{invalid_count} 个 HPA 的 min_replicas = max_replicas）",
                [f"共 {len(hpas)} 个 HPA，其中 {invalid_count} 个无法实际扩缩容"]
            )

        evidence = [f"有效 HPA 数量: {len(active_hpas)}/{len(hpas)}"]

        if store.available("k8s.event.list"):
            events: list[K8sEventRecord] = store.get("k8s.event.list")

            now = datetime.now(timezone.utc)
            threshold = now - timedelta(days=30)

            hpa_scale_events = []

            for e in events:
                event_time = e.last_timestamp
                if event_time is None:
                    event_time = datetime.now(timezone.utc)
                elif getattr(event_time, "tzinfo") is None:
                    event_time = event_time.replace(tzinfo=timezone.utc)

                if event_time and event_time < threshold:
                    continue

                is_hpa_event = False
                source_component = ""

                source_obj = e.source
                if source_obj:
                    source_component = source_obj.get('component', '')

                if source_component == "horizontal-pod-autoscaler":
                    is_hpa_event = True

                reason = e.reason
                if is_hpa_event and reason == "SuccessfulRescale":
                    hpa_scale_events.append(e)

            if hpa_scale_events:
                event_count = len(hpa_scale_events)
                evidence.append(f"HPA 主动扩缩容事件 (过去 30 天): {event_count} 次")
                evidence.append(f"  验证来源组件: horizontal-pod-autoscaler")

                if event_count >= 10:
                    return self._scored(12, "HPA 已配置且近期有频繁成功的自动扩缩容记录", evidence)
                elif event_count >= 5:
                    return self._scored(10, "HPA 已配置且近期有多次成功的自动扩缩容记录", evidence)
                elif event_count >= 2:
                    return self._scored(8, "HPA 已配置且近期有成功的自动扩缩容记录", evidence)
                else:
                    return self._scored(6, "HPA 已配置且近期有少量自动扩缩容记录", evidence)
            else:
                evidence.append("过去 30 天内未检测到 HPA 组件触发的 SuccessfulRescale 事件")
                evidence.append("可能原因：流量稳定无需扩缩容、HPA 阈值配置过高、或 HPA 未实际生效")
                return self._scored(4, "HPA 已配置但近期无触发记录（静默配置或配置不当）", evidence)

        return self._scored(3, "HPA 已配置，但缺少事件数据无法验证是否触发", evidence)


class HsTriggersRichnessAnalyzer(Analyzer):
    """
    触发器丰富度分析器
    
    评估标准（累计评分，最高 8 分）：
    - 仅 CPU/内存：2 分 (基础)
    - 包含 QPS/网络流量：+3 分 (标配)
    - 包含业务指标 (队列长度/延迟)：+3 分 (高级)
    
    数据来源：
    - ACK API：HPA 对象的 spec.metrics[] 字段
    - 检查 type 字段：Resource（CPU/Mem）、Pods（自定义 Pod 指标）、Object、External
    """

    def key(self) -> str:
        return "hs_triggers_richness"

    def dimension(self) -> str:
        return "Elasticity"

    def category(self) -> str:
        return "水平扩展能力"

    def max_score(self) -> int:
        return 8

    def required_data(self) -> list[str]:
        return ["k8s.hpa.list"]

    def analyze(self, store) -> ScoreResult:
        hpas: list[K8sHpaRecord] = store.get("k8s.hpa.list")

        if not hpas:
            return self._not_scored("未配置 HPA", [])

        metric_types = set()
        evidence_details = []

        has_cpu_mem = False
        has_qps_network = False
        has_business_external = False

        RESOURCE_NAMES = {"cpu", "memory"}
        QPS_KEYWORDS = {"qps", "requests_per_second", "rps", "network_rx", "network_tx", "connections"}
        BUSINESS_KEYWORDS = {"queue_length", "consumer_lag", "latency_p99", "backlog", "pending_tasks"}

        for hpa in hpas:
            metrics_list = hpa.metrics
            for m in metrics_list:
                m_type = m.type
                metric_types.add(m_type)

                # 1. 处理 Resource 类型
                if m_type == "Resource":
                    if m.resource_name in RESOURCE_NAMES:
                        has_cpu_mem = True
                        evidence_details.append(f"Resource: {m.resource_name} ({m.target})")

                # 2. 处理 Pods 类型
                elif m_type == "Pods" and m.pods_metric:
                    name_lower = m.pods_metric.name.lower()
                    if any(kw in name_lower for kw in QPS_KEYWORDS):
                        has_qps_network = True
                    evidence_details.append(f"Pods: {m.pods_metric.name} ({m.target})")

                # 3. 处理 Object 类型
                elif m_type == "Object" and m.object_metric:
                    name_lower = m.object_metric.name.lower()
                    if any(kw in name_lower for kw in QPS_KEYWORDS):
                        has_qps_network = True
                    obj_info = ""
                    if m.object_target:
                        obj_info = f" on {m.object_target.kind}/{m.object_target.name}"
                    evidence_details.append(f"Object: {m.object_metric.name}{obj_info} ({m.target})")

                # 4. 处理 External 类型
                elif m_type == "External" and m.external_metric:
                    name_lower = m.external_metric.name.lower()
                    if any(kw in name_lower for kw in BUSINESS_KEYWORDS):
                        has_business_external = True
                    else:
                        has_qps_network = True
                    evidence_details.append(f"External: {m.external_metric.name} ({m.target})")

        evidence = []
        score = 0

        if has_cpu_mem:
            score += 3
            evidence.append("✓ 基础资源指标 (CPU/Memory): 3 分")
        elif "Resource" in metric_types:
            score += 2
            evidence.append("✓ 其他资源指标: 2 分")

        if has_qps_network:
            score += 2
            evidence.append("✓ 应用层指标 (QPS/网络/连接数): +2 分")

        if has_business_external:
            score += 3
            evidence.append("✓ 核心业务指标 (队列/延迟/Backlog): +3 分")
        elif "External" in metric_types and not has_business_external:
            score += 1
            evidence.append("✓ 外部指标配置 (未识别具体业务语义): +1 分")

        if metric_types:
            evidence.append(f"启用指标类型: {', '.join(sorted(metric_types))}")

        if evidence_details:
            unique_details = list(set(evidence_details))
            evidence.append(f"详细配置: {', '.join(unique_details[:8])}{'...' if len(unique_details) > 8 else ''}")

        if score == 0:
            return self._scored(1, "HPA 已配置但未发现有效监控指标", evidence)

        if score >= 8:
            return self._scored(8, "触发器指标极其丰富，覆盖资源、应用层及核心业务指标", evidence)
        elif score >= 6:
            return self._scored(7, "触发器指标丰富，覆盖资源及应用层/业务指标", evidence)
        elif score >= 5:
            return self._scored(6, "触发器指标较丰富，覆盖资源及应用层指标", evidence)
        elif score >= 4:
            if has_cpu_mem and not has_qps_network and not has_business_external:
                return self._scored(5, "仅使用基础资源指标 (CPU/Memory)，建议引入 QPS 等业务指标", evidence)
            return self._scored(4, "触发器指标较为单一，建议丰富指标类型", evidence)
        elif score >= 3:
            return self._scored(3, "触发器指标单一，主要依赖基础资源指标", evidence)
        elif score >= 2:
            return self._scored(2, "触发器指标配置较弱，覆盖有限", evidence)
        else:
            return self._scored(1, "HPA 指标配置非常薄弱", evidence)


class HsPolicyIntelligenceAnalyzer(Analyzer):
    """
    策略智能化分析器
    
    评估标准（累计评分，最高 12 分）：
    - 固定阈值：2 分
    - 定时/周期性策略：+3 分
    - 预测性缩放 (AHPA/Predictive)：+7 分
    
    数据来源：
    - ACK AHPA：k8s.metric.ahpa，检查 ahpa_reactive_pods、ahpa_predicted_pods 等指标
    - ACK API：AHPA 对象列表，检查是否配置了预测模式
    """

    def key(self) -> str:
        return "hs_policy_intelligence"

    def dimension(self) -> str:
        return "Elasticity"

    def category(self) -> str:
        return "水平扩展能力"

    def max_score(self) -> int:
        return 12

    def required_data(self) -> list[str]:
        return ["k8s.hpa.list"]

    def optional_data(self) -> list[str]:
        return ["k8s.ahpa.metrics"]

    def analyze(self, store) -> ScoreResult:
        hpas: list[K8sHpaRecord] = store.get("k8s.hpa.list")

        if not hpas:
            return self._scored(1, "未配置任何弹性策略", [])

        valid_hpas = [h for h in hpas if h.min_replicas != h.max_replicas]

        if not valid_hpas:
            return self._scored(
                1,
                "HPA 配置无效（所有 HPA 的 min_replicas = max_replicas）",
                ["请调整 min/max 副本数以启用自动扩缩容"]
            )

        evidence = []
        score = 0
        strategy_details = []

        score += 2
        strategy_details.append(f"基础阈值策略 ({len(valid_hpas)} 个 HPA)")

        has_ahpa = False
        ahpa_count = 0

        if store.available("k8s.ahpa.list"):
            ahpa_records: list[K8sAhpaMetricsRecord] = store.get("k8s.ahpa.list")
            if ahpa_records:
                active_ahpa = [a for a in ahpa_records if a.prediction_enabled]

                if active_ahpa:
                    has_ahpa = True
                    ahpa_count = len(active_ahpa)
                    score += 6
                    evidence.append(f"✓ 预测性缩放 (AHPA): +6 分 (共 {ahpa_count} 个)")

        evidence.insert(0, f"✓ 基础固定阈值策略: 2 分 ({len(valid_hpas)} 个有效 HPA)")

        if has_ahpa:
            if ahpa_count >= 3:
                return self._scored(8, "采用预测性弹性策略 (AHPA)，覆盖多个应用，架构先进", evidence)
            else:
                return self._scored(7, "采用预测性弹性策略 (AHPA)，能应对突发流量", evidence)
        else:
            return self._scored(2, "仅使用基础固定阈值策略，建议引入 AHPA 应对突发流量", evidence)


HPA_ANALYZERS = [
    HsImplementedAnalyzer(),
    HsAutoScalingAnalyzer(),
    HsTriggersRichnessAnalyzer(),
    HsPolicyIntelligenceAnalyzer(),
]
