"""
SLS (日志服务) 相关 DataItem Record 类型定义
数据来源：阿里云 SLS
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class SlsLogstoreRecord:
    """SLS Logstore 记录"""
    project_name: str
    logstore_name: str
    ttl: int  # 数据保存时间(天)
    hot_ttl: int = 0  # 热存储保留时间(天)，0表示不区分冷热存储
    shard_count: int = 1
    auto_split: bool = True
    max_split_shard: int = 64
    create_time: Optional[datetime] = None
    last_modify_time: Optional[datetime] = None
    
    @property
    def name(self) -> str:
        """便捷属性：返回 logstore 名称"""
        return self.logstore_name


@dataclass
class SlsLogSampleRecord:
    """SLS 日志样本记录"""
    project_name: str
    logstore_name: str
    timestamp: datetime
    source: str
    contents: str = ""
    topic: str = ""


@dataclass
class SlsLogStructureAnalysisRecord:
    """SLS 日志结构分析记录"""
    project_name: str
    logstore_name: str
    sample_count: int = 100  # 采样数量
    json_parse_rate: float = 0.0  # JSON 解析成功率
    is_json_format: bool = False  # 是否为 JSON 格式
    has_timestamp_field: bool = False  # 是否有时间戳字段
    has_level_field: bool = False  # 是否有日志级别字段
    has_message_field: bool = False  # 是否有消息字段
    has_trace_id_field: bool = False  # 是否有 TraceID 字段
    has_service_name_field: bool = False  # 是否有服务名字段
    trace_id_injection_rate: float = 0.0  # TraceID 注入率
    standard_fields: list[str] = field(default_factory=list)  # 检测到的标准字段
    
    @property
    def has_trace_id(self) -> bool:
        """便捷属性：返回是否有 TraceID"""
        return self.has_trace_id_field or self.trace_id_injection_rate > 0


@dataclass
class SlsIndexConfigRecord:
    """SLS 索引配置记录"""
    project_name: str
    logstore_name: str
    index_enabled: bool = False
    fulltext_enabled: bool = False
    field_index_count: int = 0
    keys: list[str] = field(default_factory=list)  # 字段索引列表
    field_names: list[str] = field(default_factory=list)  # 字段名列表


@dataclass
class SlsQueryCapabilityRecord:
    """SLS 查询能力记录"""
    project_name: str
    logstore_name: str
    supports_realtime_query: bool = True  # 支持实时查询
    supports_aggregation: bool = True  # 支持聚合分析
    supports_sql: bool = True  # 支持 SQL 查询
    index_enabled: bool = False  # 是否开启索引
    full_text_index: bool = False  # 是否开启全文索引
    field_index_count: int = 0  # 字段索引数量


@dataclass
class SlsArchiveConfigRecord:
    """SLS 日志归档配置记录"""
    project_name: str
    logstore_name: str
    hot_ttl_days: int = 0  # 热存储保留天数
    warm_ttl_days: int = 0  # 温存储保留天数
    cold_archive_enabled: bool = False  # 是否开启冷存储归档
    max_retention_days: int = 0  # 最大保留天数
