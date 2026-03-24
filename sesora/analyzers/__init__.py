"""
SESORA 分析器模块

汇总所有维度的分析器，提供统一的注册和执行入口。
"""

from ..core.analyzer import AnalyzerRegistry

from .resilience import RESILIENCE_ANALYZERS
from .elasticity import ELASTICITY_ANALYZERS
from .automation import AUTOMATION_ANALYZERS
from .observability import OBSERVABILITY_ANALYZERS
from .serverless import SERVERLESS_ANALYZERS
from .service_arch import SERVICE_ARCH_ANALYZERS


# 所有分析器列表
ALL_ANALYZERS = (
    RESILIENCE_ANALYZERS +
    ELASTICITY_ANALYZERS +
    AUTOMATION_ANALYZERS +
    OBSERVABILITY_ANALYZERS +
    SERVERLESS_ANALYZERS +
    SERVICE_ARCH_ANALYZERS
)


def create_default_registry() -> AnalyzerRegistry:
    """
    创建包含所有默认分析器的注册表
    
    Returns:
        配置好的 AnalyzerRegistry 实例
    """
    registry = AnalyzerRegistry()
    registry.register_all(ALL_ANALYZERS)
    return registry


def get_analyzer_metadata() -> dict[str, dict]:
    """
    获取所有分析器的元数据
    
    Returns:
        字典，key -> {dimension, category, max_score}
    """
    metadata = {}
    for analyzer in ALL_ANALYZERS:
        metadata[analyzer.key()] = {
            "dimension": analyzer.dimension(),
            "category": analyzer.category(),
            "max_score": analyzer.max_score(),
            "required_data": analyzer.required_data(),
            "optional_data": analyzer.optional_data(),
        }
    return metadata


__all__ = [
    "ALL_ANALYZERS",
    "RESILIENCE_ANALYZERS",
    "ELASTICITY_ANALYZERS",
    "AUTOMATION_ANALYZERS",
    "OBSERVABILITY_ANALYZERS",
    "SERVERLESS_ANALYZERS",
    "SERVICE_ARCH_ANALYZERS",
    "create_default_registry",
    "get_analyzer_metadata",
]
