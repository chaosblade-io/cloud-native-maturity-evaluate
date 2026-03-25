"""
Serverless 维度 - 事件驱动架构 (EDA) 分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)            | 分值  | 评分标准                                                       |
| eda_event_sources       | 0-10  | 事件源丰富度：>=5种源(10分)/3-4种(6分)/1-2种(2分)              |
| eda_event_bus           | 8     | 事件总线使用：托管事件总线或消息中间件解耦                     |
| eda_schema_registry     | 7     | 事件模式定义：使用 Schema Registry 定义事件结构                |
| eda_decoupling          | 5     | 解耦程度：生产者完全不知道消费者的存在                         |
| eda_error_handling      | 5     | 死信与重试：自动重试机制和死信队列                             |
"""
from sesora.core.analyzer import Analyzer, ScoreResult
from sesora.schema.eventbridge import (
    EbEventBusRecord, EbEventRuleRecord, EbEventTargetRecord,
    EbEventSourceRecord, EbSchemaRecord
)
from sesora.schema.apm import ApmServiceDependencyRecord


class EdaEventSourcesAnalyzer(Analyzer):
    """
    事件源丰富度分析器
    
    评估标准：
    - 覆盖 >=5 种源 (DB变更/文件/API/MQ/IoT/系统) 得 10 分
    - 覆盖 3-4 种得 6 分
    - 仅 1-2 种得 2 分
    
    数据来源：
    - EventBridge API：ListEventSources，枚举已配置的事件源类型
    - UModel：apm.external.message，APM 中的消息队列调用
    """

    def key(self) -> str:
        return "eda_event_sources"

    def dimension(self) -> str:
        return "Serverless"

    def category(self) -> str:
        return "事件驱动架构"

    def max_score(self) -> int:
        return 10

    def required_data(self) -> list[str]:
        return ["eventbridge.source.list"]

    def optional_data(self) -> list[str]:
        return ["eventbridge.rule.list"]

    def analyze(self, store) -> ScoreResult:
        sources: list[EbEventSourceRecord] = store.get("eventbridge.source.list") or []

        if not sources:
            return self._scored(0, "未配置事件源：尚未采用事件驱动架构模式", ["未检测到 EventBridge 事件源配置"])

        source_categories: set[str] = set()
        source_types: dict[str, str] = {}

        for src in sources:
            src_type = src.source_type.lower() if src.source_type else ""
            source_types[src.source_name] = src_type

            if any(kw in src_type for kw in ["rds", "db", "database", "polardb"]):
                source_categories.add("DB变更")
            elif any(kw in src_type for kw in ["oss", "nas", "file", "storage"]):
                source_categories.add("文件")
            elif any(kw in src_type for kw in ["api", "http", "gateway"]):
                source_categories.add("API")
            elif any(kw in src_type for kw in ["mq", "kafka", "rocketmq", "rabbitmq", "message"]):
                source_categories.add("MQ")
            elif any(kw in src_type for kw in ["iot", "device"]):
                source_categories.add("IoT")
            elif any(kw in src_type for kw in ["cms", "ecs", "ack", "system", "cloud"]):
                source_categories.add("系统")
            elif any(kw in src_type for kw in ["custom", "自定义"]):
                source_categories.add("自定义")

        evidence: list[str] = [
            f"事件源数量: {len(sources)}",
            f"事件源类型: {', '.join(source_categories) if source_categories else '未分类'}",
        ]

        score = 0.0

        # --- 1. 事件源多样性评分（0-4 分）---
        category_count = len(source_categories)
        if category_count >= 5:
            score += 4.0
            evidence.append("✓ 事件源类型非常丰富 (>=5 种)")
        elif category_count >= 3:
            score += 3.0
            evidence.append("✓ 事件源类型较丰富 (3-4 种)")
        elif category_count >= 1:
            score += 1.5
            evidence.append("事件源类型有限 (1-2 种)")
        else:
            evidence.append("ℹ️ 事件源类型未能分类，将仅按数量评估")

        # --- 2. 事件源数量与规模评分（0-3 分）---
        total_sources = len(sources)
        if total_sources >= 20:
            score += 3.0
            evidence.append("✓ 事件源数量多，已在多个系统中采用事件驱动模式")
        elif total_sources >= 10:
            score += 2.0
            evidence.append("✓ 事件源数量适中，事件驱动模式已初具规模")
        elif total_sources >= 3:
            score += 1.0
            evidence.append("事件源数量有限，事件驱动模式处于试点阶段")
        else:
            evidence.append("事件源数量极少，事件驱动模式刚起步")

        # --- 3. 核心类型覆盖加分（0-3 分）---
        core_covered = 0
        if "DB变更" in source_categories:
            core_covered += 1
        if "MQ" in source_categories:
            core_covered += 1
        if "API" in source_categories or "文件" in source_categories:
            core_covered += 1

        if core_covered == 3:
            score += 3.0
            evidence.append("✓ 核心事件源类型齐全 (DB/MQ/API/文件)")
        elif core_covered == 2:
            score += 2.0
            evidence.append("核心事件源类型部分覆盖")
        elif core_covered == 1:
            score += 1.0
            evidence.append("仅覆盖少数核心事件源类型")

        final_score = max(min(round(score), 10), 0)

        if final_score >= 8:
            status_msg = "事件源非常丰富且覆盖核心业务，EDA 能力成熟"
        elif final_score >= 6:
            status_msg = "事件源类型和数量较丰富，EDA 模式应用良好"
        elif final_score >= 3:
            status_msg = "事件源有限，事件驱动架构处于建设或试点阶段"
        elif final_score >= 1:
            status_msg = "事件源较少，事件驱动架构尚未形成体系"
        else:
            status_msg = "尚未采用事件驱动架构模式"

        return self._scored(final_score, status_msg, evidence)


