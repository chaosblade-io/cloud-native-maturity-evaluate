"""
Elasticity 维度分析器

包含：
- 水平扩展 (Horizontal Scaling)
- 垂直扩展 (Vertical Scaling)
- 负载分发 (Load Distribution)
- 资源管理 (Resource Management)
"""

from .hpa import HPA_ANALYZERS
from .vpa import VPA_ANALYZERS
from .lb import LB_ANALYZERS
from .rm import RM_ANALYZERS

# 导出所有 Elasticity 维度的分析器
ELASTICITY_ANALYZERS = (
    HPA_ANALYZERS +
    VPA_ANALYZERS +
    LB_ANALYZERS +
    RM_ANALYZERS
)

__all__ = [
    "ELASTICITY_ANALYZERS",
    "HPA_ANALYZERS",
    "VPA_ANALYZERS",
    "LB_ANALYZERS",
    "RM_ANALYZERS",
]
