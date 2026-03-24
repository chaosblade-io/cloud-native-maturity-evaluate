"""
Observability 维度分析器

包含：
- 监控 (Monitoring)
- 日志 (Logging)
- 链路追踪 (Tracing)
- 可视化 (Visualization)
"""

from .monitoring import MONITORING_ANALYZERS
from .logging import LOGGING_ANALYZERS
from .tracing import TRACING_ANALYZERS
from .visualization import VISUALIZATION_ANALYZERS

# 导出所有 Observability 维度的分析器
OBSERVABILITY_ANALYZERS = (
    MONITORING_ANALYZERS +
    LOGGING_ANALYZERS +
    TRACING_ANALYZERS +
    VISUALIZATION_ANALYZERS
)

__all__ = [
    "OBSERVABILITY_ANALYZERS",
    "MONITORING_ANALYZERS",
    "LOGGING_ANALYZERS",
    "TRACING_ANALYZERS",
    "VISUALIZATION_ANALYZERS",
]
