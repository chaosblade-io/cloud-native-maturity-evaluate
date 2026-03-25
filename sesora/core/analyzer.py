"""
Analyzer 分析器定义

包含：
- ScoreState: 评分三态枚举
- ScoreResult: 评分结果数据类
- Analyzer: 分析器抽象基类
- AnalyzerRegistry: 分析器注册表
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from sesora.store.sqlite_store import DataStore


class ScoreState(Enum):
    """
    评分三态
    
    - SCORED: 分析已执行，得到具体分数（含 0 分）
    - NOT_SCORED: 分析已执行，条件不满足，得 0 分
    - NOT_EVALUATED: 分析未执行（数据不足），不参与得分计算
    """
    SCORED = "scored"
    NOT_SCORED = "not_scored"
    NOT_EVALUATED = "not_evaluated"


@dataclass
class ScoreResult:
    """
    评分结果
    
    Attributes:
        key: 评估项 Key，如 "ha_redundancy"
        state: 评分状态
        score: 实际得分（SCORED/NOT_SCORED 时有效，NOT_SCORED 为 0）
        max_score: 该评估项的满分
        reason: 得分/未得分/未评价的原因说明
        evidence: 支撑判断的具体数据点
    """
    key: str
    state: ScoreState
    score: int
    max_score: int
    reason: str
    evidence: list[str] = field(default_factory=list)
    
    @property
    def is_evaluated(self) -> bool:
        """是否已评估（参与得分计算）"""
        return self.state != ScoreState.NOT_EVALUATED
    
    @property
    def score_percentage(self) -> float:
        """得分百分比"""
        if self.max_score == 0:
            return 0.0
        return self.score / self.max_score * 100


class Analyzer(ABC):
    """
    分析器抽象基类
    
    每个 Analyzer 负责一个评估项（Key）的评分计算，
    声明所依赖的 DataItem，当依赖数据满足时执行分析，
    输出三态评分结果。
    """
    
    @abstractmethod
    def key(self) -> str:
        """评估项 Key，如 "ha_redundancy" """
        pass
    
    @abstractmethod
    def dimension(self) -> str:
        """所属维度，如 "Resilience" """
        pass
    
    @abstractmethod
    def category(self) -> str:
        """所属子类，如 "高可用" """
        pass
    
    @abstractmethod
    def max_score(self) -> int:
        """该评估项的满分"""
        pass
    
    @abstractmethod
    def required_data(self) -> list[str]:
        """
        必须可用的 DataItem 名称列表
        
        required_data 中任一 DataItem 不可用 → 直接返回 NOT_EVALUATED
        """
        pass
    
    def optional_data(self) -> list[str]:
        """
        可选 DataItem 名称列表
        
        缺失时 Analyzer 仍可执行，但可对依赖该数据的子项单独返回 NOT_EVALUATED
        """
        return []
    
    @abstractmethod
    def analyze(self, store: "DataStore") -> ScoreResult:
        """
        执行分析逻辑
        
        Args:
            store: DataStore 保证 required_data 全部可用时才会调用
            
        Returns:
            ScoreResult 评分结果
        """
        pass
    
    def _scored(self, score: int, reason: str, evidence: list[str] = None) -> ScoreResult:
        """快捷方法：返回 SCORED 状态的结果"""
        return ScoreResult(
            key=self.key(),
            state=ScoreState.SCORED,
            score=score,
            max_score=self.max_score(),
            reason=reason,
            evidence=evidence or []
        )
    
    def _not_scored(self, reason: str, evidence: list[str] = None) -> ScoreResult:
        """快捷方法：返回 NOT_SCORED 状态的结果（得 0 分）"""
        return ScoreResult(
            key=self.key(),
            state=ScoreState.NOT_SCORED,
            score=0,
            max_score=self.max_score(),
            reason=reason,
            evidence=evidence or []
        )
    
    def _not_evaluated(self, reason: str) -> ScoreResult:
        """快捷方法：返回 NOT_EVALUATED 状态的结果"""
        return ScoreResult(
            key=self.key(),
            state=ScoreState.NOT_EVALUATED,
            score=0,
            max_score=self.max_score(),
            reason=reason,
            evidence=[]
        )


class AnalyzerRegistry:
    """
    分析器注册表
    
    维护所有 Analyzer 的注册，支持按需执行分析。
    """
    
    def __init__(self):
        self._analyzers: list[Analyzer] = []
    
    def register(self, analyzer: Analyzer) -> None:
        """注册分析器"""
        self._analyzers.append(analyzer)
    
    def register_all(self, analyzers: list[Analyzer]) -> None:
        """批量注册分析器"""
        self._analyzers.extend(analyzers)
    
    def get_all(self) -> list[Analyzer]:
        """获取所有已注册的分析器"""
        return self._analyzers.copy()
    
    def get_by_dimension(self, dimension: str) -> list[Analyzer]:
        """按维度获取分析器"""
        return [a for a in self._analyzers if a.dimension() == dimension]
    
    def get_by_key(self, key: str) -> Optional[Analyzer]:
        """按 Key 获取分析器"""
        for a in self._analyzers:
            if a.key() == key:
                return a
        return None
    
    def run(self, store: "DataStore") -> list[ScoreResult]:
        """
        执行所有分析器
        
        对于 required_data 缺失的分析器，直接返回 NOT_EVALUATED。
        
        Args:
            store: 数据存储
            
        Returns:
            所有评分结果列表
        """
        results = []
        for analyzer in self._analyzers:
            # 检查必要数据是否可用
            missing = [d for d in analyzer.required_data() if not store.available(d)]
            if missing:
                results.append(ScoreResult(
                    key=analyzer.key(),
                    state=ScoreState.NOT_EVALUATED,
                    score=0,
                    max_score=analyzer.max_score(),
                    reason=f"缺少必要数据: {', '.join(missing)}",
                    evidence=[]
                ))
            else:
                try:
                    results.append(analyzer.analyze(store))
                except Exception as e:
                    results.append(ScoreResult(
                        key=analyzer.key(),
                        state=ScoreState.NOT_EVALUATED,
                        score=0,
                        max_score=analyzer.max_score(),
                        reason=f"分析执行异常: {str(e)}",
                        evidence=[]
                    ))
        return results
    
    def run_by_keys(self, store: "DataStore", keys: list[str]) -> list[ScoreResult]:
        """
        执行指定 Key 的分析器
        
        Args:
            store: 数据存储
            keys: 要执行的分析器 Key 列表
            
        Returns:
            评分结果列表
        """
        results = []
        for key in keys:
            analyzer = self.get_by_key(key)
            if analyzer is None:
                continue
            
            missing = [d for d in analyzer.required_data() if not store.available(d)]
            if missing:
                results.append(ScoreResult(
                    key=analyzer.key(),
                    state=ScoreState.NOT_EVALUATED,
                    score=0,
                    max_score=analyzer.max_score(),
                    reason=f"缺少必要数据: {', '.join(missing)}",
                    evidence=[]
                ))
            else:
                try:
                    results.append(analyzer.analyze(store))
                except Exception as e:
                    results.append(ScoreResult(
                        key=analyzer.key(),
                        state=ScoreState.NOT_EVALUATED,
                        score=0,
                        max_score=analyzer.max_score(),
                        reason=f"分析执行异常: {str(e)}",
                        evidence=[]
                    ))
        return results
