"""
APM (应用性能监控) 相关 DataItem Record 类型定义
数据来源：ARMS
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar, Optional


@dataclass
class ApmServiceRecord:
    """APM 服务记录"""
    DATAITEM_NAME: ClassVar[str] = "apm.service.list"
    service_name: str
    app_id: str = ""
    pid: str = ""
    region: str = ""
    language: Optional[str] = ""  # Java/Go/Python/Node.js/etc.
    service_type: str = ""
    trace_enabled: bool = True
    labels: dict[str, str] = field(default_factory=dict)
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None


@dataclass
class ApmTraceRecord:
    """APM 链路记录"""
    DATAITEM_NAME: ClassVar[str] = "apm.trace.list"
    trace_id: str
    service_name: str
    operation_name: str
    start_time: Optional[datetime] = None
    duration_ms: int = 0
    has_error: bool = False
    span_count: int = 0
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class ApmServiceDependencyRecord:
    """APM 服务依赖关系记录"""
    DATAITEM_NAME: ClassVar[str] = "apm.service.dependency"
    source_service: str
    target_service: str
    call_type: str = "HTTP"  # HTTP/Dubbo/gRPC/MySQL/Redis
    call: str = ""  # 具体调用信息，如 URL、RPC 方法等


@dataclass
class ApmTopologyMetricsRecord:
    """APM 拓扑指标记录"""
    DATAITEM_NAME: ClassVar[str] = "apm.topology.metrics"
    source_service: str
    target_service: str
    call_type: str  # HTTP/Dubbo/MySQL/Redis/etc.
    call: str
    call_count: int = 0
    error_count: int = 0
    rt: float = 0.0  # 平均响应时间(ms)
    timestamp: Optional[datetime] = None


@dataclass
class ApmExternalDatabaseRecord:
    """APM 外部数据库调用记录"""
    DATAITEM_NAME: ClassVar[str] = "apm.external.database"
    service_name: str
    db_type: str  # MySQL/Redis/MongoDB/PostgreSQL/etc.
    db_instance: str
    call_count: int = 0
    error_count: int = 0
    rt: float = 0.0  # 平均响应时间(ms)
    timestamp: Optional[datetime] = None


@dataclass
class ApmExternalMessageRecord:
    """APM 外部消息队列调用记录"""
    DATAITEM_NAME: ClassVar[str] = "apm.external.message"
    service_name: str
    mq_type: str  # RocketMQ/Kafka/RabbitMQ/etc.
    topic_or_queue: str
    operation: str  # send/consume
    call_count: int = 0
    error_count: int = 0
    rt: float = 0.0  # 平均响应时间(ms)
    timestamp: Optional[datetime] = None


@dataclass
class ApmServiceDbMappingRecord:
    """APM 服务-数据库映射记录（用于分析数据架构模式）"""
    DATAITEM_NAME: ClassVar[str] = "apm.service.db.mapping"
    service_name: str
    database_name: str  # 数据库名
    db_type: str = "MySQL"  # MySQL/Redis/MongoDB/etc.
    db_instance: str = ""  # 数据库实例标识
    access_type: str = "read_write"  # read_only/write_only/read_write
    is_shared: bool = False  # 是否与其他服务共享
    shared_with: list[str] = field(default_factory=list)  # 共享的服务列表


# TODO: Remove this record
@dataclass
class ApmCoverageAnalysisRecord:
    """APM 覆盖率分析记录"""
    DATAITEM_NAME: ClassVar[str] = "apm.coverage.analysis"
    total_services: int = 0  # 总服务数
    total_deployments: int = 0  # K8s 中的 Deployment 数量
    covered_services: int = 0  # 接入 APM 的服务数量
    traced_services: int = 0  # 接入 APM 的服务数量
    coverage_rate: float = 0.0  # 覆盖率
    coverage_ratio: float = 0.0  # 覆盖率
    untraced_services: list[str] = field(default_factory=list)  # 未接入的服务
    topology_nodes: int = 0  # 拓扑图节点数
    monitored_nodes: int = 0  # 有监控数据的节点数
    # 黄金信号完整性
    has_traffic_metric: bool = False
    has_error_metric: bool = False
    has_latency_metric: bool = False
    golden_signals_complete: bool = False  # Traffic + Error + Latency 都有


@dataclass
class ApmSamplingConfigRecord:
    """APM 链路采样配置记录"""
    DATAITEM_NAME: ClassVar[str] = "apm.sampling.config"
    app_id: str = ""
    strategy: str = "probabilistic"  # probabilistic/tail-based/fixed
    sample_rate: float = 0.1  # 正常请求采样率
    error_sample_rate: float = 1.0  # 错误请求采样率（应为100%）
    slow_threshold_ms: int = 1000  # 慢请求阈值
    slow_sample_rate: float = 1.0  # 慢请求采样率
    custom_rules: list[dict] = field(default_factory=list)