class EdaEventBusAnalyzer(Analyzer):
    """
    事件总线使用分析器
    
    评估标准：是否使用托管事件总线 (如 EventBridge) 或消息中间件解耦生产者和消费者，
    而非点对点硬编码调用，同时检查流量占比
    
    数据来源：
    - EventBridge API：ListEventBuses，检查是否有自定义事件总线
    - RocketMQ API：Topic 列表，判断是否在使用消息中间件解耦
    """

    def key(self) -> str:
        return "eda_event_bus"

    def dimension(self) -> str:
        return "Serverless"

    def category(self) -> str:
        return "事件驱动架构"

    def max_score(self) -> int:
        return 8

    def required_data(self) -> list[str]:
        return ["eventbridge.bus.list"]

    def analyze(self, store) -> ScoreResult:
        buses: list[EbEventBusRecord] = store.get("eventbridge.bus.list") or []

        if not buses:
            return self._scored(0, "未使用 EventBridge 事件总线：仍以点对点调用为主", ["未检测到事件总线配置"])

        default_buses = [b for b in buses if b.bus_type == "CloudService" or "default" in b.bus_name.lower()]
        custom_buses = [b for b in buses if b.bus_type == "Custom" or b not in default_buses]

        evidence: list[str] = [
            f"事件总线数: {len(buses)}",
            f"自定义总线: {len(custom_buses)} 个",
            f"默认总线: {len(default_buses)} 个",
        ]

        score = 0.0

        # --- 1. 自定义总线使用情况（0-4 分）---
        if custom_buses:
            active_custom_buses = [b for b in custom_buses if b.rule_count > 0]
            custom_count = len(custom_buses)
            active_count = len(active_custom_buses)

            evidence.append(f"自定义总线总数: {custom_count}，有规则的总线: {active_count}")

            if active_count >= 2:
                score += 4.0
                evidence.append("✓ 多个自定义事件总线承载业务事件，解耦程度高")
            elif active_count == 1:
                score += 3.0
                evidence.append("✓ 已使用自定义事件总线解耦部分业务")
            elif custom_count > 0:
                score += 1.5
                evidence.append("已创建自定义事件总线但规则较少，EDA 应用有限")
        else:
            evidence.append("仅使用云服务默认事件总线")

        # --- 2. 默认总线使用情况（0-2 分）---
        if default_buses:
            score += 1.0
            if len(default_buses) > 1:
                score += 1.0
                evidence.append("✓ 配置了多个默认/云服务事件总线")
            else:
                evidence.append("使用单个默认事件总线")

        # --- 3. 规则数量与覆盖程度（0-2 分）---
        total_rules = sum(b.rule_count for b in buses)
        evidence.append(f"事件总线规则总数: {total_rules}")

        if total_rules >= 20:
            score += 2.0
            evidence.append("✓ 规则数量多，说明事件总线已广泛用于业务解耦")
        elif total_rules >= 5:
            score += 1.0
            evidence.append("事件总线规则数量适中，EDA 模式已初步落地")

        final_score = max(min(round(score), 8), 0)

        if final_score >= 7:
            status_msg = "已广泛使用自定义事件总线，业务解耦良好"
        elif final_score >= 5:
            status_msg = "已使用自定义事件总线，事件驱动架构应用较好"
        elif final_score >= 3:
            status_msg = "仅使用默认或单一事件总线，事件驱动架构处于建设阶段"
        elif final_score >= 1:
            status_msg = "事件总线使用有限，事件驱动架构尚未形成体系"
        else:
            status_msg = "未使用事件总线，仍以点对点调用为主"

        return self._scored(final_score, status_msg, evidence)


