"""
DataItem 基础数据类定义
平台无关数据层的核心数据结构
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from enum import Enum


class SourceStatus(str, Enum):
    OK = "ok"
    ERROR = "error"


@dataclass
class DataSource:
    """
    数据来源信息
    
    Attributes:
        collector: 采集器名称
        collected_at: 采集时间
        status: 采集状态
        records: 采集到的记录列表，实际类型由各 DataItem Schema 约束
    """
    collector: str
    collected_at: datetime
    status: SourceStatus
    records: list[Any] = field(default_factory=list)


@dataclass
class DataItem:
    """
    DataItem 基础结构
    
    Attributes:
        name: DataItem 唯一名称，如 "k8s.deployment.list"
        status: 整体可用状态 (available/unavailable/partial)
        sources: 数据来源列表，支持多来源共存
    """
    name: str
    status: Literal["available", "unavailable", "partial"]
    sources: list[DataSource] = field(default_factory=list)
