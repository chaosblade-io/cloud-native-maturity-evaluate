"""
CMS (云监控) 相关 DataItem Record 类型定义
数据来源：阿里云 CMS
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


@dataclass
class CmsAlarmRuleRecord:
    """CMS 告警规则记录"""
    rule_id: str
    rule_name: str
    namespace: str  # acs_ecs_dashboard/acs_rds_dashboard/etc.
    metric_name: str
    expression: str
    level: Literal["Critical", "Warning", "Info"]
    enable_state: bool = True
    action_types: list[str] = field(default_factory=list)  # webhook/function/contact_group
    contact_groups: list[str] = field(default_factory=list)
    webhook_url: str = ""
    silence_time: int = 86400  # 静默时间(秒)，默认1天
    effective_time: str = "00:00-23:59"  # 生效时间
    has_notification: bool = True  # 是否配置通知


@dataclass
class CmsContactRecord:
    """CMS 联系人记录"""
    contact_name: str
    channels: list[str] = field(default_factory=list)  # SMS/Email/DingTalk
    phone: str = ""
    email: str = ""
    dingtalk_webhook: Optional[str] = None
    desc: str = ""


@dataclass
class CmsContactGroupRecord:
    """CMS 联系组记录"""
    group_name: str
    contacts: list[str] = field(default_factory=list)  # 联系人名称列表
    enable_subscribed: bool = False
    describe: Optional[str] = None


@dataclass
class CmsAlarmSloRecord:
    """CMS 告警规则 SLO 分析记录"""
    rule_id: str
    rule_name: str
    is_slo_based: bool = False  # 是否基于 SLO
    has_multi_window: bool = False  # 是否使用多窗口燃烧率
    has_burn_rate: bool = False  # 是否使用燃烧率
    expression_type: str = "threshold"  # threshold/slo/predictive
    has_predictive: bool = False  # 是否有预测性表达式


@dataclass
class CmsAlarmChannelSummaryRecord:
    """CMS 告警通道汇总记录"""
    total_contacts: int = 0
    channel_types: list[str] = field(default_factory=list)  # SMS/Email/DingTalk/Phone/Webhook
    channel_count: int = 0  # 通道类型数量
    has_sms: bool = False
    has_email: bool = False
    has_dingtalk: bool = False
    has_phone: bool = False
    has_webhook: bool = False


@dataclass
class CmsEventTriggerRecord:
    """云监控事件触发器记录"""
    trigger_name: str
    enabled: bool = True


@dataclass
class CmsAlarmHistoryRecord:
    """云监控告警历史记录"""
    alarm_id: str
    alarm_name: str
    rule_id: str
    rule_name: str
    level: str = "Warning"  # Critical/Warning/Info
    message: str = ""
    namespace: str = ""
    metric_name: str = ""
    dimensions: dict = field(default_factory=dict)
    timestamp: Optional[datetime] = None
