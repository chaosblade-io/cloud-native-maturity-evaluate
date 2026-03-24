"""
EventBridge (事件总线) 相关 DataItem Record 类型定义
数据来源：阿里云 EventBridge
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class EventBridgeEventSourceRecord:
    """EventBridge 事件源记录"""
    event_source_name: str
    event_bus_name: str
    description: str = ""
    event_source_type: str = ""  # AliyunService/Custom/HTTP/Scheduled
    source_type: str = ""  # 别名，事件源类型
    config: dict = field(default_factory=dict)
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None
    
    @property
    def source_name(self) -> str:
        return self.event_source_name


# Alias
EbEventSourceRecord = EventBridgeEventSourceRecord


@dataclass
class EventBridgeEventBusRecord:
    """EventBridge 事件总线记录"""
    event_bus_name: str
    description: str = ""
    event_bus_type: str = "CloudService"  # CloudService/Custom
    bus_type: str = "CloudService"  # 别名
    rule_count: int = 0  # 规则数量
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None
    
    @property
    def bus_name(self) -> str:
        return self.event_bus_name


# Alias
EbEventBusRecord = EventBridgeEventBusRecord


@dataclass
class EbEventRuleRecord:
    """EventBridge 事件规则记录"""
    rule_name: str
    event_bus_name: str
    description: str = ""
    filter_pattern: dict = field(default_factory=dict)  # 事件过滤模式
    status: str = "ENABLE"  # ENABLE/DISABLE
    targets: list[dict] = field(default_factory=list)
    create_time: Optional[datetime] = None


@dataclass
class EbEventTargetRecord:
    """EventBridge 事件目标记录"""
    target_id: str
    rule_name: str
    event_bus_name: str
    target_type: str  # FC/MNS/RocketMQ/HTTP/etc.
    target_endpoint: str = ""
    retry_strategy: dict = field(default_factory=dict)
    dead_letter_queue: dict = field(default_factory=dict)
    transform_config: dict = field(default_factory=dict)


@dataclass
class EventBridgeSchemaRecord:
    """EventBridge Schema 记录"""
    schema_name: str
    event_bus_name: str
    description: str = ""
    schema_content: str = ""  # JSON Schema 内容
    schema_format: str = "JSONSchema"  # JSONSchema/OpenAPI/Protobuf
    version_count: int = 1  # 版本数量
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None


# Alias
EbSchemaRecord = EventBridgeSchemaRecord


@dataclass
class RocketMqTopicRecord:
    """RocketMQ Topic 记录"""
    instance_id: str
    topic_name: str
    message_type: str  # NORMAL/FIFO/DELAY/TRANSACTION
    region: str = ""
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None
