"""
SESORA 成熟度评估系统

云原生架构成熟度评估工具，基于 SESORA 六维度模型：
- Serverless
- Elasticity
- Service Architecture
- Observability
- Resilience
- Automation
"""

__version__ = "0.1.0"

from .core import (
    AssessmentContext,
    DataItem,
    DataSource,
    Analyzer,
    AnalyzerRegistry,
    ScoreResult,
    ScoreState,
    AssessmentReport,
    DimensionReport,
    CategoryReport,
    SummaryStats,
)

from .store import (
    DataStore,
    SQLiteDataStore,
)

from .engine import (
    AssessmentEngine,
    AssessmentTask,
    quick_assess,
)

from .analyzers import (
    ALL_ANALYZERS,
    create_default_registry,
    get_analyzer_metadata,
)

__all__ = [
    # Version
    "__version__",
    # Core
    "AssessmentContext",
    "Credentials",
    "DataItem",
    "DataSource",
    "Analyzer",
    "AnalyzerRegistry",
    "ScoreResult",
    "ScoreState",
    "AssessmentReport",
    "DimensionReport",
    "CategoryReport",
    "SummaryStats",
    # Store
    "DataStore",
    "SQLiteDataStore",
    # Engine
    "AssessmentEngine",
    "AssessmentTask",
    "quick_assess",
    # Analyzers
    "ALL_ANALYZERS",
    "create_default_registry",
    "get_analyzer_metadata",
]
