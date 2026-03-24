"""
Serverless 维度分析器

包含：
- FaaS (函数即服务)
- EDA (事件驱动架构)
- Data (数据服务)
"""

from .faas import FAAS_ANALYZERS
from .eda import EDA_ANALYZERS
from .data import DATA_ANALYZERS

# 导出所有 Serverless 维度的分析器
SERVERLESS_ANALYZERS = (
    FAAS_ANALYZERS +
    EDA_ANALYZERS +
    DATA_ANALYZERS
)

__all__ = [
    "SERVERLESS_ANALYZERS",
    "FAAS_ANALYZERS",
    "EDA_ANALYZERS",
    "DATA_ANALYZERS",
]