class EdaSchemaRegistryAnalyzer(Analyzer):
    """
    事件模式定义分析器
    
    评估标准：是否使用 Schema Registry (如 AWS Schema Registry, Avro) 定义事件结构，并实施兼容性检查
    
    数据来源：
    - EventBridge API：ListSchemas，检查是否有事件 Schema 定义
    """

    def key(self) -> str:
        return "eda_schema_registry"

    def dimension(self) -> str:
        return "Serverless"

    def category(self) -> str:
        return "事件驱动架构"

    def max_score(self) -> int:
        return 7

    def required_data(self) -> list[str]:
        return ["eventbridge.schema.list"]

    def analyze(self, store) -> ScoreResult:
        schemas: list[EbSchemaRecord] = store.get("eventbridge.schema.list")

        if not schemas:
            return self._scored(0, "未使用 Schema Registry 定义事件结构", ["未检测到事件 Schema 定义"])

        evidence: list[str] = []
        warnings: list[str] = []
        score = 0.0

        count = len(schemas)
        evidence.append(f"Schema 数量: {count}")

        # --- 1. 采用程度评分（0-3 分，基于数量）---
        if count >= 10:
            score += 3.0
            evidence.append("✓ Schema 数量多，事件结构定义较为全面")
        elif count >= 5:
            score += 2.0
            evidence.append("✓ Schema 数量适中，已在多个事件中使用 Schema 定义")
        elif count >= 2:
            score += 1.0
            evidence.append("Schema 使用处于起步阶段")
        else:
            score += 0.5
            evidence.append("仅定义了少量 Schema")

        # --- 2. 版本管理成熟度（0-2 分）---
        versioned_schemas = [s for s in schemas if s.version_count > 1]
        versioned_count = len(versioned_schemas)

        if versioned_count > 0:
            version_ratio = versioned_count / count
            evidence.append(f"多版本 Schema 数量: {versioned_count} 个 ({version_ratio * 100:.1f}%)")

            if version_ratio >= 0.6:
                score += 2.0
                evidence.append("✓ 大部分关键事件 Schema 具备版本演进管理")
            elif version_ratio >= 0.3:
                score += 1.5
                evidence.append("✓ 部分事件 Schema 具备版本管理")
            else:
                score += 1.0
                evidence.append("有少量 Schema 具备版本管理能力")
        else:
            if count >= 5:
                warnings.append("所有 Schema 均为单版本，缺乏演进管理，建议引入版本控制")

        # --- 3. Schema 格式多样性（0-1 分）---
        formats = {s.schema_format for s in schemas if s.schema_format} or set()
        if formats:
            evidence.append(f"Schema 格式: {', '.join(formats)}")
            if len(formats) >= 2:
                score += 1.0
                evidence.append("✓ 支持多种 Schema 格式，便于跨语言/跨系统集成")
            else:
                score += 0.5
        else:
            evidence.append("ℹ️ 未检测到明确的 Schema 格式定义")

        # --- 4. 描述与治理程度（0-1 分）---
        described = [s for s in schemas if (s.description or "").strip()]
        if count > 0:
            desc_ratio = len(described) / count
            if desc_ratio >= 0.8:
                score += 1.0
                evidence.append("✓ 大部分 Schema 含有描述信息，便于团队理解与治理")
            elif desc_ratio >= 0.5:
                score += 0.5
                evidence.append("部分 Schema 含有描述信息")
            else:
                warnings.append("多数 Schema 缺少描述信息，不利于事件模型治理")

        final_score = max(min(int(round(score)), 7), 0)

        if final_score >= 6:
            summary = "Schema Registry 使用完善：规模、版本管理与治理水平较高"
        elif final_score >= 4:
            summary = "Schema Registry 使用良好：已在关键事件中采用并具备一定版本管理"
        elif final_score >= 2:
            summary = "Schema Registry 基础使用：有部分 Schema 定义，但治理与版本管理有限"
        else:
            summary = "Schema Registry 使用有限：仅有少量定义或缺乏治理"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(final_score, summary, evidence)


