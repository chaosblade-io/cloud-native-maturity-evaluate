"""
Serverless 维度 - 函数即服务 (FaaS) 分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)               | 分值  | 评分标准                                                       |
| faas_coverage              | 0-12  | 业务渗透率：高(12)/中(8)/低(4)/无(0)                           |
| faas_trigger_diversity     | 0-8   | 触发器多样性：>=5种(8分)/3-4种(5分)/1-2种(2分)                 |
| faas_runtime_flex          | 0-6   | 运行时灵活性：>=4种语言或自定义镜像(6分)/2-3种(4分)/1种(1分)   |
| faas_cold_start            | 6     | 冷启动优化：预留实例、快照恢复或轻量级运行时优化               |
| faas_observability         | 5     | 函数可观测性：独立的日志、指标和追踪，关联到调用链             |
| faas_governance            | 5     | 治理与版本：版本控制、别名管理及灰度发布策略                   |
"""
from ...core.analyzer import Analyzer, ScoreResult
from ...schema.fc import (
    FcFunctionRecord, FcVersionRecord, FcAliasRecord,
    FcColdStartMetricRecord, FcFunctionStatisticsRecord
)


class FaasCoverageAnalyzer(Analyzer):
    """
    业务渗透率分析器
    
    评估标准：
    - 高 (12): FaaS 处理的请求量占总请求量 > 40% 或承载核心链路
    - 中 (8): 占比 10%-40%
    - 低 (4): < 10%
    - 无 (0): 0%
    
    数据来源：
    - FC API：ListFunctions，统计函数总数
    - GetFunctionStatistics，获取函数调用量
    """

    def key(self) -> str:
        return "faas_coverage"

    def dimension(self) -> str:
        return "Serverless"

    def category(self) -> str:
        return "函数即服务"

    def max_score(self) -> int:
        return 12

    def required_data(self) -> list[str]:
        return ["fc.function.list", "fc.function.statistics"]

    def analyze(self, store) -> ScoreResult:
        functions: list[FcFunctionRecord] = store.get("fc.function.list") or []

        if not functions:
            return self._scored(0, "未使用函数计算：尚未采用 FaaS 架构", ["未检测到 FC 函数配置"])

        evidence: list[str] = [f"函数数量: {len(functions)}"]
        score = 0.0

        # --- 1. 函数数量规模评分 (0-4 分) ---
        func_count = len(functions)
        if func_count >= 50:
            score += 4.0
            evidence.append("✓ 函数数量庞大，FaaS 已在多业务场景广泛应用")
        elif func_count >= 20:
            score += 3.0
            evidence.append("✓ 函数数量充足，FaaS 应用较为广泛")
        elif func_count >= 10:
            score += 2.0
            evidence.append("函数数量较多，FaaS 应用初具规模")
        elif func_count >= 3:
            score += 1.0
            evidence.append("函数数量有限，FaaS 处于试点阶段")
        else:
            score += 0.5
            evidence.append("函数数量极少，FaaS 刚起步")

        # --- 2. 调用量活跃度评分 (0-4 分) ---
        if store.available("fc.function.statistics"):
            stats: list[FcFunctionStatisticsRecord] = store.get("fc.function.statistics") or []
            if stats:
                total_invocations = sum(s.invocation_count for s in stats)
                evidence.append(f"总调用量: {total_invocations}")

                if total_invocations >= 1000000:
                    score += 4.0
                    evidence.append("✓ 调用量极高，FaaS 承载核心业务流量")
                elif total_invocations >= 100000:
                    score += 3.0
                    evidence.append("✓ 调用量高，FaaS 业务渗透率高")
                elif total_invocations >= 10000:
                    score += 2.0
                    evidence.append("调用量中等，FaaS 已有一定业务渗透")
                elif total_invocations >= 1000:
                    score += 1.0
                    evidence.append("调用量较低，FaaS 业务渗透有限")
                else:
                    evidence.append("调用量极少，函数可能处于测试或低频场景")
            else:
                evidence.append("ℹ️ 未获取到函数调用统计数据")
        else:
            evidence.append("ℹ️ 无函数调用统计数据，仅按函数数量评估")

        # --- 3. 函数活跃度分布评分 (0-2 分) ---
        if store.available("fc.function.statistics"):
            stats: list[FcFunctionStatisticsRecord] = store.get("fc.function.statistics") or []
            if stats:
                active_functions = [s for s in stats if s.invocation_count > 100]
                if active_functions:
                    active_ratio = len(active_functions) / len(stats)
                    evidence.append(f"活跃函数比例: {active_ratio:.0%} ({len(active_functions)}/{len(stats)})")
                    if active_ratio >= 0.7:
                        score += 2.0
                        evidence.append("✓ 绝大多数函数处于活跃状态，资源利用率高")
                    elif active_ratio >= 0.4:
                        score += 1.0
                        evidence.append("部分函数活跃，存在一定僵尸函数")
                    else:
                        evidence.append("活跃函数比例低，存在较多僵尸函数")
                else:
                    evidence.append("⚠️ 无活跃函数，可能存在大量僵尸函数")

        # --- 4. 高级特性使用情况 (0-2 分) ---
        advanced_features = 0
        reserved_funcs = [f for f in functions if f.reserved_instances > 0]
        container_funcs = [f for f in functions if f.custom_container_config]
        layer_funcs = [f for f in functions if f.layers]

        if reserved_funcs:
            advanced_features += 1
            evidence.append(f"✓ {len(reserved_funcs)} 个函数配置预留实例，冷启动优化到位")
        if container_funcs:
            advanced_features += 1
            evidence.append(f"✓ {len(container_funcs)} 个函数使用自定义容器")
        if layer_funcs:
            advanced_features += 1
            evidence.append(f"✓ {len(layer_funcs)} 个函数使用 Layer 管理依赖")

        if advanced_features >= 2:
            score += 2.0
        elif advanced_features == 1:
            score += 1.0

        final_score = max(min(int(round(score)), 12), 0)

        if final_score >= 10:
            status_msg = "FaaS 业务渗透率高：函数数量多、调用量大且使用高级特性"
        elif final_score >= 7:
            status_msg = "FaaS 业务渗透率较高：函数规模较大且有一定业务流量"
        elif final_score >= 4:
            status_msg = "FaaS 业务渗透率中等：函数数量和调用量处于中等水平"
        elif final_score >= 2:
            status_msg = "FaaS 业务渗透率较低：函数数量有限或调用量较少"
        else:
            status_msg = "FaaS 业务渗透率低：尚未大规模采用函数计算"

        return self._scored(final_score, status_msg, evidence)


