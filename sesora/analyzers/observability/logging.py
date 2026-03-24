"""
Observability 维度 - 日志管理能力 (Logging) 分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)             | 分值 | 评分标准                                                       |
| log_centralized          | 6    | 集中式收集：所有节点/容器日志自动采集并汇聚到中央存储           |
| log_structure            | 0-6  | 日志结构化：JSON(2分) + 标准字段(1分) + TraceID注入率>90%(3分) |
| log_analysis             | 5    | 日志分析能力：实时查询、聚合分析、异常模式识别                 |
| log_retention_policy     | 4    | 保留策略：分层存储策略 (热/温/冷数据) 及自动过期机制           |
| log_context              | 4    | 上下文关联：日志能通过 TraceID 与 Tracing 系统关联             |
"""
from ...core.analyzer import Analyzer, ScoreResult
from ...schema.sls import (
    SlsLogstoreRecord, SlsIndexConfigRecord,
    SlsLogStructureAnalysisRecord, SlsArchiveConfigRecord
)
from ...schema.apm import ApmServiceRecord


class LogCentralizedAnalyzer(Analyzer):
    """
    集中式收集分析器
    
    评估标准：所有节点/容器的日志是否自动采集并汇聚到中央存储，无需登录机器查看
    
    数据来源：
    - SLS API：ListLogstore + GetLogstore，检查各 Logstore 的数据写入量和接入来源
    - ACK API：检查集群中是否有 Logtail DaemonSet 或 Fluentbit DaemonSet
    """

    def key(self) -> str:
        return "log_centralized"

    def dimension(self) -> str:
        return "Observability"

    def category(self) -> str:
        return "日志管理能力"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return ["sls.logstore.list"]

    def analyze(self, store) -> ScoreResult:
        logstores: list[SlsLogstoreRecord] = store.get("sls.logstore.list")

        if not logstores:
            return self._not_scored("未配置 SLS 日志服务", [])

        total = len(logstores)
        evidence = [f"检测到 {total} 个 Logstore"]
        score = 0.0

        # --- 1. 日志来源多样性 (最高 3 分) ---
        source_buckets = {
            "container": 0,
            "audit": 0,
            "access": 0,
            "application": 0,
        }
        for ls in logstores:
            name = (ls.name or "").lower()
            if not name:
                continue
            if any(k in name for k in ["k8s", "container", "pod", "stdout", "stderr", "logtail"]):
                source_buckets["container"] += 1
            elif any(k in name for k in ["audit", "k8s-audit", "apiserver"]):
                source_buckets["audit"] += 1
            elif any(k in name for k in ["access", "nginx", "ingress", "gateway", "alb"]):
                source_buckets["access"] += 1
            elif any(k in name for k in ["app", "application", "business", "service", "api"]):
                source_buckets["application"] += 1

        covered_sources = [s for s, cnt in source_buckets.items() if cnt > 0]
        source_count = len(covered_sources)

        if covered_sources:
            evidence.append(f"推断日志来源覆盖: {', '.join(sorted(covered_sources))}")
            source_score = min(source_count / 4 * 3, 3.0)
            score += source_score
            if source_count >= 4:
                evidence.append("✓ 日志来源覆盖非常全面 (容器/审计/访问/业务)")
            elif source_count >= 2:
                evidence.append(f"ℹ️ 日志来源覆盖 {source_count} 种，建议补充其他类型")
            else:
                evidence.append(f"⚠️ 日志来源较单一 ({covered_sources[0]})，建议补充审计和业务日志")
        else:
            evidence.append("⚠️ 无法通过名称推断日志来源，建议规范 Logstore 命名")

        # --- 2. 分片配置评估 (最高 2 分) ---
        total_shards = 0
        multi_shard_count = 0
        for ls in logstores:
            shard_count = ls.shard_count
            if shard_count is None:
                continue
            try:
                count = int(shard_count)
                total_shards += count
                if count >= 2:
                    multi_shard_count += 1
            except (ValueError, TypeError):
                continue

        shard_ratio = multi_shard_count / total if total else 0
        avg_shards = total_shards / total if total else 0

        if avg_shards >= 4:
            score += 2
            evidence.append(f"✓ 平均分片数 {avg_shards:.1f}，具备高吸吐能力")
        elif shard_ratio >= 0.5:
            score += 1
            evidence.append(f"✓ 多数 Logstore ({multi_shard_count}/{total}) 配置了多分片")
        elif multi_shard_count > 0:
            score += 0.5
            evidence.append(f"ℹ️ 少量 Logstore ({multi_shard_count}/{total}) 配置了多分片")
        else:
            evidence.append("ℹ️ 所有 Logstore 均为单分片，小规模场景可接受")

        very_short_ttl = [ls for ls in logstores if ls.ttl is not None and ls.ttl < 7]
        short_ttl = [ls for ls in logstores if ls.ttl is not None and 7 <= ls.ttl < 30]
        reasonable_ttl = [ls for ls in logstores if ls.ttl is not None and ls.ttl >= 30]

        if very_short_ttl:
            penalty = min(len(very_short_ttl) / total, 1.0)
            score -= penalty
            evidence.append(
                f"❌ {len(very_short_ttl)} 个 Logstore TTL < 7 天，不满足审计合规 (扣分)"
            )

        if reasonable_ttl:
            evidence.append(f"✓ {len(reasonable_ttl)} 个 Logstore TTL >= 30 天，符合审计要求")
        elif short_ttl:
            evidence.append(f"ℹ️ {len(short_ttl)} 个 Logstore TTL 7-30 天，建议延长保留天数")

        score = max(score, 0)
        final_score = min(round(score), 6)

        if final_score >= 5:
            conclusion = "日志集中收集架构完善，覆盖多来源且具备高吸吐能力"
        elif final_score >= 3:
            conclusion = "日志集中收集基本满足，建议在来源覆盖或分片配置上优化"
        else:
            conclusion = "日志收集配置简陋，存在单点风险或关键日志缺失"

        evidence.append(f"综合评分: {final_score}分")

        return self._scored(final_score, conclusion, evidence)


