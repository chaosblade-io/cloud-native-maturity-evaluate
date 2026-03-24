"""
Service Architecture 维度分析器

包含：
- API 管理
- 服务通信
- 数据管理
"""

from .api import API_ANALYZERS
from .comm import COMM_ANALYZERS
from .data_mgmt import DATA_MGMT_ANALYZERS

# 导出所有 Service Architecture 维度的分析器
SERVICE_ARCH_ANALYZERS = (
    API_ANALYZERS +
    COMM_ANALYZERS +
    DATA_MGMT_ANALYZERS
)

__all__ = [
    "SERVICE_ARCH_ANALYZERS",
    "API_ANALYZERS",
    "COMM_ANALYZERS",
    "DATA_MGMT_ANALYZERS",
]