class FaasTriggerDiversityAnalyzer(Analyzer):
    """
    触发器多样性分析器
    
    评估标准：
    - 覆盖 >=5 种类型 (HTTP/事件/定时/消息/流) 得 8 分
    - 覆盖 3-4 种得 5 分
    - 仅 1-2 种 (通常仅 HTTP) 得 2 分
    
    数据来源：
    - FC API：ListTriggers，枚举所有函数的触发器类型（HTTP/OSS/MQ/Timer/EventBridge 等）
    """

    def key(self) -> str:
        return "faas_trigger_diversity"

    def dimension(self) -> str:
        return "Serverless"

    def category(self) -> str:
        return "函数即服务"

    def max_score(self) -> int:
        return 8

    def required_data(self) -> list[str]:
        return ["fc.function.list"]

    def analyze(self, store) -> ScoreResult:
        functions: list[FcFunctionRecord] = store.get("fc.function.list") or []

        if not functions:
            return self._scored(0, "未使用函数计算：尚未采用 FaaS 架构", ["未检测到 FC 函数配置"])

        trigger_types: set[str] = set()
        total_triggers = 0

        for f in functions:
            if f.triggers:
                for t in f.triggers:
                    t_type = t.get("type", "").lower()
                    if t_type:
                        trigger_types.add(t_type)
                        total_triggers += 1

        type_count = len(trigger_types)

        if not trigger_types:
            return self._scored(1, "函数未配置触发器：函数无法被实际调用",
                                [f"函数数量: {len(functions)}，但均未配置触发器"])

        evidence: list[str] = [
            f"函数数量: {len(functions)}",
            f"触发器类型: {', '.join(trigger_types)} ({type_count}种)",
            f"触发器总数: {total_triggers} 个"
        ]

        score = 0.0

        # --- 1. 触发器类型多样性 (0-4 分) ---
        if type_count >= 5:
            score += 4.0
            evidence.append("✓ 触发器类型非常丰富 (>=5 种)，多个事件源接入函数")
        elif type_count >= 3:
            score += 2.5
            evidence.append("✓ 触发器类型丰富 (3-4 种)")
        elif type_count == 2:
            score += 1.5
            evidence.append("触发器类型有限 (2 种)")
        else:
            score += 0.5
            evidence.append("触发器类型单一 (仅 1 种)")

        # --- 2. 触发器覆盖率 (0-2 分) ---
        functions_with_triggers = len([f for f in functions if f.triggers])
        trigger_coverage = functions_with_triggers / len(functions) if len(functions) > 0 else 0
        evidence.append(f"触发器覆盖率: {trigger_coverage:.0%} ({functions_with_triggers}/{len(functions)})")

        if trigger_coverage >= 0.8:
            score += 2.0
            evidence.append("✓ 绝大多数函数配置了触发器")
        elif trigger_coverage >= 0.5:
            score += 1.0
            evidence.append("部分函数配置了触发器")
        elif trigger_coverage > 0:
            score += 0.5
            evidence.append("仅少数函数配置了触发器")
        else:
            evidence.append("⚠️ 无函数配置触发器")

        # --- 3. 核心触发器类型覆盖 (0-2 分) ---
        core_types = {"http", "timer", "oss", "mq", "eventbridge", "api", "tablestore", "cdn"}
        core_covered = sum(1 for t_type in trigger_types if t_type in core_types)

        if core_covered >= 4:
            score += 2.0
            evidence.append(f"✓ 核心触发器类型覆盖全面 ({core_covered}/8 种)")
        elif core_covered >= 2:
            score += 1.0
            evidence.append("核心触发器类型部分覆盖")
        else:
            evidence.append("核心触发器类型覆盖有限")

        final_score = max(min(int(round(score)), 8), 0)

        if final_score >= 7:
            status_msg = "触发器配置完善：类型丰富、覆盖率高、核心类型齐全"
        elif final_score >= 5:
            status_msg = "触发器配置良好：类型较丰富，覆盖率中等"
        elif final_score >= 3:
            status_msg = "触发器配置基础：类型有限，覆盖率较低"
        elif final_score >= 1:
            status_msg = "触发器配置较少：仅有少量触发器"
        else:
            status_msg = "触发器配置有限：类型单一，覆盖率低"

        return self._scored(final_score, status_msg, evidence)