class EdaDecouplingAnalyzer(Analyzer):
    """
    解耦程度分析器
    
    评估标准：核心业务流程中，生产者是否完全不知道消费者的存在 (通过事件路由)
    
    数据来源：
    - UModel：apm.metric.topology（arms_service_graph_request_count），分析服务调用图
    - 判断逻辑：同步调用链越短、MQ 类型调用占比越高，解耦程度越高
    """

    def key(self) -> str:
        return "eda_decoupling"

    def dimension(self) -> str:
        return "Serverless"

    def category(self) -> str:
        return "事件驱动架构"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["apm.service.dependency"]

    def optional_data(self) -> list[str]:
        return ["eventbridge.rule.list"]

    def analyze(self, store) -> ScoreResult:
        dependencies: list[ApmServiceDependencyRecord] = store.get("apm.service.dependency") or []

        if not dependencies:
            return self._not_evaluated("未获取到服务依赖数据")

        sync_calls = []
        async_calls = []

        for dep in dependencies:
            call_type = dep.call_type.lower() if dep.call_type else ""

            if any(kw in call_type for kw in ["http", "rpc", "grpc", "dubbo"]):
                sync_calls.append(dep)
            elif any(kw in call_type for kw in ["mq", "kafka", "rocketmq", "event", "message"]):
                async_calls.append(dep)

        total = len(sync_calls) + len(async_calls)
        async_ratio = len(async_calls) / total if total > 0 else 0

        evidence = [
            f"同步调用: {len(sync_calls)} 条",
            f"异步调用: {len(async_calls)} 条",
            f"异步调用占比: {async_ratio * 100:.0f}%"
        ]

        score = 0.0
        warnings = []

        # --- 1. 异步调用占比评分 (0-3 分) ---
        if async_ratio >= 0.6:
            score += 3.0
            evidence.append("✓ 异步调用占比高，系统解耦良好")
        elif async_ratio >= 0.4:
            score += 2.0
            evidence.append("✓ 异步调用占比适中，部分服务已解耦")
        elif async_ratio >= 0.2:
            score += 1.0
            evidence.append("异步调用占比较低，系统耦合度较高")
        elif total > 0:
            score += 0.5
            warnings.append("异步调用极少，系统高度耦合，建议引入消息队列解耦")
        else:
            warnings.append("无法识别调用类型，请检查 APM 数据质量")

        # --- 2. EventBridge 规则使用情况 (0-1 分) ---
        eventbridge_score = 0.0
        if store.available("eventbridge.rule.list"):
            rules: list[EbEventRuleRecord] = store.get("eventbridge.rule.list") or []
            if rules:
                rule_count = len(rules)
                evidence.append(f"EventBridge 规则: {rule_count} 条")
                if rule_count >= 10:
                    eventbridge_score = 1.0
                    evidence.append("✓ EventBridge 规则丰富，事件驱动架构应用成熟")
                elif rule_count >= 3:
                    eventbridge_score = 0.5
                    evidence.append("EventBridge 规则数量适中")
                else:
                    eventbridge_score = 0.3
                    evidence.append("EventBridge 规则较少，EDA 应用有限")

        score += eventbridge_score

        # --- 3. 异步调用质量评估 (0-1 分) ---
        reliable_async = [dep for dep in async_calls if any(
            kw in (dep.call_type or "").lower()
            for kw in ["rocketmq", "kafka", "rabbitmq", "mq"]
        )]
        if async_calls:
            reliable_ratio = len(reliable_async) / len(async_calls)
            if reliable_ratio >= 0.8:
                score += 1.0
                evidence.append("✓ 异步调用主要使用可靠消息中间件，具备缓冲和重试能力")
            elif reliable_ratio >= 0.5:
                score += 0.5
                evidence.append("部分异步调用使用消息中间件")
            else:
                warnings.append("异步调用多使用轻量级机制，建议引入消息队列增强可靠性")

        final_score = max(min(int(round(score)), 5), 0)

        if final_score >= 4:
            status_msg = "解耦程度高：异步调用占比高且使用可靠消息中间件"
        elif final_score >= 3:
            status_msg = "解耦程度较好：异步调用占比较高"
        elif final_score >= 2:
            status_msg = "解耦程度一般：异步调用占比适中"
        elif final_score >= 1:
            status_msg = "解耦程度较低：以同步调用为主，建议引入事件驱动架构"
        else:
            status_msg = "解耦程度低：系统高度耦合，需重点改进"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(final_score, status_msg, evidence)