class LogStructureAnalyzer(Analyzer):
    """
    日志结构化分析器
    
    评估标准（累计评分，最高 6 分）：
    - JSON 格式：2 分
    - 标准字段 (time, level, msg)：1 分
    - TraceID 注入率 > 90%：3 分
    
    数据来源：
    - SLS API：GetLogs，抽取最近 100 条日志，统计 JSON 解析成功率
    - 检查是否包含 trace_id、service_name、level、timestamp 等标准字段
    """

    def key(self) -> str:
        return "log_structure"

    def dimension(self) -> str:
        return "Observability"

    def category(self) -> str:
        return "日志管理能力"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return ["sls.index_config.list", "sls.log_structure_analysis"]

    def analyze(self, store) -> ScoreResult:
        configs: list[SlsIndexConfigRecord] = store.get("sls.index_config.list")

        if not configs:
            return self._not_scored("未配置日志索引", [])

        evidence = []
        score = 0.0
        total_configs = len(configs)

        # --- 1. 字段索引覆盖率 (最高 2 分) ---
        field_indexed = [c for c in configs if c.index_enabled and c.field_index_count > 0]
        coverage_ratio = len(field_indexed) / total_configs if total_configs else 0

        evidence.append(
            f"已开启字段索引的 Logstore: {len(field_indexed)}/{total_configs} ({coverage_ratio * 100:.0f}%)")

        avg_fields = 0.0
        if field_indexed:
            avg_fields = sum(c.field_index_count for c in field_indexed) / len(field_indexed)
            evidence.append(f"平均索引字段数: {avg_fields:.1f}")

        if coverage_ratio >= 0.8 and avg_fields >= 10:
            score += 2
            evidence.append("✓ 字段索引覆盖全面且字段丰富，结构化程度高")
        elif coverage_ratio >= 0.5 and avg_fields >= 5:
            score += 1.5
            evidence.append(f"✓ 字段索引覆盖较好 ({coverage_ratio * 100:.0f}%)，平均 {avg_fields:.0f} 个字段")
        elif coverage_ratio >= 0.3 or avg_fields >= 3:
            score += 1
            evidence.append(f"ℹ️ 字段索引覆盖局部 ({coverage_ratio * 100:.0f}%)，结构化程度一般")
        elif field_indexed:
            score += 0.5
            evidence.append("⚠️ 字段索引覆盖范围有限")
        else:
            evidence.append("✗ 未配置字段索引，日志查询能力将大幅受限")

        # --- 2. 标准字段规范性 (最高 1.5 分) ---
        critical_fields = {"trace_id", "traceid", "span_id", "service", "service_name"}
        basic_fields = {"time", "timestamp", "level", "severity", "msg", "message"}

        has_critical = False
        has_basic = False
        max_matched = 0

        for config in field_indexed:
            names = config.field_names
            if not names:
                continue

            if isinstance(names, str):
                current_fields = set(n.strip().lower() for n in names.split(',') if n.strip())
            elif isinstance(names, list):
                current_fields = set(str(n).lower() for n in names)
            else:
                continue

            if current_fields & critical_fields:
                has_critical = True
            if len(current_fields & basic_fields) >= 2:
                has_basic = True
            max_matched = max(max_matched, len(current_fields & (critical_fields | basic_fields)))

        if has_critical and has_basic:
            score += 1.5
            evidence.append("✓ 包含关键可观测性字段 (trace_id/service) + 基础规范字段")
        elif has_critical:
            score += 1.0
            evidence.append("✓ 包含 trace_id/service 字段，具备链路关联能力")
        elif has_basic:
            score += 0.5
            evidence.append("ℹ️ 包含基础规范字段 (time/level/msg)，建议补充 trace_id")
        else:
            evidence.append("⚠️ 未检测到标准日志字段，建议规范日志格式")

        # --- 3. TraceID 注入率 (平滑评分，最高 2.5 分) ---
        analysis: list[SlsLogStructureAnalysisRecord] = store.get("sls.log_structure_analysis")
        if analysis:
            valid_analysis = [a for a in analysis if a is not None]
            if valid_analysis:
                with_trace_id = [a for a in valid_analysis if a.has_trace_id]
                trace_ratio = len(with_trace_id) / len(valid_analysis)

                evidence.append(f"TraceID 覆盖采样率: {trace_ratio * 100:.1f}%")

                trace_score = trace_ratio * 2.5
                score += trace_score

                if trace_ratio >= 0.9:
                    evidence.append("✓ TraceID 注入率极高 (>90%)，具备全链路追踪能力")
                elif trace_ratio >= 0.5:
                    evidence.append(f"ℹ️ TraceID 注入率中等 ({trace_ratio * 100:.0f}%)，建议提升")
                elif trace_ratio > 0:
                    evidence.append(f"⚠️ TraceID 注入率较低 ({trace_ratio * 100:.0f}%)，难以进行链路追踪")
                else:
                    evidence.append("✗ 未检测到 TraceID 注入")
        else:
            evidence.append("ℹ️ 无日志结构分析数据")

        final_score = min(round(score), 6)

        if final_score == 0:
            return self._not_scored("日志未结构化或缺乏关键追踪信息",
                                    ["未检测到有效的字段索引或 TraceID 注入"])

        if final_score >= 5:
            conclusion = "日志结构化程度高，具备完善的字段索引与全链路追踪能力"
        elif final_score >= 3:
            conclusion = "日志部分结构化，建议在 TraceID 注入或标准字段规范上优化"
        else:
            conclusion = "日志结构化程度低，难以支持高效检索与链路分析"

        evidence.append(f"综合评分: {final_score}分")

        return self._scored(final_score, conclusion, evidence)


