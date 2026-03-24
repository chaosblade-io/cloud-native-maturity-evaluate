"""
Resilience 维度分析器

包含：
- 高可用 (High Availability)
- 容错 (Fault Tolerance)
- 灾难恢复 (Disaster Recovery)
- 健康管理 (Health Management)
"""

from .ha import HA_ANALYZERS
from .fault_tolerance import FAULT_TOLERANCE_ANALYZERS
from .dr import DR_ANALYZERS
from .health import HEALTH_ANALYZERS

# 导出所有 Resilience 维度的分析器
RESILIENCE_ANALYZERS = (
    HA_ANALYZERS +
    FAULT_TOLERANCE_ANALYZERS +
    DR_ANALYZERS +
    HEALTH_ANALYZERS
)

__all__ = [
    "RESILIENCE_ANALYZERS",
    "HA_ANALYZERS",
    "FAULT_TOLERANCE_ANALYZERS",
    "DR_ANALYZERS",
    "HEALTH_ANALYZERS",
]
