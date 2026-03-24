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
from ...core.analyzer import Analyzer, ScoreResult
from ...schema.eventbridge import (
    EbEventBusRecord, EbEventRuleRecord, EbEventTargetRecord,
    EbEventSourceRecord, EbSchemaRecord
)
from ...schema.apm import ApmServiceDependencyRecord


class EdaEventSources(Analyzer):
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
        sources: list[EbEventSourceRecord] = store.get("eventbridge.source.list")
        
        if not sources:
            return self._not_scored("未配置事件源", [])
        
        # 分类事件源
        source_categories = set()
        source_types = {}
        
        for src in sources:
            src_type = src.source_type.lower() if src.source_type else ""
            source_types[src.source_name] = src_type
            
            # 分类事件源
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
        
        evidence = [
            f"事件源数量: {len(sources)}",
            f"事件源类型: {', '.join(source_categories) if source_categories else '未分类'}"
        ]
        
        category_count = len(source_categories)
        
        if category_count >= 5:
            return self._scored(10, "事件源非常丰富 (>=5种类型)", evidence)
        elif category_count >= 3:
            return self._scored(6, "事件源丰富 (3-4种类型)", evidence)
        elif category_count >= 1:
            return self._scored(2, "事件源有限 (1-2种类型)", evidence)
        else:
            # 有事件源但无法分类
            if len(sources) >= 5:
                return self._scored(6, "事件源数量充足", evidence)
            elif len(sources) >= 2:
                return self._scored(3, "事件源数量有限", evidence)
            else:
                return self._scored(1, "事件源数量极少", evidence)


class EdaEventBus(Analyzer):
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
        buses: list[EbEventBusRecord] = store.get("eventbridge.bus.list")
        
        if not buses:
            return self._not_scored("未使用 EventBridge 事件总线", [])
        
        # 区分系统默认总线和自定义总线
        default_buses = [b for b in buses if b.bus_type == "Default" or "default" in b.bus_name.lower()]
        custom_buses = [b for b in buses if b.bus_type == "Custom" or b not in default_buses]
        
        evidence = [
            f"事件总线数: {len(buses)}",
            f"自定义总线: {len(custom_buses)} 个",
            f"默认总线: {len(default_buses)} 个"
        ]
        
        if custom_buses:
            # 检查自定义总线是否有规则配置
            active_buses = [b for b in custom_buses if b.rule_count > 0]
            if active_buses:
                evidence.append(f"✓ 活跃自定义总线: {len(active_buses)} 个")
                return self._scored(8, "已使用自定义事件总线解耦", evidence)
            else:
                return self._scored(6, "已创建自定义总线但规则较少", evidence)
        elif default_buses:
            # 只有默认总线
            return self._scored(4, "使用默认事件总线", evidence)
        else:
            return self._scored(2, "事件总线配置基础", evidence)


class EdaSchemaRegistry(Analyzer):
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
            return self._not_scored("未使用 Schema Registry 定义事件结构", [])

        evidence = []
        score = 0
        reasons = []

        count = len(schemas)
        evidence.append(f"Schema 数量: {count}")

        # 1. 计算基础分 (基于数量)
        if count >= 10:
            score = 5
            reasons.append("规模庞大")
        elif count >= 5:
            score = 4
            reasons.append("数量良好")
        elif count >= 2:
            score = 2
            reasons.append("基础使用")
        else:
            score = 1
            reasons.append("使用有限")

        # 2. 检查格式信息
        formats = set(s.schema_format for s in schemas if s.schema_format)
        if formats:
            evidence.append(f"Schema 格式: {', '.join(formats)}")
        else:
            # 即使没有格式也不扣分，但作为提示信息
            evidence.append("ℹ️ 未检测到明确的 Schema 格式定义")

        versioned_schemas = [s for s in schemas if getattr(s, 'version_count', 0) > 1]
        version_count = len(versioned_schemas)

        if version_count > 0:
            evidence.append(f"✓ 多版本 Schema: {version_count} 个")

            # 根据基数分给予不同权重的加分
            if score >= 5:
                # 大规模且有版本管理：直接拉满到 7 分 (5 + 2)
                score += 2
                reasons.append("版本管理完善")
            elif score >= 2:
                # 中小规模且有版本管理：小幅奖励 ( +1 )
                score += 1
                reasons.append("具备版本演进意识")
        else:
            # 关键改进：如果没有版本管理，且数量较多，明确记录原因
            if count >= 5:
                evidence.append("⚠️ 所有 Schema 均为单版本，缺乏演进管理，影响评分")
                if count >= 10:
                    reasons.append("规模大但缺乏版本控制")

        # 确保不超过满分 7
        final_score = min(score, 7)

        # 构建最终评语
        if final_score == 7:
            summary = "Schema Registry 使用完善"
        elif final_score >= 5:
            summary = "Schema Registry 使用良好"
        elif final_score >= 3:
            summary = "Schema Registry 基础使用"
        else:
            summary = "Schema Registry 使用有限"
        return self._scored(final_score, summary, evidence)

