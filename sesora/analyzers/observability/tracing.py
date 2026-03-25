"""
Observability 维度 - 分布式追踪能力 (Tracing) 分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)            | 分值 | 评分标准                                                       |
| trace_propagation       | 6    | 跨服务传播：TraceID 在微服务、MQ、DB调用链中完整透传           |
| trace_sampling          | 6    | 智能采样：错误请求100%采集，正常请求按比率采集                 |
| trace_visualization     | 5    | 拓扑与瀑布图：可视化调用链瀑布图和依赖拓扑图，支持钻取        |
| trace_coverage          | 0-3  | 接入覆盖率：全面(3)/核心(2)/试点(1)                            |
"""
from sesora.core.analyzer import Analyzer, ScoreResult
from sesora.schema.apm import (
    ApmServiceRecord, ApmTraceRecord, ApmServiceDependencyRecord,
    ApmSamplingConfigRecord
)
from sesora.schema.k8s import K8sDeploymentRecord


class TracePropagationAnalyzer(Analyzer):
    """
    跨服务传播分析器
    
    评估标准：TraceID 是否能在微服务、消息队列、数据库调用链中完整透传，无断点
    
    数据来源：
    - UModel：apm.external.database、apm.external.message、apm.external.rpc_client 等
    - ARMS：查询完整 Trace，检查 Span 是否覆盖 API Gateway -> 微服务 -> MQ -> DB 全路径
    """

    def key(self) -> str:
        return "trace_propagation"

    def dimension(self) -> str:
        return "Observability"

    def category(self) -> str:
        return "分布式追踪能力"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return ["apm.service.dependency"]

    def optional_data(self) -> list[str]:
        return ["apm.trace.list"]

    def analyze(self, store) -> ScoreResult:
        dependencies: list[ApmServiceDependencyRecord] = store.get("apm.service.dependency")

        if not dependencies:
            return self._not_scored("未获取到服务依赖关系", [])

        evidence = [f"服务依赖关系: {len(dependencies)} 条"]
        score = 0.0

        # --- 1. 调用类型覆盖度 (最高 3 分) ---
        call_types: set[str] = set()
        for dep in dependencies:
            ct = (dep.call_type or "").lower()
            if any(kw in ct for kw in ["http", "grpc", "rpc", "dubbo"]):
                call_types.add("service")
            if any(kw in ct for kw in ["mysql", "redis", "mongo", "db", "database", "postgres"]):
                call_types.add("database")
            if any(kw in ct for kw in ["kafka", "rocketmq", "mq", "rabbitmq", "message"]):
                call_types.add("message_queue")
            if any(kw in ct for kw in ["gateway", "api"]):
                call_types.add("gateway")

        type_count = len(call_types)
        evidence.append(f"拓扑调用类型: {', '.join(call_types) if call_types else '未识别'} ({type_count} 种)")

        type_score = type_count / 4 * 3.0  # 4 种全覆盖得 3 分
        score += type_score

        has_cross_service = "service" in call_types
        has_db = "database" in call_types
        has_mq = "message_queue" in call_types
        has_gw = "gateway" in call_types

        if has_gw:   evidence.append("✓ Gateway 层透传已覆盖")
        if has_cross_service: evidence.append("✓ 微服务间透传已覆盖")
        if has_mq:   evidence.append("✓ 消息队列异步透传已覆盖")
        if has_db:   evidence.append("✓ DB 调用透传已覆盖")

        # --- 2. 链路深度与完整性 (最高 2 分) ---
        traces: list[ApmTraceRecord] = store.get("apm.trace.list")
        if traces:
            cross_service_traces = [t for t in traces if t.span_count >= 3]
            deep_traces = [t for t in traces if t.span_count >= 5]
            complete_ratio = len(cross_service_traces) / len(traces) if traces else 0

            evidence.append(f"实际 Trace 数: {len(traces)}，跨服务链路 (>=3 span): "
                            f"{len(cross_service_traces)} ({complete_ratio * 100:.0f}%)")
            if deep_traces:
                evidence.append(f"深度链路 (>=5 span): {len(deep_traces)} 条")

            if complete_ratio >= 0.7:
                score += 2.0
                evidence.append("✓ 多数 Trace 跨服务透传成功")
            elif complete_ratio >= 0.3:
                score += 1.0
                evidence.append("ℹ️ 部分 Trace 跨服务透传成功")
            else:
                evidence.append("⚠️ 跨服务 Trace 较少，透传效果待验证")
        else:
            evidence.append("ℹ️ 无实际 Trace 数据可验证，仅依拓扑估算透传范围")

        # --- 3. 关键路径惩罚 (最大 -1 分) ---
        if has_cross_service and traces is not None and len(traces) == 0:
            score -= 1.0
            evidence.append("⚠️ 服务间调用存在但无 Trace 数据，透传可能未真正生效")

        final_score = max(min(round(score), 6), 0)

        if final_score >= 6:
            conclusion = "TraceID 全链路透传：覆盖 Gateway/微服务/MQ/DB，跨服务验证充分"
        elif final_score >= 4:
            conclusion = "TraceID 透传范围较广，建议补全缺失调用类型"
        elif final_score >= 2:
            conclusion = "TraceID 透传基础，仅覆盖部分调用路径，建议延伸到 MQ/DB"
        else:
            conclusion = "TraceID 透传能力薄弱，建议检查探针配置"

        return self._scored(final_score, conclusion, evidence)


