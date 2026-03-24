"""
Cloud Storage Products (云存储产品) 相关 DataItem Record 类型定义
用于统计 Serverless 数据存储类型多样性
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


@dataclass
class CloudStorageProductRecord:
    """云存储产品记录"""
    product_type: str  # RDS/PolarDB/Redis/MongoDB/OSS/TableStore/etc.
    instance_id: str
    instance_name: str = ""
    region: str = ""
    pay_type: str = ""  # Prepaid/Postpaid/Serverless
    is_serverless: bool = False  # 是否 Serverless 模式
    engine: str = ""  # MySQL/PostgreSQL/etc.
    engine_version: str = ""
    create_time: Optional[datetime] = None


@dataclass
class CloudStorageSummaryRecord:
    """云存储产品汇总记录"""
    total_products: int = 0
    product_types: list[str] = field(default_factory=list)  # 使用的产品类型
    product_type_count: int = 0  # 产品类型数量
    serverless_count: int = 0  # Serverless 模式实例数
    traditional_count: int = 0  # 传统模式实例数
    serverless_ratio: float = 0.0  # Serverless 比例
    # 各类型统计
    has_object_storage: bool = False  # OSS
    has_nosql: bool = False  # MongoDB/TableStore/Lindorm
    has_cache: bool = False  # Redis/Memcache
    has_search: bool = False  # OpenSearch/ES
    has_rdbms: bool = False  # RDS/PolarDB


@dataclass
class RdsInstanceModeRecord:
    """RDS 实例模式记录"""
    instance_id: str
    instance_name: str
    db_type: Literal["MySQL", "PostgreSQL", "SQLServer", "MariaDB"]
    pay_type: str  # Prepaid/Postpaid/Serverless
    is_serverless: bool = False
    category: str = ""  # Basic/HighAvailability/Finance/serverless
    storage_type: str = ""  # local_ssd/cloud_essd
    max_connections: int = 0
    region: str = ""


@dataclass
class TairInstanceModeRecord:
    """Tair/Redis 实例模式记录"""
    instance_id: str
    instance_name: str
    architecture_type: str  # cluster/standard/rwsplit
    is_serverless: bool = False
    pay_type: str = ""
    memory_size: int = 0  # MB
    has_ttl_config: bool = False  # 是否配置了 TTL
    region: str = ""