class FaasRuntimeFlexAnalyzer(Analyzer):
    """
    运行时灵活性分析器
    
    评估标准：
    - 支持 >=4 种主流语言或支持自定义容器镜像得 6 分
    - 支持 2-3 种得 4 分
    - 仅支持 1 种得 1 分
    
    数据来源：
    - FC API：函数配置中的 runtime 字段，统计所有使用的运行时语言种类
    """

    def key(self) -> str:
        return "faas_runtime_flex"

    def dimension(self) -> str:
        return "Serverless"

    def category(self) -> str:
        return "函数即服务"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return ["fc.function.list"]

    def analyze(self, store) -> ScoreResult:
        functions: list[FcFunctionRecord] = store.get("fc.function.list")

        if not functions:
            return self._not_evaluated("未使用函数计算")

        runtimes = set(f.runtime for f in functions if f.runtime)

        custom_image = any(f.custom_container_config for f in functions)

        evidence = [f"运行时类型: {', '.join(runtimes) if runtimes else '无'}"]

        if custom_image:
            evidence.append("✓ 支持自定义容器镜像")

        runtime_count = len(runtimes)

        if runtime_count >= 4:
            score = 5
            description = "运行时灵活性高 (>=4种语言)"
        elif runtime_count == 3:
            score = 4
            description = "运行时灵活性中高 (3种语言)"
        elif runtime_count == 2:
            score = 2
            description = "运行时灵活性中 (2种语言)"
        elif runtime_count == 1:
            score = 1
            description = "运行时灵活性低 (仅1种语言)"
        else:
            return self._not_scored("未检测到运行时配置", evidence)

        if custom_image:
            score = min(6, score + 1)
            evidence.append("✓ 支持自定义容器镜像 (+1分)")
            if score == 6:
                description = "运行时灵活性高 (>=4种语言或自定义镜像)"

        return self._scored(score, description, evidence)


