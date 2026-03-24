"""
Chaos Engineering (混沌工程) 相关 DataItem Record 类型定义
数据来源：ACK 托管版 Chaos Mesh / AHAS
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


@dataclass
class ChaosExperimentRecord:
    """混沌实验记录"""
    experiment_id: str
    experiment_name: str
    experiment_type: Literal["PodChaos", "NetworkChaos", "IOChaos", "StressChaos", 
                             "TimeChaos", "KernelChaos", "DNSChaos", "HTTPChaos"]
    namespace: str
    target_selector: dict = field(default_factory=dict)  # 目标选择器
    action: str = ""  # pod-kill/pod-failure/network-delay/etc.
    duration: str = ""  # 持续时间，如 "30s"
    schedule: str = ""  # Cron 表达式，定期执行
    status: str = ""  # Running/Paused/Finished/Failed
    create_time: Optional[datetime] = None
    last_run_time: Optional[datetime] = None


@dataclass
class ChaosExperimentRunRecord:
    """混沌实验执行记录"""
    experiment_id: str
    run_id: str
    status: str = ""  # Running/Finished/Failed/Paused
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    affected_pods: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)  # 执行过程中的事件
    result_summary: str = ""


@dataclass
class ChaosScheduleRecord:
    """混沌实验调度记录"""
    schedule_id: str
    schedule_name: str
    namespace: str
    schedule_type: str  # Immediate/Once/Cron
    cron_expression: str = ""
    experiments: list[dict] = field(default_factory=list)  # 关联的实验列表
    enabled: bool = True
    create_time: Optional[datetime] = None


@dataclass
class ChaosWorkflowRecord:
    """混沌工作流记录（多个实验组合）"""
    workflow_id: str
    workflow_name: str
    namespace: str
    entry: str  # 入口节点
    templates: list[dict] = field(default_factory=list)  # 工作流模板
    status: str = ""
    create_time: Optional[datetime] = None
    last_run_time: Optional[datetime] = None
