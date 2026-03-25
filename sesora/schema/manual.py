"""
人工填写/问卷数据 相关 DataItem Record 类型定义
用于无法自动化采集的评估项
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


@dataclass
class ManualQuestionnaireRecord:
    """人工问卷记录（通用）"""
    question_key: str  # 对应评估项 Key
    question_text: str  # 问题描述
    answer: str = ""  # 回答内容
    answer_type: str = "text"  # text/boolean/enum/number
    evidence: str = ""  # 证据描述或链接
    answered_by: str = ""  # 填写人
    answered_at: Optional[datetime] = None


@dataclass
class ManualFallbackConfigRecord:
    """降级机制配置记录（ft_fallback）"""
    service_name: str
    has_fallback: bool = False
    fallback_type: str = ""  # cache/default_value/simplified_flow/circuit_breaker
    fallback_description: str = ""
    dependencies_covered: list[str] = field(default_factory=list)  # 覆盖的依赖
    evidence: str = ""


@dataclass
class ManualBulkheadConfigRecord:
    """舱壁模式配置记录（ft_bulkhead）"""
    service_name: str
    has_bulkhead: bool = False
    thread_pool_isolation: bool = False  # 线程池隔离
    connection_pool_isolation: bool = False  # 连接池隔离
    semaphore_isolation: bool = False  # 信号量隔离
    isolation_description: str = ""
    evidence: str = ""


@dataclass
class ManualDrPlanRecord:
    """灾难恢复计划记录（dr_recovery_plan）"""
    has_dr_plan: bool = False
    plan_document_url: str = ""  # 计划文档链接
    last_updated: Optional[datetime] = None
    steps_defined: bool = False  # 是否有明确步骤
    roles_assigned: bool = False  # 是否分配角色
    communication_plan: bool = False  # 是否有通信计划
    evidence: str = ""


@dataclass
class ManualRtoRpoRecord:
    """RTO/RPO 定义记录（dr_rto_rpo_defined）"""
    service_name: str
    rto_defined: bool = False
    rto_minutes: int = 0  # 恢复时间目标（分钟）
    rpo_defined: bool = False
    rpo_minutes: int = 0  # 恢复点目标（分钟）
    architecture_supports: bool = False  # 架构是否支持
    evidence: str = ""


@dataclass
class ManualDrTestingRecord:
    """灾难恢复演练记录（dr_recovery_testing）"""
    has_testing: bool = False
    last_test_date: Optional[datetime] = None
    test_type: str = ""  # tabletop/partial/full
    test_scope: str = ""  # 演练范围
    issues_found: int = 0
    issues_resolved: int = 0
    improvement_report: bool = False  # 是否有改进报告
    evidence: str = ""


@dataclass
class ManualDataConsistencyRecord:
    """数据一致性模型记录（data_consistency_model）"""
    service_name: str
    consistency_model: str = ""  # strong/eventual/mixed
    uses_saga: bool = False  # 是否使用 Saga 模式
    uses_tcc: bool = False  # 是否使用 TCC 模式
    uses_distributed_lock: bool = False  # 是否使用分布式锁
    consistency_description: str = ""
    evidence: str = ""


@dataclass
class ManualDataOwnershipRecord:
    """数据所有权记录（data_ownership_clear）"""
    table_or_collection: str
    owner_service: str  # 唯一写入者
    read_only_services: list[str] = field(default_factory=list)  # 只读服务
    access_via_api: bool = False  # 是否通过 API 访问
    evidence: str = ""


@dataclass
class ManualDataMigrationRecord:
    """在线数据迁移能力记录（data_migration_strategy）"""
    has_capability: bool = False
    supports_dual_write: bool = False  # 支持双写
    supports_grayscale: bool = False  # 支持灰度切换
    supports_online_ddl: bool = False  # 支持在线 DDL
    tools_used: list[str] = field(default_factory=list)  # 使用的工具
    evidence: str = ""


@dataclass
class ManualConfigManagementRecord:
    """配置管理工具记录（configuration_management）"""
    has_config_mgmt: bool = False
    tool_type: str = ""  # ansible/salt/puppet/chef
    agent_installed: bool = False  # 是否安装 Agent
    periodic_sync: bool = False  # 是否定期同步
    servers_covered: int = 0  # 覆盖的服务器数量
    evidence: str = ""


@dataclass
class ManualConsistencyModelRecord:
    """一致性模型适配记录（sd_consistency_model）"""
    has_assessment: bool = False  # 是否进行过评估
    strong_consistency_scenarios: list[str] = field(default_factory=list)  # 强一致性场景
    eventual_consistency_handled: bool = False  # 最终一致性场景是否已处理
    consistent_read_configured: bool = False  # 是否配置了强一致性读取
    data_risk_identified: bool = False  # 是否识别了数据风险
    evidence: str = ""
