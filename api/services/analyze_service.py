"""
分析服务

封装评估分析逻辑，复用 engine.py 和 run_analyzer.py 中的分析器
"""
import sys
from pathlib import Path
from typing import Optional

from api.models.schemas import (
    AnalyzerInfo,
    AnalyzeResult,
    DimensionSummary,
    DataItemStatus,
)

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class AnalyzeService:
    """分析服务类"""
    
    # 数据库路径
    DB_DIR = PROJECT_ROOT / "data"
    DEFAULT_DB = DB_DIR / "sesora.db"
    
    @classmethod
    def get_maturity_level(cls, percentage: float) -> str:
        """
        根据百分比返回成熟度等级
        
        分级标准:
        - 无: 0%
        - 基础: 1-25%
        - 标准: 26-50%
        - 高级: 51-75%
        - 全面: 76-100%
        """
        if percentage <= 0:
            return "无"
        elif percentage <= 25:
            return "基础"
        elif percentage <= 50:
            return "标准"
        elif percentage <= 75:
            return "高级"
        else:
            return "全面"
    
    @classmethod
    def get_analyzer_list(cls) -> list[AnalyzerInfo]:
        """获取所有可用的分析器列表"""
        from sesora.analyzers import get_analyzer_metadata
        
        metadata = get_analyzer_metadata()
        analyzers = []
        
        for key, info in metadata.items():
            analyzers.append(AnalyzerInfo(
                key=key,
                dimension=info["dimension"],
                category=info["category"],
                max_score=info["max_score"],
                required_data=info["required_data"],
                optional_data=info["optional_data"],
            ))
        
        # 按维度和 key 排序
        analyzers.sort(key=lambda x: (x.dimension, x.key))
        return analyzers
    
    @classmethod
    def get_data_status(
        cls,
        keys: list[str] = None,
        db_name: str = "sesora.db",
    ) -> tuple[list[DataItemStatus], list[DataItemStatus], list[DataItemStatus]]:
        """
        获取数据就绪状态
        
        Args:
            keys: 分析器 key 列表，None 表示全部
            db_name: 数据库文件名
            
        Returns:
            (all_items, required_items, optional_items) 三元组
        """
        from sesora.store.sqlite_store import SQLiteDataStore
        from sesora.engine import AssessmentEngine
        
        db_path = cls.DB_DIR / db_name
        
        if not db_path.exists():
            return [], [], []
        
        with SQLiteDataStore(db_path) as store:
            engine = AssessmentEngine(store=store)
            
            # 获取数据库中所有数据项
            all_items_names = store.list_dataitems()
            all_items = []
            for name in all_items_names:
                records = store.get(name)
                all_items.append(DataItemStatus(
                    name=name,
                    available=store.available(name),
                    records_count=len(records),
                ))
            
            # 获取分析器的数据需求
            requirements = engine.get_data_requirements(keys)
            
            required_items = []
            for name in sorted(requirements["required"]):
                available = store.available(name)
                records = store.get(name) if available else []
                required_items.append(DataItemStatus(
                    name=name,
                    available=available,
                    records_count=len(records),
                ))
            
            optional_items = []
            for name in sorted(requirements["optional"]):
                available = store.available(name)
                records = store.get(name) if available else []
                optional_items.append(DataItemStatus(
                    name=name,
                    available=available,
                    records_count=len(records),
                ))
        
        return all_items, required_items, optional_items
    
    @classmethod
    def run_analysis(
        cls,
        keys: list[str] = None,
        db_name: str = "sesora.db",
    ) -> tuple[list[AnalyzeResult], list[DimensionSummary], int, int, float, str]:
        """
        执行评估分析
        
        Args:
            keys: 要执行的分析器 key 列表，None 表示全部
            db_name: 数据库文件名
            
        Returns:
            (results, summary, total_score, total_max, percentage, maturity) 元组
        """
        from sesora.store.sqlite_store import SQLiteDataStore
        from sesora.engine import AssessmentEngine
        from sesora.core.analyzer import ScoreState
        from sesora.analyzers import get_analyzer_metadata
        
        db_path = cls.DB_DIR / db_name
        
        if not db_path.exists():
            raise FileNotFoundError(f"数据库文件不存在: {db_path}")
        
        with SQLiteDataStore(db_path) as store:
            engine = AssessmentEngine(store=store)
            metadata = get_analyzer_metadata()
            
            # 确定要执行的分析器
            if not keys:
                all_analyzers = engine.registry.get_all()
                keys = [a.key() for a in all_analyzers]
            
            # 执行分析
            score_results = engine.registry.run_by_keys(store, keys)
            
            # 转换结果
            results = []
            for r in score_results:
                info = metadata.get(r.key, {})
                pct = (r.score / r.max_score * 100) if r.max_score > 0 else 0
                
                results.append(AnalyzeResult(
                    key=r.key,
                    dimension=info.get("dimension", ""),
                    category=info.get("category", ""),
                    state=r.state.value if hasattr(r.state, "value") else str(r.state),
                    score=r.score,
                    max_score=r.max_score,
                    percentage=round(pct, 1),
                    reason=r.reason,
                    evidence=r.evidence[:10] if r.evidence else [],
                ))
            
            # 按维度汇总
            by_dimension: dict[str, dict] = {}
            total_score = 0
            total_max = 0
            
            for r in results:
                dim = r.dimension or "Unknown"
                if dim not in by_dimension:
                    by_dimension[dim] = {"score": 0, "max_score": 0, "count": 0}
                
                if r.state in ("scored", "not_scored"):
                    by_dimension[dim]["score"] += r.score
                    by_dimension[dim]["max_score"] += r.max_score
                    by_dimension[dim]["count"] += 1
                    total_score += r.score
                    total_max += r.max_score
            
            # 生成维度汇总
            summary = []
            for dim in sorted(by_dimension.keys()):
                data = by_dimension[dim]
                pct = (data["score"] / data["max_score"] * 100) if data["max_score"] > 0 else 0
                summary.append(DimensionSummary(
                    dimension=dim,
                    score=data["score"],
                    max_score=data["max_score"],
                    percentage=round(pct, 1),
                    maturity_level=cls.get_maturity_level(pct),
                    count=data["count"],
                ))
            
            # 计算总体成熟度
            total_pct = (total_score / total_max * 100) if total_max > 0 else 0
            overall_maturity = cls.get_maturity_level(total_pct)
            
            return results, summary, total_score, total_max, round(total_pct, 1), overall_maturity