class LogAnalysisAnalyzer(Analyzer):
    """
    日志分析能力分析器
    
    评估标准：是否具备实时查询、聚合分析、异常模式识别能力
    
    数据来源：
    - SLS API：CreateQuery 测试是否支持实时查询和聚合分析能力
    """

    def key(self) -> str:
        return "log_analysis"

    def dimension(self) -> str:
        return "Observability"

    def category(self) -> str:
        return "日志管理能力"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["sls.index_config.list"]

    def analyze(self, store) -> ScoreResult:
        configs: list[SlsIndexConfigRecord] = store.get("sls.index_config.list")

        if not configs:
            return self._not_scored("未配置日志索引，无法进行分析", [])

        indexed = [c for c in configs if c.index_enabled]

        if not indexed:
            return self._not_scored("日志索引已配置但未启用", [])

        total_count = len(indexed)
        evidence = [f"已启用 Logstore: {total_count} 个"]
        score = 0.0

        # --- 1. 全文索引 (最高 1.5 分, 按覆盖率平滑) ---
        fulltext = [c for c in indexed if c.fulltext_enabled]
        ft_ratio = len(fulltext) / total_count

        if fulltext:
            ft_score = ft_ratio * 1.5
            score += ft_score
            if ft_ratio >= 0.8:
                evidence.append(f"✓ 全文索引覆盖全面: {len(fulltext)}/{total_count} ({ft_ratio * 100:.0f}%)")
            else:
                evidence.append(f"ℹ️ 全文索引覆盖部分: {len(fulltext)}/{total_count} ({ft_ratio * 100:.0f}%)")
        else:
            evidence.append("✗ 未开启全文索引，日志关键词查询受限")

        # --- 2. 字段索引 (最高 2 分, 覆盖率 * 字段丰富度共同决定) ---
        field_indexed = [c for c in indexed if c.field_index_count > 0]
        fi_ratio = len(field_indexed) / total_count

        if field_indexed:
            avg_fields = sum(c.field_index_count for c in field_indexed) / len(field_indexed)

            coverage_factor = fi_ratio
            richness_factor = min(avg_fields / 15, 1.0)
            fi_score = (coverage_factor * 0.6 + richness_factor * 0.4) * 2
            score += fi_score

            if fi_ratio >= 0.8 and avg_fields >= 10:
                evidence.append(f"✓ 字段索引完善: {len(field_indexed)}/{total_count}，平均 {avg_fields:.0f} 字段")
            elif fi_ratio >= 0.5:
                evidence.append(f"ℹ️ 字段索引覆盖中等: {len(field_indexed)}/{total_count}，平均 {avg_fields:.0f} 字段")
            else:
                evidence.append(f"⚠️ 字段索引覆盖率低: {len(field_indexed)}/{total_count} ({fi_ratio * 100:.0f}%)")
        else:
            evidence.append("✗ 未配置字段索引，无法支持聚合分析")

        # --- 3. 丰富字段索引覆盖率 (最高 1.5 分) ---
        RICH_THRESHOLD = 10
        rich_indexed = [c for c in field_indexed if c.field_index_count >= RICH_THRESHOLD]
        ri_ratio = len(rich_indexed) / total_count

        if rich_indexed:
            ri_score = ri_ratio * 1.5
            score += ri_score
            if ri_ratio >= 0.5:
                evidence.append(
                    f"✓ 丰富字段索引 (>={RICH_THRESHOLD}字段): {len(rich_indexed)}/{total_count} ({ri_ratio * 100:.0f}%)")
            else:
                evidence.append(f"ℹ️ 少量 Logstore 有丰富索引: {len(rich_indexed)}/{total_count}")
        else:
            evidence.append(f"ℹ️ 未检测到字段数超过 {RICH_THRESHOLD} 的丰富索引")

        final_score = min(round(score), 5)

        if final_score >= 4:
            verdict = "日志分析能力完善，支持全文检索、要求聚合与复杂分析"
        elif final_score >= 3:
            verdict = "日志分析能力良好，建议提升字段索引覆盖率"
        elif final_score >= 2:
            verdict = "日志分析能力基础，建议开启字段索引以支持聚合分析"
        else:
            verdict = "日志分析能力不足，建议全面配置日志索引"

        evidence.append(f"综合评分: {final_score}分")

        return self._scored(final_score, verdict, evidence)


