"""
Grafana 可视化相关 DataItem Record 类型定义
数据来源：ARMS Grafana / 云监控 Dashboard
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


@dataclass
class GrafanaDashboardRecord:
    """Grafana 仪表盘记录"""
    uid: str
    title: str
    folder_id: int = 0
    folder_title: str = ""
    tags: list[str] = field(default_factory=list)
    panels_count: int = 0
    refresh_interval: str = ""  # 如 "5s", "1m"
    time_range: str = ""  # 如 "now-6h", "now-7d"
    has_templating: bool = False  # 是否有变量模板
    templating_vars: list[str] = field(default_factory=list)
    variable_count: int = 0  # 变量数量
    has_alerts: bool = False  # 是否配置告警
    alert_rules_count: int = 0
    alert_count: int = 0  # 告警数量
    has_drill_down: bool = False  # 是否有下钻链接
    has_links: bool = False  # 是否有链接（下钻）
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None


@dataclass
class GrafanaFolderRecord:
    """Grafana 文件夹记录（用于角色视图）"""
    id: int
    uid: str
    title: str
    dashboard_count: int = 0
    permissions: list[dict] = field(default_factory=list)  # 权限配置
    create_time: Optional[datetime] = None


@dataclass
class GrafanaPanelRecord:
    """Grafana 面板记录"""
    dashboard_uid: str
    panel_id: int
    title: str
    panel_type: str  # graph/stat/table/heatmap/etc.
    datasource: str = ""
    targets: list[dict] = field(default_factory=list)  # 查询目标
    has_alert: bool = False
    links: list[dict] = field(default_factory=list)  # 下钻链接


@dataclass
class GrafanaAlertRuleRecord:
    """Grafana 告警规则记录"""
    uid: str
    title: str
    folder_uid: str
    condition: str = ""
    for_duration: str = ""  # 持续时间触发
    annotations: dict = field(default_factory=dict)
    labels: dict = field(default_factory=dict)
    notification_channels: list[str] = field(default_factory=list)
    state: str = ""  # OK/Alerting/Pending/NoData
    create_time: Optional[datetime] = None


@dataclass
class GrafanaDashboardAnalysisRecord:
    """Grafana 仪表盘分析汇总记录"""
    total_dashboards: int = 0
    system_dashboards: int = 0  # 系统指标仪表盘
    app_dashboards: int = 0  # 应用指标仪表盘
    business_dashboards: int = 0  # 业务指标仪表盘
    ux_dashboards: int = 0  # 用户体验仪表盘
    realtime_dashboards: int = 0  # 实时仪表盘（刷新间隔 <= 15s）
    dashboards_with_alerts: int = 0  # 有告警的仪表盘
    dashboards_with_drilldown: int = 0  # 有下钻的仪表盘
    folders_count: int = 0  # 文件夹数量（角色隔离）


@dataclass
class MetricIntervalRecord:
    """指标采集间隔记录"""
    metric_source: str  # prometheus/arms/cms
    metric_name: str
    interval_seconds: int = 60  # 采集间隔（秒）
    retention_days: int = 15  # 保留天数
    is_realtime: bool = False  # 是否实时（<= 15s）