class TraceSamplingAnalyzer(Analyzer):
    """
    智能采样分析器
    
    评估标准：是否实施了动态采样策略
    - 错误请求 (Status >= 500 或 Exception) 采样率必须为 100%
    - 正常请求按比率采集，平衡性能与存储
    
    数据来源：
    - ARMS：采样规则配置 API，检查是否配置了尾采样 (tail-based) 或概率采样 (probabilistic)
    """

    def key(self) -> str:
        return "trace_sampling"

    def dimension(self) -> str:
        return "Observability"

    def category(self) -> str:
        return "分布式追踪能力"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return ["apm.trace.list"]

    def optional_data(self) -> list[str]:
        return ["apm.sampling.config"]

    def analyze(self, store) -> ScoreResult:
        traces: list[ApmTraceRecord] = store.get("apm.trace.list")

        if not traces:
            return self._not_scored("未获取到链路数据", [])

        evidence = [f"采样链路数: {len(traces)}"]
        score = 0.0

        error_traces = [t for t in traces if t.has_error]
        slow_traces = [t for t in traces if t.duration_ms > 1000]
        error_ratio = len(error_traces) / len(traces) if traces else 0.0

        evidence.append(f"错误链路: {len(error_traces)} 条 ({error_ratio * 100:.1f}%)")
        if slow_traces:
            evidence.append(f"慢链路 (>1s): {len(slow_traces)} 条")

        configs: list[ApmSamplingConfigRecord] = store.get("apm.sampling.config")
        if configs:
            total = len(configs)
            evidence.append(f"采样配置应用数: {total}")

            strategies = [c.strategy for c in configs]
            error_rates = [c.error_sample_rate for c in configs]
            slow_rates = [c.slow_sample_rate for c in configs]
            normal_rates = [c.sample_rate for c in configs]

            tail_count = strategies.count("tail-based")
            prob_count = strategies.count("probabilistic")
            error_100_count = sum(1 for r in error_rates if r >= 1.0)
            slow_100_count = sum(1 for r in slow_rates if r >= 1.0)
            has_downsample_count = sum(1 for r in normal_rates if r < 1.0)

            avg_error_rate = sum(error_rates) / total
            avg_normal_rate = sum(normal_rates) / total

            # 1. 采样策略类型（最高 2 分）
            if tail_count / total >= 0.8:
                score += 2.0
                evidence.append(f"✓ 尾采样策略（{tail_count}/{total} 应用，最优）")
            elif tail_count > 0:
                score += 1.5
                evidence.append(f"✓ 部分应用采用尾采样 ({tail_count}/{total})")
            elif prob_count / total >= 0.8 and avg_normal_rate < 1.0:
                score += 1.5
                evidence.append(f"✓ 概率采样 + 降采率 avg {avg_normal_rate * 100:.0f}%")
            elif prob_count > 0:
                score += 1.0
                evidence.append(f"ℹ️ 概率采样 ({prob_count}/{total} 应用)")
            else:
                score += 0.5
                evidence.append(f"ℹ️ 固定/默认采样策略，策略分布: {set(strategies)}")

            # 2. 错误请求 100% 采集（最高 2 分）
            error_100_ratio = error_100_count / total
            if error_100_ratio >= 0.9:
                score += 2.0
                evidence.append(f"✓ {error_100_count}/{total} 应用错误请求 100% 采集")
            elif error_100_ratio >= 0.5:
                score += 1.0
                evidence.append(
                    f"ℹ️ {error_100_count}/{total} 应用配置错误100%采集，平均错误采样率 {avg_error_rate * 100:.0f}%")
            else:
                evidence.append(
                    f"⚠️ 仅 {error_100_count}/{total} 应用错误100%采集，平均采样率 {avg_error_rate * 100:.0f}%，可能丢失错误现场")

            # 3. 慢请求覆盖（最高 1 分）
            slow_100_ratio = slow_100_count / total
            if slow_100_ratio >= 0.8:
                score += 1.0
                evidence.append(f"✓ {slow_100_count}/{total} 应用慢请求 100% 采集")
            elif slow_100_ratio >= 0.4:
                score += 0.5
                evidence.append(f"ℹ️ {slow_100_count}/{total} 应用慢请求 100% 采集")

            # 4. 正常请求降采覆盖（最高 1 分）
            if has_downsample_count / total >= 0.8:
                score += 1.0
                evidence.append(
                    f"✓ {has_downsample_count}/{total} 应用配置降采，avg 正常采样率 {avg_normal_rate * 100:.0f}%")
            elif has_downsample_count > 0:
                score += 0.5
                evidence.append(f"ℹ️ {has_downsample_count}/{total} 应用配置降采")
            else:
                evidence.append(f"⚠️ 所有应用正常请求全采（100%），存储成本高，建议配置降采")

        else:
            evidence.append("ℹ️ 未获取到采样配置，依链路数据间接评估")

            if error_traces:
                score += 1.0
                evidence.append("ℹ️ 发现错误链路被采集，采样策略覆盖错误场景")

            if error_ratio >= 0.05 and slow_traces:
                score += 0.5
                evidence.append("ℹ️ 错误+慢链路均有采集，疑似存在差异化采样策略")

        final_score = max(min(round(score), 6), 0)

        if final_score >= 5:
            conclusion = "智能采样策略完善：尾采样/概率采样+错误100%采集+慢请求覆盖"
        elif final_score >= 3:
            conclusion = "采样策略较好，建议完善错误100%采集或慢请求覆盖"
        elif final_score >= 1:
            conclusion = "采样策略基础，建议引入尾采样或概率降采策略"
        else:
            conclusion = "采样策略未配置或无法评估"

        return self._scored(final_score, conclusion, evidence)