class FaasColdStartAnalyzer(Analyzer):
    """
    冷启动优化分析器
    
    评估标准：是否实施了预留实例 (Provisioned Concurrency)、快照恢复或轻量级运行时优化，
    将 P99 冷启动延迟控制在业务可接受范围 (如 < 500ms)
    
    数据来源：
    - FC 监控指标：FunctionColdStartDuration，统计 P99 冷启动延迟
    - FC API：GetFunctionConcurrency，检查是否配置了预留并发
    """

    def key(self) -> str:
        return "faas_cold_start"

    def dimension(self) -> str:
        return "Serverless"

    def category(self) -> str:
        return "函数即服务"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return ["fc.function.list", "fc.cold_start_metrics"]

    def analyze(self, store) -> ScoreResult:
        functions: list[FcFunctionRecord] = store.get("fc.function.list")

        if not functions:
            return self._not_evaluated("未使用函数计算")

        evidence = []

        # --- 配置侧评分 (0-2分) ---
        config_score = 0
        reserved = [f for f in functions if f.reserved_instances > 0]
        if reserved:
            config_score = 2
            evidence.append(f"✓ 已配置预留实例: {len(reserved)}/{len(functions)} 个函数")
        else:
            evidence.append("✗ 未配置预留实例")

        # --- 效果侧评分 (0-4分) ---
        metric_score = 0
        if store.available("fc.cold_start_metrics"):
            metrics: list[FcColdStartMetricRecord] = store.get("fc.cold_start_metrics")
            if metrics:
                p99_cold_start = max(m.p99_cold_start_ms for m in metrics)
                avg_cold_start = sum(m.avg_cold_start_ms for m in metrics) / len(metrics)
                evidence.append(f"P99 冷启动: {p99_cold_start:.0f}ms, 平均: {avg_cold_start:.0f}ms")

                if p99_cold_start < 500:
                    metric_score = 4
                    evidence.append("✓ P99 冷启动 < 500ms，优化效果显著")
                elif p99_cold_start < 1000:
                    metric_score = 3
                    evidence.append("P99 冷启动 500-1000ms，优化效果良好")
                elif p99_cold_start < 2000:
                    metric_score = 2
                    evidence.append("P99 冷启动 1000-2000ms，优化效果一般")
                else:
                    metric_score = 1
                    evidence.append("✗ P99 冷启动 >= 2000ms，优化效果不足")

        else:
            evidence.append("冷启动指标不可用，无法评估实际优化效果")

        score = min(6, config_score + metric_score)

        if score >= 5:
            return self._scored(score, "冷启动优化完善（配置+效果双达标）", evidence)
        elif score >= 3:
            return self._scored(score, "冷启动优化基本满足", evidence)
        elif score > 0:
            return self._scored(score, "冷启动优化有待改进", evidence)
        else:
            return self._not_scored("未实施冷启动优化措施", evidence)


