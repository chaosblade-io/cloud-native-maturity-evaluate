"""
SESORA Core Module

核心模块，包含：
- AssessmentContext: 评估上下文
- Analyzer: 分析器基类和注册表
- Report: 评估报告
- DataItem: 数据项基础结构
"""

from .context import AssessmentContext
from .dataitem import DataItem, DataSource
from .analyzer import Analyzer, AnalyzerRegistry, ScoreResult, ScoreState
from .report import AssessmentReport, DimensionReport, CategoryReport, SummaryStats

__all__ = [
    # Context
    "AssessmentContext",
    # DataItem
    "DataItem",
    "DataSource",
    # Analyzer
    "Analyzer",
    "AnalyzerRegistry",
    "ScoreResult",
    "ScoreState",
    # Report
    "AssessmentReport",
    "DimensionReport",
    "CategoryReport",
    "SummaryStats",
]
