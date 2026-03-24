"""
FC (函数计算) 相关 DataItem Record 类型定义
数据来源：阿里云函数计算
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


@dataclass
class FcFunctionRecord:
    """FC 函数记录"""
    function_name: str
    runtime: str  # python3.10/nodejs18/java11/etc.
    handler: str
    memory_size: int = 512  # MB
    timeout: int = 60  # 秒
    disk_size: int = 512  # MB
    cpu: float = 0.5
    gpu_memory_size: int = 0
    environment_variables: dict[str, str] = field(default_factory=dict)
    layers: list[str] = field(default_factory=list)
    instance_concurrency: Optional[int] = None  # 部分函数可能不返回此字段
    triggers: list[dict] = field(default_factory=list)  # 触发器配置
    reserved_instances: int = 0  # 预留实例数
    log_config: dict = field(default_factory=dict)  # 日志配置
    trace_config: dict = field(default_factory=dict)  # 链路追踪配置
    custom_container_config: dict = field(default_factory=dict)  # 自定义容器配置
    last_modified_time: Optional[datetime] = None
    create_time: Optional[datetime] = None


@dataclass
class FcAliasRecord:
    """FC 别名记录"""
    alias_name: str
    version_id: str
    description: str = ""
    additional_version_weight: dict[str, float] = field(default_factory=dict)
    created_time: Optional[datetime] = None
    last_modified_time: Optional[datetime] = None


@dataclass
class FcVersionRecord:
    """FC 版本记录"""
    function_name: str
    version_id: str
    description: str = ""
    created_time: Optional[datetime] = None


@dataclass
class FcColdStartMetricRecord:
    """FC 冷启动指标记录"""
    function_name: str
    avg_cold_start_ms: float = 0.0  # 平均冷启动时间
    p99_cold_start_ms: float = 0.0  # P99 冷启动时间
    total_invocations: int = 0  # 总调用次数
    time_range_hours: int = 24  # 统计时间范围


@dataclass
class FcProvisionedConcurrencyRecord:
    """FC 预留并发配置记录"""
    function_name: str
    qualifier: str  # 版本或别名
    target: int = 0  # 目标预留并发数
    current: int = 0  # 当前预留并发数
    scheduled_actions: list[dict] = field(default_factory=list)  # 定时伸缩配置


@dataclass
class FcObservabilityConfigRecord:
    """FC 可观测性配置记录"""
    function_name: str
    log_enabled: bool = False  # 是否开启日志
    log_project: str = ""  # SLS Project
    log_store: str = ""  # SLS Logstore
    trace_enabled: bool = False  # 是否开启链路追踪
    trace_type: str = ""  # Jaeger/Zipkin/ARMS
    metrics_enabled: bool = False  # 是否开启指标
    arms_integrated: bool = False  # 是否集成 ARMS


@dataclass
class FcUsageSummaryRecord:
    """FC 使用情况汇总记录"""
    total_functions: int = 0
    total_invocations_30d: int = 0  # 近 30 天调用量
    trigger_types: list[str] = field(default_factory=list)  # 使用的触发器类型
    trigger_type_count: int = 0
    runtime_types: list[str] = field(default_factory=list)  # 使用的运行时类型
    runtime_type_count: int = 0
    functions_with_alias: int = 0  # 有别名的函数数
    functions_with_version: int = 0  # 有多版本的函数数


@dataclass
class FcFunctionStatisticsRecord:
    """FC 函数统计记录"""
    function_name: str
    invocation_count: int = 0  # 调用次数
    error_count: int = 0  # 错误次数
    avg_duration_ms: float = 0.0  # 平均执行时间
    p99_duration_ms: float = 0.0  # P99 执行时间
    concurrent_executions: int = 0  # 并发执行数
    time_range_hours: int = 24  # 统计时间范围