class EdaDecoupling(Analyzer):
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
        dependencies: list[ApmServiceDependencyRecord] = store.get("apm.service.dependency")
        
        if not dependencies:
            return self._not_evaluated("未获取到服务依赖数据")
        
        # 分析调用类型
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
            f"异步调用占比: {async_ratio*100:.0f}%"
        ]
        
        # 检查事件规则数
        if store.available("eventbridge.rule.list"):
            rules: list[EbEventRuleRecord] = store.get("eventbridge.rule.list")
            if rules:
                evidence.append(f"事件规则: {len(rules)} 条")
                async_ratio += 0.1  # 有事件规则加分
        
        # 评分判断
        if async_ratio >= 0.5:
            return self._scored(5, "解耦程度高：异步调用占比高", evidence)
        elif async_ratio >= 0.3:
            return self._scored(4, "解耦程度较好", evidence)
        elif async_ratio >= 0.1:
            return self._scored(2, "解耦程度一般", evidence)
        else:
            return self._not_scored("解耦程度低：同步调用为主", evidence)


class EdaErrorHandling(Analyzer):
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
        targets: list[EbEventTargetRecord] = store.get("eventbridge.target.list")

        if not targets:
            return self._not_evaluated("未配置事件目标")

        # 检查是否配置了重试
        with_retry = [t for t in targets if t.retry_strategy]
        with_dlq = [t for t in targets if t.dead_letter_queue]

        total_count = len(targets)
        retry_count = len(with_retry)
        dlq_count = len(with_dlq)

        # 计算比率 (确保浮点数运算)
        retry_ratio = retry_count / total_count
        dlq_ratio = dlq_count / total_count

        evidence = [
            f"目标总数: {total_count}",
            f"配置重试: {retry_count} 个 ({retry_ratio:.0%})",
            f"配置死信队列: {dlq_count} 个 ({dlq_ratio:.0%})"
        ]

        score = 0

        # 重试策略评分
        if retry_ratio >= 0.8:
            score += 2
            evidence.append("✓ 重试策略覆盖率高 (≥80%)")
        elif retry_ratio >= 0.5:
            score += 1
            evidence.append("△ 重试策略覆盖率中等 (≥50%)")
        elif retry_ratio > 0:
            evidence.append("✗ 重试策略覆盖率低 (<50%)")

        # 死信队列评分
        if dlq_ratio >= 0.5:
            score += 3
            evidence.append("✓ 死信队列配置完善 (≥50%)")
        elif dlq_ratio > 0:
            score += 2
            evidence.append("△ 死信队列部分配置")
        else:
            evidence.append("✗ 未配置死信队列")

        if score >= 4:
            return self._scored(5, "错误处理完善：重试+死信队列", evidence)
        elif score >= 2:
            return self._scored(score, "错误处理基本配置", evidence)
        elif score > 0:
            return self._scored(score, "错误处理有待改进", evidence)
        else:
            # 修改点：这里应该是明确的 0 分，表示配置了但做得很差，而不是无法评分
            return self._scored(0, "严重风险：未配置任何错误处理机制", evidence)

# 导出所有分析器
EDA_ANALYZERS = [
    EdaEventSources(),
    EdaEventBus(),
    EdaSchemaRegistry(),
    EdaDecoupling(),
    EdaErrorHandling(),
]