class FaasObservabilityAnalyzer(Analyzer):
    """
    函数可观测性分析器
    
    评估标准：是否为每个函数配置了独立的日志、指标和追踪，且能关联到调用链
    
    数据来源：
    - FC API：检查函数是否启用了日志投递（SLS）和 Trace 投递（ARMS）
    - ARMS：检查是否能查询到该函数的 Trace 数据
    """

    def key(self) -> str:
        return "faas_observability"

    def dimension(self) -> str:
        return "Serverless"

    def category(self) -> str:
        return "函数即服务"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["fc.function.list"]

    def analyze(self, store) -> ScoreResult:
        functions: list[FcFunctionRecord] = store.get("fc.function.list")

        if not functions:
            return self._not_evaluated("未使用函数计算，无法评估可观测性")

        evidence = []
        score = 0.0
        total_count = len(functions)

        # --- 1. 检查日志配置 (Logging) - 权重 0-2分 ---
        valid_log_funcs = []
        for f in functions:
            cfg = f.log_config
            if cfg:
                if cfg.get('project') and cfg.get('logstore'):
                    valid_log_funcs.append(f)

        log_ratio = len(valid_log_funcs) / total_count if total_count else 0
        evidence.append(f"日志配置覆盖率: {len(valid_log_funcs)}/{total_count} ({log_ratio:.1%})")

        log_score = 0.0
        if log_ratio >= 0.95:
            log_score = 2.0
            evidence.append("✓ 日志近乎全覆盖 (2.0/2.0)")
        elif log_ratio >= 0.8:
            log_score = 1.5
            evidence.append("ℹ️ 大部分函数已配置日志 (1.5/2.0)")
        elif log_ratio >= 0.5:
            log_score = 1.0
            evidence.append("⚠️ 仅半数函数存在日志 (1.0/2.0)")
        elif log_ratio > 0:
            log_score = 0.5
            evidence.append("⚠️ 日志配置零星 (0.5/2.0)")
        else:
            evidence.append("❌ 日志配置缺失 (0/2.0)")

        score += log_score

        # --- 2. 检查链路追踪配置 (Tracing) - 权重 0-2分 ---
        valid_trace_funcs = []
        for f in functions:
            cfg = f.trace_config
            if cfg:
                trace_type = cfg.get('type')
                if trace_type and str(trace_type).lower() not in ["none", "disabled", "off", "null", ""]:
                    valid_trace_funcs.append(f)

        trace_ratio = len(valid_trace_funcs) / total_count if total_count else 0
        evidence.append(f"链路追踪覆盖率: {len(valid_trace_funcs)}/{total_count} ({trace_ratio:.1%})")

        trace_score = 0.0
        if trace_ratio >= 0.95:
            trace_score = 2.0
            evidence.append("✓ 追踪近乎全覆盖 (2.0/2.0)")
        elif trace_ratio >= 0.8:
            trace_score = 1.5
            evidence.append("ℹ️ 大部分函数已配置追踪 (1.5/2.0)")
        elif trace_ratio >= 0.5:
            trace_score = 1.0
            evidence.append("⚠️ 仅半数函数存在追踪 (1.0/2.0)")
        elif trace_ratio > 0:
            trace_score = 0.5
            evidence.append("⚠️ 追踪配置零星 (0.5/2.0)")
        else:
            evidence.append("❌ 追踪配置缺失 (0/2.0)")

        score += trace_score

        # --- 3. 检查日志与追踪的关联性 (Correlation) - 权重 0-1分 ---
        both_configured = [f for f in functions if f in valid_log_funcs and f in valid_trace_funcs]
        correlation_ratio = len(both_configured) / total_count if total_count else 0
        evidence.append(f"日志+追踪双覆盖: {len(both_configured)}/{total_count} ({correlation_ratio:.1%})")

        correlation_score = 0.0
        if correlation_ratio >= 0.8:
            correlation_score = 1.0
            evidence.append("✓ 可观测性数据关联性强，支持调用链追踪 (1.0/1.0)")
        elif correlation_ratio >= 0.5:
            correlation_score = 0.5
            evidence.append("ℹ️ 部分函数可观测性数据可关联 (0.5/1.0)")
        else:
            evidence.append("❌ 可观测性数据割裂，难以关联调用链 (0/1.0)")

        score += correlation_score

        final_score = round(score)

        if final_score >= 5:
            conclusion = "可观测性体系完善：全链路日志+追踪无死角，支持调用链关联"
        elif final_score >= 4:
            conclusion = "可观测性良好：核心链路已覆盖，建议消除剩余盲区"
        elif final_score >= 2:
            conclusion = "可观测性基础可用：存在明显盲区，难以应对复杂故障"
        elif final_score > 0:
            conclusion = "可观测性薄弱：配置零散，缺乏系统性"
        else:
            return self._not_scored("函数可观测性缺失：无法有效监控和排查故障", evidence)

        return self._scored(final_score, conclusion, evidence)