class LogRetentionPolicyAnalyzer(Analyzer):
    """
    保留策略分析器
    
    评估标准：是否根据合规要求和成本制定了分层存储策略 (热/温/冷数据) 及自动过期机制
    
    数据来源：
    - SLS API：GetLogstore，检查 ttl（数据保留天数）配置
    - 检查是否配置了 OSS Archive 的自动归档任务（冷存储）
    """

    def key(self) -> str:
        return "log_retention_policy"

    def dimension(self) -> str:
        return "Observability"

    def category(self) -> str:
        return "日志管理能力"

    def max_score(self) -> int:
        return 4

    def required_data(self) -> list[str]:
        return ["sls.logstore.list"]

    def optional_data(self) -> list[str]:
        return ["sls.archive_config.list"]

    def analyze(self, store) -> ScoreResult:
        logstores: list[SlsLogstoreRecord] = store.get("sls.logstore.list")

        if not logstores:
            return self._not_scored("未配置日志存储", [])

        total = len(logstores)
        evidence = [f"共检测到 {total} 个 Logstore"]
        score = 0.0

        # --- 1. 合规覆盖率 (最高 2.5 分) ---
        too_short = [ls for ls in logstores if ls.ttl < 7]
        minimal = [ls for ls in logstores if 7 <= ls.ttl < 30]
        compliant = [ls for ls in logstores if 30 <= ls.ttl < 90]
        long_term = [ls for ls in logstores if ls.ttl >= 90]

        avg_ttl = sum(ls.ttl for ls in logstores) / total
        min_ttl = min(ls.ttl for ls in logstores)

        evidence.append(f"平均 TTL: {avg_ttl:.0f} 天，最短 TTL: {min_ttl} 天")

        if too_short:
            evidence.append(f"❌ TTL < 7 天 (不合规): {len(too_short)}/{total} 个 Logstore")
        if minimal:
            evidence.append(f"⚠️ TTL 7-30 天 (最低合规线): {len(minimal)}/{total} 个")
        if compliant:
            evidence.append(f"✓ TTL 30-90 天 (合规): {len(compliant)}/{total} 个")
        if long_term:
            evidence.append(f"✓ TTL >= 90 天 (长期合规): {len(long_term)}/{total} 个")

        compliant_count = len(compliant) + len(long_term)
        compliant_ratio = compliant_count / total

        ttl_score = compliant_ratio * 2.0
        if len(long_term) / total >= 0.3:
            ttl_score += 0.5
        score += ttl_score

        noncompliant_ratio = len(too_short) / total
        if noncompliant_ratio > 0.2:
            penalty = (noncompliant_ratio - 0.2) * 1.0
            score -= penalty
            evidence.append(f"❌ 不合规 Logstore 超过 20%，扰分 {penalty:.1f} 分")

        # --- 2. 归档配置 (最高 1.5 分) ---
        archives: list[SlsArchiveConfigRecord] = store.get("sls.archive_config.list")
        if archives:
            archive_ratio = len(archives) / total
            if archive_ratio >= 0.5:
                score += 1.5
                evidence.append(f"✓ OSS 归档配置全面: {len(archives)}/{total} 个 Logstore")
            elif archive_ratio >= 0.2:
                score += 1.0
                evidence.append(f"✓ OSS 归档配置部分: {len(archives)}/{total} 个 Logstore")
            else:
                score += 0.5
                evidence.append(f"ℹ️ 少量 Logstore 配置归档: {len(archives)}/{total}")
        else:
            evidence.append("ℹ️ 未配置 OSS 归档，无法限制长期存储成本")

        final_score = max(min(round(score), 4), 0)

        if final_score >= 4:
            conclusion = "日志保留策略完善，合规覆盖全面且配置归档分层存储"
        elif final_score >= 3:
            conclusion = "日志保留策略较好，建议扩大合规 TTL 覆盖范围"
        elif final_score >= 2:
            conclusion = "日志保留策略基础，建议将核心日志 TTL 调整到 30 天以上"
        else:
            conclusion = "日志保留策略不足，大量 Logstore TTL 过短，存在审计合规风险"

        return self._scored(final_score, conclusion, evidence)


