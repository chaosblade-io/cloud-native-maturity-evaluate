"""
RDS/OSS/PolarDB/ROS 相关 DataItem Record 类型定义
数据来源：阿里云 RDS、OSS、资源编排等
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar, Literal, Optional, Union


@dataclass
class RdsInstanceRecord:
    """RDS 实例记录"""
    DATAITEM_NAME: ClassVar[str] = "rds.instance.list"
    db_instance_id: str
    db_instance_description: Optional[str] = ""
    db_instance_type: str = "Primary"  # Primary/Readonly
    db_instance_class: str = ""
    engine: str = "MySQL"  # MySQL/PostgreSQL/SQLServer/MariaDB
    engine_version: str = ""
    db_instance_status: str = "Running"
    zone_id: str = ""
    region_id: str = ""
    auto_upgrade_minor_version: bool = False
    instance_network_type: str = "VPC"  # Classic/VPC
    connection_string: str = ""
    port: str = "3306"
    max_iops: int = 0
    max_connections: int = 0
    connection_pool_enabled: bool = False  # 是否启用连接池
    create_time: Optional[datetime] = None
    tags: dict[str, str] = field(default_factory=dict)  # 标签


@dataclass
class RdsBackupPolicyRecord:
    """RDS 备份策略记录"""
    DATAITEM_NAME: ClassVar[str] = "rds.backup_policy.list"
    instance_id: str
    instance_type: Literal["MySQL", "PostgreSQL", "SQLServer", "MariaDB"] = "MySQL"
    backup_retention_period: int = 7  # 备份保留天数
    preferred_backup_time: str = ""  # 如 "02:00Z-03:00Z"
    preferred_backup_period: list[str] = field(default_factory=list)  # Monday/Tuesday/etc.
    backup_method: str = "Physical"  # Physical/Snapshot
    enable_backup_log: bool = False
    log_backup_retention_period: Union[int, str] = 7  # 支持 int 或 str 类型
    cross_backup_region: Optional[str] = ""  # 跨地域备份区域
    cross_backup_enabled: bool = False



@dataclass
class AlbListenerRecord:
    """ALB 监听器记录"""
    DATAITEM_NAME: ClassVar[str] = "alb.listener.list"
    listener_id: str
    load_balancer_id: str
    listener_protocol: str  # HTTP/HTTPS/QUIC
    listener_port: int
    default_actions: list[dict] = field(default_factory=list)
    gzip_enabled: bool = True
    http2_enabled: bool = False
    quic_config: dict = field(default_factory=dict)
    x_forwarded_for_config: dict = field(default_factory=dict)


@dataclass
class GtmAddressPoolRecord:
    """GTM (全局流量管理) 地址池记录"""
    DATAITEM_NAME: ClassVar[str] = "gtm.address_pool.list"
    pool_id: str
    pool_name: str
    instance_id: str
    type: str  # IPv4/IPv6/Domain
    min_available_addr_num: int = 1
    addresses: list[dict] = field(default_factory=list)
    monitor_status: str = ""  # OPEN/CLOSE
    lb_strategy: str = "all_rr"  # 负载均衡策略


@dataclass
class RdsProxyRecord:
    """RDS 代理记录"""
    DATAITEM_NAME: ClassVar[str] = "rds.proxy.list"
    instance_id: str
    status: Optional[str] = "Running"  # Running/Stopped/Creating


@dataclass
class OssBucketRecord:
    """OSS Bucket 记录"""
    DATAITEM_NAME: ClassVar[str] = "oss.bucket.list"
    bucket_name: str
    location: str = ""
    storage_class: str = "Standard"  # Standard/IA/Archive/ColdArchive
    acl: str = "private"  # private/public-read/public-read-write
    versioning_status: str = "Suspended"  # Enabled/Suspended
    redundancy_type: str = "LRS"  # LRS/ZRS
    encryption_enabled: bool = False
    tags: dict[str, str] = field(default_factory=dict)  # 标签


@dataclass
class OssBucketLifecycleRecord:
    """OSS Bucket 生命周期规则记录"""
    DATAITEM_NAME: ClassVar[str] = "oss.bucket.lifecycle"
    bucket_name: str
    rule_id: str
    status: Literal["Enabled", "Disabled"]
    prefix: str = ""
    expiration_days: int = 0
    transitions: list[dict] = field(default_factory=list)  # 存储类型转换规则
    abort_multipart_upload_days: int = 0
    noncurrent_version_expiration_days: int = 0

    @property
    def has_transition(self) -> bool:
        """是否有归档转储规则"""
        return len(self.transitions) > 0

    @property
    def has_expiration(self) -> bool:
        """是否有过期删除规则"""
        return self.expiration_days > 0 or self.noncurrent_version_expiration_days > 0


@dataclass
class TairInstanceModeRecord:
    """Tair/Redis 实例模式记录"""
    DATAITEM_NAME: ClassVar[str] = "tair.instance_mode.list"
    instance_id: str
    instance_name: str
    architecture_type: str  # cluster/standard/rwsplit
    is_serverless: bool = False
    pay_type: str = ""
    memory_size: int = 0  # MB
    has_ttl_config: bool = False  # 是否配置了 TTL
    region: str = ""