class TraceVisualizationAnalyzer(Analyzer):
    """
    拓扑与瀑布图分析器
    
    评估标准：是否提供可视化的调用链瀑布图和依赖拓扑图，支持钻取分析
    
    数据来源：
    - UModel：apm.metric.topology，服务依赖拓扑数据
    - ARMS：判断是否提供调用链瀑布图（平台能力）
    """

    def key(self) -> str:
        return "trace_visualization"

    def dimension(self) -> str:
        return "Observability"

    def category(self) -> str:
        return "分布式追踪能力"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["apm.service.dependency"]

    def optional_data(self) -> list[str]:
        return ["apm.trace.list"]

    def analyze(self, store) -> ScoreResult:
        dependencies: list[ApmServiceDependencyRecord] = store.get("apm.service.dependency")

        if not dependencies:
            return self._not_scored("未获取到服务依赖关系，无法生成拓扑", [])

        services: set[str] = set()
        for dep in dependencies:
            services.add(dep.source_service)
            services.add(dep.target_service)

        service_count = len(services)
        edge_count = len(dependencies)

        evidence = [
            f"服务节点: {service_count}",
            f"依赖边: {edge_count}"
        ]
        score = 0.0

        # --- 1. 拓扑可视化价值（最高 2 分）---
        topology_value = min(service_count / 15, 1.0) * 1.5 + min(edge_count / 30, 1.0) * 0.5
        score += topology_value

        if service_count >= 10:
            evidence.append(f"✓ 拓扑规模较大 ({service_count} 服务)，可视化价值高")
        elif service_count >= 5:
            evidence.append(f"ℹ️ 拓扑规模适中 ({service_count} 服务)")
        else:
            evidence.append(f"⚠️ 拓扑规模较小 ({service_count} 服务)，可视化价值有限")

        # --- 2. 瀑布图数据支撑（最高 2 分）---
        traces: list[ApmTraceRecord] = store.get("apm.trace.list")
        if traces:
            cross_service_traces = [t for t in traces if t.span_count >= 3]
            cross_ratio = len(cross_service_traces) / len(traces) if traces else 0.0

            evidence.append(
                f"跨服务链路 (>=3 span): {len(cross_service_traces)}/{len(traces)} ({cross_ratio * 100:.0f}%)")

            waterfall_score = min(cross_ratio * 2.5, 2.0)
            score += waterfall_score

            if cross_ratio >= 0.6:
                evidence.append("✓ 大量跨服务链路，瀑布图价值高")
            elif cross_ratio >= 0.3:
                evidence.append("ℹ️ 部分跨服务链路，瀑布图有一定价值")
            else:
                evidence.append("⚠️ 跨服务链路较少，瀑布图价值有限")
        else:
            evidence.append("ℹ️ 无 Trace 数据，无法评估瀑布图能力")

        # --- 3. 调用类型多样性（最高 1 分）---
        call_types: set[str] = set()
        for dep in dependencies:
            ct = (dep.call_type or "").lower()
            if any(kw in ct for kw in ["http", "grpc", "rpc", "dubbo"]):
                call_types.add("service")
            if any(kw in ct for kw in ["mysql", "redis", "mongo", "db", "database"]):
                call_types.add("database")
            if any(kw in ct for kw in ["kafka", "rocketmq", "mq", "rabbitmq"]):
                call_types.add("message_queue")

        type_count = len(call_types)
        if type_count >= 3:
            score += 1.0
            evidence.append(f"✓ 调用类型多样 ({', '.join(call_types)})，可视化场景丰富")
        elif type_count >= 2:
            score += 0.5
            evidence.append(f"ℹ️ 调用类型较丰富 ({', '.join(call_types)})")

        final_score = max(min(round(score), 5), 0)

        if final_score >= 4:
            conclusion = "拓扑与瀑布图可视化完善：规模适中、跨服务链路充足"
        elif final_score >= 2:
            conclusion = "具备可视化能力，建议扩展跨服务链路或增加拓扑规模"
        elif final_score >= 1:
            conclusion = "可视化能力基础，拓扑规模较小或链路数据不足"
        else:
            conclusion = "可视化能力有限，建议检查 APM 接入情况"

        return self._scored(final_score, conclusion, evidence)