class LogContext(Analyzer):
    """
    上下文关联分析器
    
    评估标准：日志是否能通过 TraceID 与 Tracing 系统关联，或通过 Label 与 Metrics 关联
    
    数据来源：
    - UModel：APM trace_set_link 定义了 Trace 与 Log 的关联
    - 验证方式：检查日志中是否存在 trace_id 字段
    """

    def key(self) -> str:
        return "log_context"

    def dimension(self) -> str:
        return "Observability"

    def category(self) -> str:
        return "日志管理能力"

    def max_score(self) -> int:
        return 4

    def required_data(self) -> list[str]:
        return ["sls.index_config.list"]

    def optional_data(self) -> list[str]:
        return ["sls.log_structure_analysis", "apm.service.list"]

    def analyze(self, store) -> ScoreResult:
        configs: list[SlsIndexConfigRecord] = store.get("sls.index_config.list")

        if not configs:
            return self._not_scored("未获取到日志配置", [])

        evidence = []
        score = 0.0

        # --- 1. TraceID 字段索引覆盖率 (基础能力, 最高 1.5 分) ---
        trace_fields = {"trace_id", "traceid", "x-trace-id", "request_id", "span_id"}
        configs_with_trace = []

        for config in configs:
            names = config.field_names
            if not names:
                continue
            if isinstance(names, str):
                field_set = set(n.strip().lower() for n in names.split(',') if n.strip())
            elif isinstance(names, list):
                field_set = set(str(n).lower() for n in names)
            else:
                continue

            if field_set & trace_fields:
                configs_with_trace.append(config)

        total = len(configs)
        trace_field_ratio = len(configs_with_trace) / total if total else 0

        if configs_with_trace:
            field_score = trace_field_ratio * 1.5
            score += field_score
            if trace_field_ratio >= 0.8:
                evidence.append(f"✓ TraceID 字段索引覆盖全面: {len(configs_with_trace)}/{total}")
            else:
                evidence.append(
                    f"ℹ️ TraceID 字段索引覆盖部分: {len(configs_with_trace)}/{total} ({trace_field_ratio * 100:.0f}%)")
        else:
            evidence.append("✗ 未配置 TraceID 字段索引，无法支持通过 TraceID 检索日志")

        # --- 2. 实际 TraceID 注入率 (运行时验证, 最高 1.5 分) ---
        analysis: list[SlsLogStructureAnalysisRecord] = store.get("sls.log_structure_analysis")
        if analysis:
            valid = [a for a in analysis if a is not None]
            if valid:
                with_trace = [a for a in valid if a.has_trace_id]
                inject_ratio = len(with_trace) / len(valid)

                inject_score = inject_ratio * 1.5
                score += inject_score

                evidence.append(f"TraceID 实际注入率: {inject_ratio * 100:.1f}% ({len(with_trace)}/{len(valid)})")
                if inject_ratio >= 0.9:
                    evidence.append("✓ TraceID 注入率高，具备全链路关联能力")
                elif inject_ratio >= 0.5:
                    evidence.append("ℹ️ TraceID 注入率中等，建议提升")
                else:
                    evidence.append("⚠️ TraceID 注入率较低，链路关联效果将大打折扣")
        else:
            evidence.append("ℹ️ 无日志结构分析数据，无法验证 TraceID 实际注入率")

        # --- 3. APM 双向关联与成熟度 (最高 1 分) ---
        services: list[ApmServiceRecord] = store.get("apm.service.list")
        if services and configs_with_trace:
            score += 1.0
            evidence.append(f"✓ APM 服务可关联 ({len(services)} 个)，日志-Trace 双向关联已就绪")
        elif services and not configs_with_trace:
            score += 0.3
            evidence.append(f"ℹ️ APM 有 {len(services)} 个服务，但日志未注入 TraceID，关联无法生效")
        elif not services:
            evidence.append("ℹ️ 未检测到 APM 服务，建议配置 ARMS 完善全链路分析")

        final_score = max(min(round(score), 4), 0)

        if final_score == 0:
            return self._not_scored("日志无法与 Trace 系统关联", evidence)

        if final_score >= 4:
            conclusion = "日志与 Trace/Metrics 关联完善，具备全链路可观测性"
        elif final_score >= 3:
            conclusion = "日志具备较好的上下文关联能力，建议提升注入率"
        elif final_score >= 2:
            conclusion = "日志具备基础上下文关联能力，建议完善 APM 关联"
        else:
            conclusion = "日志关联能力有限，建议配置 TraceID 字段索引"

        return self._scored(final_score, conclusion, evidence)


# 导出所有分析器
LOGGING_ANALYZERS = [
    LogCentralizedAnalyzer(),
    LogStructureAnalyzer(),
    LogAnalysisAnalyzer(),
    LogRetentionPolicyAnalyzer(),
    LogContext(),
]
