"""
AssessmentReport 评估报告定义

包含：
- CategoryReport: 子类评分报告
- DimensionReport: 维度评分报告
- AssessmentReport: 完整评估报告
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .analyzer import ScoreResult, ScoreState
from .context import AssessmentContext


@dataclass
class CategoryReport:
    """
    子类评分报告
    
    如 "CI/CD 流水线"、"高可用" 等
    """
    category: str
    items: list[ScoreResult] = field(default_factory=list)
    
    @property
    def category_score(self) -> int:
        """子类实际得分（仅计算已评估项）"""
        return sum(r.score for r in self.items if r.is_evaluated)
    
    @property
    def category_max(self) -> int:
        """子类满分（仅计算已评估项）"""
        return sum(r.max_score for r in self.items if r.is_evaluated)
    
    @property
    def evaluated_count(self) -> int:
        """已评估项数量"""
        return sum(1 for r in self.items if r.is_evaluated)
    
    @property
    def not_evaluated_count(self) -> int:
        """未评估项数量"""
        return sum(1 for r in self.items if not r.is_evaluated)
    
    @property
    def score_percentage(self) -> float:
        """得分百分比"""
        if self.category_max == 0:
            return 0.0
        return self.category_score / self.category_max * 100


@dataclass
class DimensionReport:
    """
    维度评分报告
    
    如 "Automation"、"Resilience" 等
    """
    dimension: str
    categories: list[CategoryReport] = field(default_factory=list)
    
    @property
    def dimension_score(self) -> int:
        """维度实际得分"""
        return sum(c.category_score for c in self.categories)
    
    @property
    def dimension_max(self) -> int:
        """维度满分"""
        return sum(c.category_max for c in self.categories)
    
    @property
    def evaluated_count(self) -> int:
        """已评估项数量"""
        return sum(c.evaluated_count for c in self.categories)
    
    @property
    def not_evaluated_count(self) -> int:
        """未评估项数量"""
        return sum(c.not_evaluated_count for c in self.categories)
    
    @property
    def total_items(self) -> int:
        """总评估项数量"""
        return sum(len(c.items) for c in self.categories)
    
    @property
    def score_percentage(self) -> float:
        """得分百分比"""
        if self.dimension_max == 0:
            return 0.0
        return self.dimension_score / self.dimension_max * 100
    
    @property
    def coverage_ratio(self) -> float:
        """评估覆盖率"""
        total = self.total_items
        if total == 0:
            return 0.0
        return self.evaluated_count / total * 100


@dataclass
class SummaryStats:
    """评估汇总统计"""
    # 得分统计（仅含已分析项）
    evaluated_score: int = 0
    evaluated_max: int = 0
    maturity_percentage: float = 0.0
    
    # 覆盖率统计
    total_items: int = 0
    evaluated_items: int = 0
    not_evaluated_items: int = 0
    coverage_ratio: float = 0.0
    
    # 各维度汇总
    by_dimension: dict = field(default_factory=dict)


@dataclass
class AssessmentReport:
    """
    完整评估报告
    
    包含所有维度的评分结果和汇总统计。
    """
    task_id: str
    target: Optional[AssessmentContext] = None
    executed_at: Optional[datetime] = None
    dimensions: list[DimensionReport] = field(default_factory=list)
    summary: Optional[SummaryStats] = None
    
    @classmethod
    def from_results(
        cls,
        task_id: str,
        results: list[ScoreResult],
        analyzer_metadata: dict[str, dict],  # key -> {dimension, category}
        target: AssessmentContext = None
    ) -> "AssessmentReport":
        """
        从评分结果构建报告
        
        Args:
            task_id: 任务 ID
            results: 评分结果列表
            analyzer_metadata: 分析器元数据，key -> {dimension, category}
            target: 评估上下文
            
        Returns:
            AssessmentReport 实例
        """
        # 按维度和子类分组
        dimension_map: dict[str, dict[str, list[ScoreResult]]] = {}
        
        for result in results:
            meta = analyzer_metadata.get(result.key, {})
            dimension = meta.get("dimension", "Unknown")
            category = meta.get("category", "Unknown")
            
            if dimension not in dimension_map:
                dimension_map[dimension] = {}
            if category not in dimension_map[dimension]:
                dimension_map[dimension][category] = []
            
            dimension_map[dimension][category].append(result)
        
        # 构建维度报告
        dimensions = []
        for dim_name, categories in dimension_map.items():
            cat_reports = [
                CategoryReport(category=cat_name, items=items)
                for cat_name, items in categories.items()
            ]
            dimensions.append(DimensionReport(dimension=dim_name, categories=cat_reports))
        
        # 计算汇总统计
        summary = cls._calculate_summary(results, dimensions)
        
        return cls(
            task_id=task_id,
            target=target,
            executed_at=datetime.now(),
            dimensions=dimensions,
            summary=summary
        )
    
    @staticmethod
    def _calculate_summary(results: list[ScoreResult], dimensions: list[DimensionReport]) -> SummaryStats:
        """计算汇总统计"""
        evaluated_results = [r for r in results if r.is_evaluated]
        
        evaluated_score = sum(r.score for r in evaluated_results)
        evaluated_max = sum(r.max_score for r in evaluated_results)
        
        total_items = len(results)
        evaluated_items = len(evaluated_results)
        not_evaluated_items = total_items - evaluated_items
        
        maturity_percentage = (evaluated_score / evaluated_max * 100) if evaluated_max > 0 else 0.0
        coverage_ratio = (evaluated_items / total_items * 100) if total_items > 0 else 0.0
        
        # 各维度汇总
        by_dimension = {}
        for dim in dimensions:
            by_dimension[dim.dimension] = {
                "evaluated_score": dim.dimension_score,
                "evaluated_max": dim.dimension_max,
                "score_percentage": dim.score_percentage,
                "coverage_ratio": dim.coverage_ratio,
            }
        
        return SummaryStats(
            evaluated_score=evaluated_score,
            evaluated_max=evaluated_max,
            maturity_percentage=maturity_percentage,
            total_items=total_items,
            evaluated_items=evaluated_items,
            not_evaluated_items=not_evaluated_items,
            coverage_ratio=coverage_ratio,
            by_dimension=by_dimension
        )
    
    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "task_id": self.task_id,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "summary": {
                "evaluated_score": self.summary.evaluated_score if self.summary else 0,
                "evaluated_max": self.summary.evaluated_max if self.summary else 0,
                "maturity_percentage": round(self.summary.maturity_percentage, 2) if self.summary else 0,
                "total_items": self.summary.total_items if self.summary else 0,
                "evaluated_items": self.summary.evaluated_items if self.summary else 0,
                "not_evaluated_items": self.summary.not_evaluated_items if self.summary else 0,
                "coverage_ratio": round(self.summary.coverage_ratio, 2) if self.summary else 0,
                "by_dimension": self.summary.by_dimension if self.summary else {},
            },
            "dimensions": [
                {
                    "dimension": dim.dimension,
                    "dimension_score": dim.dimension_score,
                    "dimension_max": dim.dimension_max,
                    "score_percentage": round(dim.score_percentage, 2),
                    "categories": [
                        {
                            "category": cat.category,
                            "category_score": cat.category_score,
                            "category_max": cat.category_max,
                            "score_percentage": round(cat.score_percentage, 2),
                            "items": [
                                {
                                    "key": item.key,
                                    "state": item.state.value,
                                    "score": item.score,
                                    "max_score": item.max_score,
                                    "reason": item.reason,
                                    "evidence": item.evidence,
                                }
                                for item in cat.items
                            ]
                        }
                        for cat in dim.categories
                    ]
                }
                for dim in self.dimensions
            ]
        }
