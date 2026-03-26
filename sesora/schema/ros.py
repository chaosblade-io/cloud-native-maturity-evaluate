"""
ROS (资源编排服务) 相关 DataItem Record 类型定义
数据来源：阿里云 ROS
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar, Optional

@dataclass
class RosStackDriftRecord:
    """ROS 堆栈漂移检测记录"""
    DATAITEM_NAME: ClassVar[str] = "ros.stack.drift"
    stack_id: str
    stack_name: str
    drift_status: str  # IN_SYNC/DRIFTED/NOT_CHECKED
    drift_detection_time: Optional[datetime] = None
    drifted_resources: list[dict] = field(default_factory=list)  # 漂移的资源列表
    total_resources: int = 0
    drifted_count: int = 0


@dataclass
class RosStackRecord:
    """ROS (资源编排服务) 堆栈记录"""
    DATAITEM_NAME: ClassVar[str] = "ros.stack.list"
    stack_id: str
    stack_name: str
    status: str  # CREATE_COMPLETE/UPDATE_COMPLETE/etc.
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None
    timeout_in_minutes: int = 60
    disable_rollback: bool = False
    deletion_protection: str = "Disabled"  # Enabled/Disabled
    drift_detection_time: Optional[datetime] = None
    drift_status: Optional[str] = ""  # IN_SYNC/DRIFTED/NOT_CHECKED
    tags: dict[str, str] = field(default_factory=dict)