class TraceCoverageAnalyzer(Analyzer):
    """
    接入覆盖率分析器
    
    评估标准：
    - 全面 (3): 所有微服务及中间件均接入
    - 核心 (2): 仅核心链路接入
    - 试点 (1): 仅个别服务接入
    
    数据来源：
    - UModel：apm.service entity_set，统计接入 ARMS 的应用数量
    - UModel：k8s.deployment entity_set，统计 K8s 中运行的工作负载数量
    - 判断逻辑：Trace 接入率 = ARMS 中的服务数 / K8s 中的 Deployment 数
    """

    def key(self) -> str:
        return "trace_coverage"

    def dimension(self) -> str:
        return "Observability"

    def category(self) -> str:
        return "分布式追踪能力"

    def max_score(self) -> int:
        return 3

    def required_data(self) -> list[str]:
        return ["apm.service.list"]

    def optional_data(self) -> list[str]:
        return ["k8s.deployment.list"]

    def analyze(self, store) -> ScoreResult:
        services: list[ApmServiceRecord] = store.get("apm.service.list")

        if not services:
            return self._not_scored("未接入 APM 服务监控", [])

        traced_services = [s for s in services if s.trace_enabled]
        total_apm = len(services)
        traced_count = len(traced_services)

        evidence = [
            f"APM 注册服务数: {total_apm}",
            f"Trace 已接入服务: {traced_count}"
        ]

        deployments: list[K8sDeploymentRecord] = store.get("k8s.deployment.list")
        if deployments:
            total_workloads = len(deployments)
            coverage_ratio = min(traced_count / total_workloads, 1.0) if total_workloads > 0 else 0.0

            evidence.append(f"K8s Deployment 总数: {total_workloads}")
            evidence.append(f"估算 Trace 覆盖率: {coverage_ratio * 100:.1f}% (保守估算)")

            score = coverage_ratio * 3.0
            final_score = max(min(round(score), 3), 0)

            if final_score >= 3:
                conclusion = "全面接入：绝大多数工作负载已接入 Trace"
            elif final_score >= 2:
                conclusion = "核心接入：超过半数工作负载已接入 Trace"
            elif final_score >= 1:
                conclusion = "部分接入：少量工作负载已接入 Trace"
            else:
                conclusion = "接入率低：大部分工作负载未接入 Trace"

            return self._scored(final_score, conclusion, evidence)

        apm_ratio = traced_count / total_apm if total_apm > 0 else 0.0
        evidence.append(f"APM 内部接入率: {apm_ratio * 100:.1f}% (缺少 K8s 全量数据验证)")

        if apm_ratio >= 0.9 and traced_count >= 3:
            score = 2.0
            conclusion = "接入良好：APM 内部绝大多数已接入 (注: 缺少 K8s 全量数据验证)"
        elif apm_ratio >= 0.5 and traced_count >= 3:
            score = 1.5
            conclusion = "部分接入：APM 内部超过半数已接入 (注: 缺少 K8s 全量数据验证)"
        elif traced_count >= 3:
            score = 1.0
            conclusion = "初步接入：APM 内部少量服务已接入 (注: 缺少 K8s 全量数据验证)"
        elif traced_count >= 1:
            score = 0.5
            conclusion = "试点接入：仅个别服务已接入"
        else:
            return self._not_scored("未启用 Trace 功能", evidence)

        final_score = max(min(round(score), 3), 0)
        return self._scored(final_score, conclusion, evidence)


TRACING_ANALYZERS = [
    TracePropagationAnalyzer(),
    TraceSamplingAnalyzer(),
    TraceVisualizationAnalyzer(),
    TraceCoverageAnalyzer(),
]
