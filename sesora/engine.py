"""
SESORA 评估引擎

提供完整的评估流程执行能力。
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .core.context import AssessmentContext
from .core.analyzer import AnalyzerRegistry, ScoreResult
from .core.report import AssessmentReport
from .store.sqlite_store import SQLiteDataStore
from .analyzers import create_default_registry, get_analyzer_metadata


@dataclass
class AssessmentTask:
    """评估任务"""
    task_id: str
    context: AssessmentContext
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    status: str = "pending"  # pending, running, completed, failed
    error_message: str = ""


class AssessmentEngine:
    """
    评估引擎
    
    负责协调整个评估流程：
    1. 数据采集（通过 Collector）
    2. 分析评分（通过 Analyzer）
    3. 报告生成
    """
    
    def __init__(self, store: SQLiteDataStore = None, registry: AnalyzerRegistry = None):
        """
        初始化评估引擎
        
        Args:
            store: 数据存储，如果不提供则创建内存存储
            registry: 分析器注册表，如果不提供则使用默认注册表
        """
        self.store = store or SQLiteDataStore()
        self.registry = registry or create_default_registry()
        self._metadata = get_analyzer_metadata()
    
    def create_task(self, context: AssessmentContext) -> AssessmentTask:
        """
        创建评估任务
        
        Args:
            context: 评估上下文
            
        Returns:
            AssessmentTask 实例
        """
        task_id = str(uuid.uuid4())[:8]
        return AssessmentTask(task_id=task_id, context=context)
    
    def run_analysis(self, task: AssessmentTask, keys: list[str] = None) -> AssessmentReport:
        """
        执行分析评估
        
        假设数据已通过 Collector 采集到 Store 中。
        
        Args:
            task: 评估任务
            keys: 要执行的分析器 Key 列表，None 表示执行全部
            
        Returns:
            AssessmentReport 评估报告
        """
        task.status = "running"
        task.started_at = datetime.now()
        
        try:
            # 执行分析
            if keys:
                results = self.registry.run_by_keys(self.store, keys)
            else:
                results = self.registry.run(self.store)
            
            # 生成报告
            report = AssessmentReport.from_results(
                task_id=task.task_id,
                results=results,
                analyzer_metadata=self._metadata,
                target=task.context
            )
            
            task.status = "completed"
            task.finished_at = datetime.now()
            
            return report
            
        except Exception as e:
            task.status = "failed"
            task.error_message = str(e)
            task.finished_at = datetime.now()
            raise
    
    def get_data_requirements(self, keys: list[str] = None) -> dict:
        """
        获取指定分析器的数据需求
        
        Args:
            keys: 分析器 Key 列表，None 表示全部
            
        Returns:
            数据需求汇总 {required: set, optional: set}
        """
        required = set()
        optional = set()
        
        analyzers = self.registry.get_all()
        if keys:
            analyzers = [a for a in analyzers if a.key() in keys]
        
        for analyzer in analyzers:
            required.update(analyzer.required_data())
            optional.update(analyzer.optional_data())
        
        # 移除已在 required 中的 optional
        optional = optional - required
        
        return {
            "required": required,
            "optional": optional
        }
    
    def check_data_readiness(self, keys: list[str] = None) -> dict:
        """
        检查数据就绪状态
        
        Args:
            keys: 分析器 Key 列表，None 表示全部
            
        Returns:
            数据就绪状态 {name: available}
        """
        requirements = self.get_data_requirements(keys)
        all_data = requirements["required"] | requirements["optional"]
        
        status = {}
        for name in all_data:
            status[name] = self.store.available(name)
        
        return status
    
    def get_analyzable_items(self) -> list[str]:
        """
        获取当前可执行分析的评估项 Key
        
        Returns:
            可执行的 Key 列表
        """
        analyzable = []
        
        for analyzer in self.registry.get_all():
            required = analyzer.required_data()
            if self.store.all_available(required):
                analyzable.append(analyzer.key())
        
        return analyzable
    
    def get_summary_stats(self) -> dict:
        """
        获取引擎统计信息
        
        Returns:
            统计信息字典
        """
        analyzers = self.registry.get_all()
        
        by_dimension = {}
        for analyzer in analyzers:
            dim = analyzer.dimension()
            if dim not in by_dimension:
                by_dimension[dim] = {"count": 0, "max_score": 0}
            by_dimension[dim]["count"] += 1
            by_dimension[dim]["max_score"] += analyzer.max_score()
        
        total_max_score = sum(a.max_score() for a in analyzers)
        
        return {
            "total_analyzers": len(analyzers),
            "total_max_score": total_max_score,
            "by_dimension": by_dimension
        }


# 便捷函数
def quick_assess(store: SQLiteDataStore, context: AssessmentContext = None) -> AssessmentReport:
    """
    快速执行评估
    
    Args:
        store: 数据存储（需已填充数据）
        context: 评估上下文（可选）
        
    Returns:
        AssessmentReport 评估报告
    """
    engine = AssessmentEngine(store=store)
    task = engine.create_task(context or AssessmentContext())
    return engine.run_analysis(task)