class FaasGovernanceAnalyzer(Analyzer):
    """
    治理与版本分析器
    
    评估标准：是否实施了函数版本控制、别名管理 (Alias) 及灰度发布策略
    
    数据来源：
    - FC API：ListVersions、ListAliases，检查函数是否有多版本和别名配置
    """

    def key(self) -> str:
        return "faas_governance"

    def dimension(self) -> str:
        return "Serverless"

    def category(self) -> str:
        return "函数即服务"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["fc.version.list"]

    def optional_data(self) -> list[str]:
        return ["fc.alias.list"]

    def analyze(self, store) -> ScoreResult:
        versions: list[FcVersionRecord] = store.get("fc.version.list")

        if not versions:
            return self._not_scored("未配置函数版本管理：所有调用可能直接指向 LATEST，存在高风险", [])

        evidence = []
        score = 0.0

        functions_with_versions = set(v.function_name for v in versions)
        evidence.append(f"纳管函数数：{len(functions_with_versions)}")

        func_version_counts = {}
        for v in versions:
            fname = v.function_name
            func_version_counts[fname] = func_version_counts.get(fname, 0) + 1

        stacked_funcs = [f for f, count in func_version_counts.items() if count > 10]
        avg_versions = sum(func_version_counts.values()) / len(func_version_counts) if func_version_counts else 0
        evidence.append(f"平均版本数：{avg_versions:.1f}")

        # --- 1. 版本健康度 (0-1分) ---
        if not stacked_funcs:
            score += 1.0
            evidence.append("✓ 版本数量合理，无明显堆积 (1.0/1.0)")
        elif len(stacked_funcs) < len(functions_with_versions) * 0.5:
            score += 0.5
            evidence.append(f"⚠️ 发现 {len(stacked_funcs)} 个函数版本堆积 (>10 个)，建议配置版本保留策略 (0.5/1.0)")
        else:
            evidence.append(f"❌ 大量函数版本堆积 ({len(stacked_funcs)} 个)，版本管理混乱 (0/1.0)")

        # --- 2. 生产隔离 (0-2分) ---
        if store.available("fc.alias.list"):
            aliases: list[FcAliasRecord] = store.get("fc.alias.list")

            prod_keywords = ["prod", "prd", "production", "release", "stable", "online", "live"]
            prod_aliases = [a for a in aliases
                            if any(k in a.alias_name.lower() for k in prod_keywords)]

            if prod_aliases:
                score += 2.0
                evidence.append(f"✓ 生产隔离良好：发现 {len(prod_aliases)} 个标准生产环境别名 (2.0/2.0)")
            elif aliases:
                score += 1.0
                evidence.append("ℹ️ 已配置别名，但未发现标准生产别名 (prod/prd/release)，可能存在环境混用风险 (1.0/2.0)")
            else:
                evidence.append("❌ 未发现别名配置：流量可能直接指向 LATEST 或不稳定版本 (0/2.0)")
        else:
            evidence.append("❌ 未获取到别名列表，无法确认生产隔离情况 (0/2.0)")

        # --- 3. 灰度发布能力 (0-2分) ---
        if store.available("fc.alias.list"):
            aliases: list[FcAliasRecord] = store.get("fc.alias.list")

            active_canary_aliases = []
            static_split_aliases = []

            for a in aliases:
                weights_dict = a.additional_version_weight

                if isinstance(weights_dict, dict) and weights_dict:
                    w_values = []
                    for v_key, w_val in weights_dict.items():
                        try:
                            w_float = float(w_val)
                            if 0.0 <= w_float <= 1.0 and w_float not in (0.0, 1.0):
                                w_values.append(w_float * 100)
                            else:
                                w_values.append(w_float)
                        except (ValueError, TypeError):
                            continue

                    if not w_values:
                        continue

                    has_active_canary = any(0 < w < 100 for w in w_values)
                    if not has_active_canary and len(w_values) > 1 and not any(w == 100 for w in w_values):
                        has_active_canary = True

                    if has_active_canary:
                        active_canary_aliases.append(a)
                    elif all(w == 0 or w == 100 for w in w_values):
                        static_split_aliases.append(a)

            total_aliases = len(aliases) if aliases else 0
            if total_aliases > 0 and active_canary_aliases:
                canary_ratio = len(active_canary_aliases) / total_aliases
                if canary_ratio >= 0.5:
                    score += 2.0
                    evidence.append(
                        f"✓ 灰度发布广泛实施：{len(active_canary_aliases)}/{total_aliases} 个别名处于流量分割状态 (2.0/2.0)")
                elif canary_ratio >= 0.2:
                    score += 1.5
                    evidence.append(
                        f"✓ 灰度发布部分实施：{len(active_canary_aliases)}/{total_aliases} 个别名处于流量分割状态 (1.5/2.0)")
                else:
                    score += 1.0
                    evidence.append(
                        f"ℹ️ 灰度发布试点：{len(active_canary_aliases)}/{total_aliases} 个别名处于流量分割状态 (1.0/2.0)")
            elif static_split_aliases:
                score += 0.5
                evidence.append(
                    f"ℹ️ 具备灰度配置能力：{len(static_split_aliases)} 个别名配置了多版本权重（当前为全量/零量）(0.5/2.0)")
            elif aliases:
                evidence.append("ℹ️ 别名均为单一版本指向，未利用权重进行流量控制 (0/2.0)")

        final_score = min(5, round(score))

        if final_score >= 5:
            conclusion = "函数治理卓越：生产隔离清晰、版本控制合理、正在实施动态灰度"
        elif final_score >= 4:
            conclusion = "函数治理良好：具备生产隔离和版本管理，建议引入动态灰度提升发布平滑度"
        elif final_score >= 3:
            conclusion = "函数治理基础：有版本和别名概念，但缺乏明确的生产环境规范或流量控制"
        elif final_score > 0:
            if stacked_funcs:
                conclusion = "函数治理混乱：版本堆积严重，缺乏清理策略和规范的生产隔离"
            else:
                conclusion = "函数治理薄弱：仅有版本记录，未形成有效的发布管理体系"
        else:
            return self._not_scored("无有效函数版本管理数据", evidence)

        return self._scored(final_score, conclusion, evidence)


FAAS_ANALYZERS = [
    FaasCoverageAnalyzer(),
    FaasTriggerDiversityAnalyzer(),
    FaasRuntimeFlexAnalyzer(),
    FaasColdStartAnalyzer(),
    FaasObservabilityAnalyzer(),
    FaasGovernanceAnalyzer(),
]
