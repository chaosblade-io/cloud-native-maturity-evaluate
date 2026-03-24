from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class AcrRepositoryRecord:
    """ACR 镜像仓库记录"""

    instance_id: str
    repo_id: str
    repo_name: str
    repo_namespace: str
    repo_type: str = "PUBLIC"  # PUBLIC/PRIVATE
    summary: str = ""
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None


@dataclass
class AcrImageRecord:
    """ACR 镜像记录"""

    instance_id: str
    repo_id: str
    image_id: Optional[str] = ""
    digest: str = ""
    tag: str = ""
    size: int = 0
    push_time: Optional[datetime] = None


@dataclass
class AcrScanResultRecord:
    """ACR 镜像扫描结果记录"""
    instance_id: str
    repo_id: str
    tag: str
    high_severity_count: int = 0
    medium_severity_count: int = 0
    low_severity_count: int = 0
    unknown_severity_count: int = 0


# 别名
AcrImageScanResultRecord = AcrScanResultRecord