class EdaErrorHandlingAnalyzer(Analyzer):
    """
    死信与重试分析器
    
    评估标准：事件处理失败时，是否有自动重试机制和死信队列 (DLQ) 用于人工干预或后续分析
    
    数据来源：
    - RocketMQ API：检查 Topic 是否有对应的死信 Topic 配置
    - EventBridge API：检查 EventBus 的重试策略和死信队列配置
    """

    def key(self) -> str:
        return "eda_error_handling"

    def dimension(self) -> str:
        return "Serverless"

    def category(self) -> str:
        return "事件驱动架构"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["eventbridge.target.list"]

    def analyze(self, store) -> ScoreResult:
        targets: list[EbEventTargetRecord] = store.get("eventbridge.target.list") or []

        if not targets:
            return self._scored(0, "未配置事件目标：无事件处理机制，错误处理无从谈起",
                                ["未检测到 EventBridge 事件目标配置"])

        with_retry = [t for t in targets if t.retry_strategy]
        with_dlq = [t for t in targets if t.dead_letter_queue]
        with_complete = [t for t in targets if t.retry_strategy and t.dead_letter_queue]

        total_count = len(targets)
        retry_count = len(with_retry)
        dlq_count = len(with_dlq)
        complete_count = len(with_complete)

        retry_ratio = retry_count / total_count
        dlq_ratio = dlq_count / total_count
        complete_ratio = complete_count / total_count

        evidence = [
            f"目标总数: {total_count}",
            f"配置重试: {retry_count} 个 ({retry_ratio:.0%})",
            f"配置死信队列: {dlq_count} 个 ({dlq_ratio:.0%})",
            f"完整错误处理(重试+死信): {complete_count} 个 ({complete_ratio:.0%})"
        ]

        score = 0.0
        warnings = []

        # --- 1. 完整错误处理覆盖率 (0-3 分) ---
        if complete_ratio >= 0.8:
            score += 3.0
            evidence.append("✓ 绝大多数目标配置了完整的错误处理机制(重试+死信)")
        elif complete_ratio >= 0.5:
            score += 2.0
            evidence.append("✓ 超过半数目标配置了完整的错误处理机制")
        elif complete_ratio >= 0.2:
            score += 1.0
            evidence.append("部分目标配置了完整的错误处理机制")
        elif complete_count > 0:
            score += 0.5
            evidence.append("仅少数目标配置了完整的错误处理机制")

        # --- 2. 重试策略覆盖率 (0-1.5 分) ---
        if retry_ratio >= 0.8:
            score += 1.5
            evidence.append("✓ 重试策略覆盖率高")
        elif retry_ratio >= 0.5:
            score += 1.0
            evidence.append("重试策略覆盖率中等")
        elif retry_ratio > 0:
            score += 0.5
            evidence.append("重试策略覆盖率较低")

        # --- 3. 死信队列覆盖率 (0-1.5 分) ---
        if dlq_ratio >= 0.8:
            score += 1.5
            evidence.append("✓ 死信队列配置完善")
        elif dlq_ratio >= 0.5:
            score += 1.0
            evidence.append("死信队列配置较好")
        elif dlq_ratio > 0:
            score += 0.5
            evidence.append("死信队列配置有限")

        retry_without_dlq = [t for t in with_retry if not t.dead_letter_queue]
        if retry_without_dlq and len(retry_without_dlq) / retry_count > 0.5:
            warnings.append(f"{len(retry_without_dlq)} 个目标配置了重试但没有死信队列，存在无限重试风险")
            score = max(score - 0.5, 0)

        no_handling = total_count - retry_count - dlq_count + complete_count
        if no_handling / total_count > 0.5:
            warnings.append(f"{no_handling} 个目标({no_handling / total_count:.0%})未配置任何错误处理机制")

        final_score = max(min(int(round(score)), 5), 0)

        if final_score >= 4:
            status_msg = "错误处理机制完善：重试+死信队列配置完整"
        elif final_score >= 3:
            status_msg = "错误处理机制较好：大部分目标具备完整的错误处理能力"
        elif final_score >= 2:
            status_msg = "错误处理机制基本配置：部分目标具备错误处理能力"
        elif final_score >= 1:
            status_msg = "错误处理机制有待改进：覆盖率较低或配置不完整"
        else:
            status_msg = "严重风险：错误处理机制缺失或配置不当"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(final_score, status_msg, evidence)


EDA_ANALYZERS = [
    EdaEventSourcesAnalyzer(),
    EdaEventBusAnalyzer(),
    EdaSchemaRegistryAnalyzer(),
    EdaDecouplingAnalyzer(),
    EdaErrorHandlingAnalyzer(),
]
