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
        functions: list[FcFunctionRecord] = store.get("fc.function.list")

        if not functions:
            return self._not_scored("未使用函数计算", [])

        evidence = [f"函数数量: {len(functions)}"]

        # 检查函数统计数据
        if store.available("fc.function.statistics"):
            stats: list[FcFunctionStatisticsRecord] = store.get("fc.function.statistics")
            if stats:
                total_invocations = sum(s.invocation_count for s in stats)
                evidence.append(f"总调用量: {total_invocations}")

                # 根据调用量判断渗透率
                if total_invocations >= 100000:
                    return self._scored(12, "FaaS 业务渗透率高：承载大量请求", evidence)
                elif total_invocations >= 10000:
                    return self._scored(8, "FaaS 业务渗透率中", evidence)
                elif total_invocations >= 1000:
                    return self._scored(4, "FaaS 业务渗透率低", evidence)

        # 无统计数据时，根据函数数量估算
        if len(functions) >= 20:
            return self._scored(12, "FaaS 函数数量充足，渗透率高", evidence)
        elif len(functions) >= 10:
            return self._scored(8, "FaaS 函数数量较多，渗透率中", evidence)
        elif len(functions) >= 3:
            return self._scored(4, "FaaS 函数数量有限，渗透率低", evidence)
        else:
            return self._scored(2, "FaaS 使用极少", evidence)


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
        functions: list[FcFunctionRecord] = store.get("fc.function.list")

        if not functions:
            return self._not_evaluated("未使用函数计算")

        # 收集所有触发器类型
        trigger_types = set()

        # 从函数配置中获取触发器
        for f in functions:
            if f.triggers:
                for t in f.triggers:
                    t_type = t.get("triggerType", "").lower()
                    if t_type:
                        trigger_types.add(t_type)

        if not trigger_types:
            return self._not_scored("函数未配置触发器", [])

        evidence = [f"触发器类型: {', '.join(trigger_types)}"]
        type_count = len(trigger_types)

        if type_count >= 5:
            return self._scored(8, "触发器类型非常丰富 (>=5种)", evidence)
        elif type_count >= 3:
            return self._scored(5, "触发器类型丰富 (3-4种)", evidence)
        else:
            return self._scored(2, "触发器类型有限 (1-2种)", evidence)


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

        # 统计运行时类型
        runtimes = set(f.runtime for f in functions if f.runtime)

        # 检查是否有自定义容器镜像
        custom_image = any(f.custom_container_config for f in functions)

        evidence = [f"运行时类型: {', '.join(runtimes) if runtimes else '无'}"]

        if custom_image:
            evidence.append("✓ 支持自定义容器镜像")

        runtime_count = len(runtimes)

        if runtime_count >= 4 or custom_image:
            return self._scored(6, "运行时灵活性高 (>=4种语言或自定义镜像)", evidence)
        elif runtime_count >= 2:
            return self._scored(4, "运行时灵活性中 (2-3种语言)", evidence)
        elif runtime_count == 1:
            return self._scored(1, "运行时灵活性低 (仅1种语言)", evidence)
        else:
            return self._not_scored("未检测到运行时配置", evidence)


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
        score = 0

        # 检查预留实例配置
        reserved = [f for f in functions if f.reserved_instances > 0]
        if reserved:
            score += 3
            evidence.append(f"✓ 预留实例函数: {len(reserved)} 个")

        # 检查冷启动指标
        if store.available("fc.cold_start_metrics"):
            metrics: list[FcColdStartMetricRecord] = store.get("fc.cold_start_metrics")
            if metrics:
                p99_cold_start = max(m.p99_cold_start_ms for m in metrics)
                avg_cold_start = sum(m.avg_cold_start_ms for m in metrics) / len(metrics)

                evidence.append(f"P99 冷启动: {p99_cold_start:.0f}ms")
                evidence.append(f"平均冷启动: {avg_cold_start:.0f}ms")

                if p99_cold_start < 500:
                    score += 3
                    evidence.append("✓ P99 冷启动 < 500ms")
                elif p99_cold_start < 1000:
                    score += 2
                elif p99_cold_start < 2000:
                    score += 1
        else:
            # 无冷启动指标，根据配置估算
            if reserved:
                score += 2  # 有预留实例通常冷启动较好

        if score >= 5:
            return self._scored(6, "冷启动优化完善", evidence)
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
        max_score = 5.0  # 满分调整为 5 分

        total_count = len(functions)

        # --- 1. 检查日志配置 (Logging) - 权重 2.5 分 ---
        valid_log_funcs = []
        for f in functions:
            cfg = f.log_config
            if cfg:
                is_enabled = False
                # 默认开启，除非显式关闭，且必须有 project
                if cfg.get('enable_instance_metrics', True) is not False and cfg.get('project'):
                    is_enabled = True

                if is_enabled:
                    valid_log_funcs.append(f)

        log_ratio = len(valid_log_funcs) / total_count if total_count else 0
        evidence.append(f"日志配置覆盖率: {len(valid_log_funcs)}/{total_count} ({log_ratio:.1%})")

        log_score = 0.0
        if log_ratio >= 0.95:
            log_score = 2.5
            evidence.append("✓ 日志近乎全覆盖 (2.5/2.5)")
        elif log_ratio >= 0.8:
            log_score = 2.0
            evidence.append("ℹ️ 大部分函数已配置日志 (2.0/2.5)")
        elif log_ratio >= 0.5:
            log_score = 1.5
            evidence.append("⚠️ 仅半数函数存在日志 (1.5/2.5)")
        else:
            log_score = 0.0
            evidence.append("❌ 日志配置严重缺失 (0/2.5)")

        score += log_score

        # --- 2. 检查链路追踪配置 (Tracing) - 权重 2.5 分 ---
        valid_trace_funcs = []
        for f in functions:
            cfg = f.trace_config
            if cfg:
                is_enabled = False
                trace_type = cfg.get('type')

                if trace_type and str(trace_type).lower() not in ["none", "disabled", "off", "null"]:
                    is_enabled = True

                if is_enabled:
                    valid_trace_funcs.append(f)

        trace_ratio = len(valid_trace_funcs) / total_count if total_count else 0
        evidence.append(f"链路追踪覆盖率: {len(valid_trace_funcs)}/{total_count} ({trace_ratio:.1%})")

        trace_score = 0.0
        if trace_ratio >= 0.95:
            trace_score = 2.5
            evidence.append("✓ 追踪近乎全覆盖 (2.5/2.5)")
        elif trace_ratio >= 0.8:
            trace_score = 2.0
            evidence.append("ℹ️ 大部分函数已配置追踪 (2.0/2.5)")
        elif trace_ratio >= 0.5:
            trace_score = 1.5
            evidence.append("⚠️ 仅半数函数存在追踪 (1.5/2.5)")
        else:
            trace_score = 0.0
            evidence.append("❌ 追踪配置严重缺失 (0/2.5)")

        score += trace_score

        if score >= 4.5:
            conclusion = "可观测性体系完善：全链路日志+追踪无死角"
        elif score >= 3.5:
            conclusion = "可观测性良好：核心链路已覆盖，建议消除剩余盲区"
        elif score >= 2.0:
            conclusion = "可观测性基础可用：存在明显盲区，难以应对复杂故障"
        elif score > 0:
            conclusion = "可观测性薄弱：配置零散，缺乏系统性"
        else:
            return self._not_scored("函数可观测性缺失：无法有效监控和排查故障", evidence)

        final_score = round(score, 1)
        return self._scored(int(final_score), conclusion, evidence)

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
        max_score = 5.0

        functions_with_versions = set(v.function_name for v in versions)
        evidence.append(f"纳管函数数：{len(functions_with_versions)}")

        func_version_counts = {}
        for v in versions:
            fname = v.function_name
            func_version_counts[fname] = func_version_counts.get(fname, 0) + 1

        stacked_funcs = [f for f, count in func_version_counts.items() if count > 10]
        avg_versions = sum(func_version_counts.values()) / len(func_version_counts) if func_version_counts else 0

        evidence.append(f"平均版本数：{avg_versions:.1f}")

        version_score = 0.0
        if stacked_funcs:
            evidence.append(f"⚠️ 发现 {len(stacked_funcs)} 个函数版本堆积 (>10 个)，建议配置版本保留策略")
            max_score = 3.0
        else:
            version_score = 1.0
            evidence.append("✓ 版本数量合理，无明显堆积")

        score += version_score

        has_prod_isolation = False
        isolation_score = 0.0

        if store.available("fc.alias.list"):
            aliases: list[FcAliasRecord] = store.get("fc.alias.list")

            prod_keywords = ["prod", "production", "release", "stable", "online"]
            prod_aliases = [a for a in aliases
                            if any(k in a.alias_name.lower() for k in prod_keywords)]

            if prod_aliases:
                has_prod_isolation = True
                isolation_score = 2.0
                evidence.append(f"✓ 生产隔离良好：发现 {len(prod_aliases)} 个标准生产环境别名")
            else:
                if aliases:
                    isolation_score = 1.0
                    evidence.append("ℹ️ 已配置别名，但未发现标准生产别名 (prod/release)，可能存在环境混用风险")
                else:
                    evidence.append("❌ 未发现别名配置：流量可能直接指向 LATEST 或不稳定版本")
        else:
            evidence.append("❌ 未获取到别名列表，无法确认生产隔离情况")

        score += isolation_score

        if not has_prod_isolation:
            if max_score > 4.0:
                max_score = 4.0

        canary_score = 0.0
        active_canary_count = 0
        static_split_count = 0

        if store.available("fc.alias.list"):
            aliases: list[FcAliasRecord] = store.get("fc.alias.list")

            for a in aliases:
                weights_dict = getattr(a, 'additional_version_weights', None)

                if isinstance(weights_dict, dict) and weights_dict:
                    w_values = []
                    for v_key, w_val in weights_dict.items():
                        try:
                            w_float = float(w_val)
                            if 0.0 <= w_float <= 1.0 and w_float != 0 and w_float != 1:
                                w_values.append(w_float * 100)
                            else:
                                w_values.append(w_float)
                        except (ValueError, TypeError):
                            continue

                    if not w_values:
                        continue

                    has_active_canary = False
                    is_static = True

                    for w in w_values:
                        if 0 < w < 100:
                            has_active_canary = True
                            break

                    if len(w_values) > 1 and not any(w == 100 for w in w_values):
                        has_active_canary = True

                    if has_active_canary:
                        active_canary_count += 1
                    else:
                        if all(w == 0 or w == 100 for w in w_values):
                            static_split_count += 1

            if active_canary_count > 0:
                canary_score = 2.0
                evidence.append(f"✓ 正在进行灰度发布：{active_canary_count} 个别名处于流量分割状态")
            elif static_split_count > 0:
                canary_score = 1.0
                evidence.append(f"ℹ️ 具备灰度配置能力：{static_split_count} 个别名配置了多版本权重 (但当前为全量/零量)")
            else:
                if aliases:
                    evidence.append("ℹ️ 别名均为单一版本指向或未利用权重进行流量控制")

        score += canary_score

        final_score = min(score, max_score)

        if final_score >= 4.5:
            conclusion = "函数治理卓越：生产隔离清晰、版本控制合理、正在实施动态灰度"
        elif final_score >= 3.5:
            conclusion = "函数治理良好：具备生产隔离和版本管理，建议引入动态灰度提升发布平滑度"
        elif final_score >= 2.5:
            conclusion = "函数治理基础：有版本和别名概念，但缺乏明确的生产环境规范或流量控制"
        elif final_score > 0:
            if stacked_funcs:
                conclusion = "函数治理混乱：版本堆积严重，缺乏清理策略和规范的生产隔离"
            else:
                conclusion = "函数治理薄弱：仅有版本记录，未形成有效的发布管理体系"
        else:
            return self._not_scored("无有效函数版本管理数据", evidence)

        return self._scored(int(final_score), conclusion, evidence)

# 导出所有分析器
FAAS_ANALYZERS = [
    FaasCoverageAnalyzer(),
    FaasTriggerDiversityAnalyzer(),
    FaasRuntimeFlexAnalyzer(),
    FaasColdStartAnalyzer(),
    FaasObservabilityAnalyzer(),
    FaasGovernanceAnalyzer(),
]
