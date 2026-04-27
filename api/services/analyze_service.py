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

from sesora.utils.agent_guidance import agent_assist_env


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
    def export_prometheus(cls, db_name: str = "sesora.db") -> str:
        """
        将上次评估缓存导出为 Prometheus 文本格式（exposition format 0.0.4）。

        各层级 gauge：
        - sesora_metric_score / sesora_metric_max_score / sesora_metric_coverage
        - sesora_category_score / sesora_category_max_score / sesora_category_coverage_ratio
        - sesora_dimension_score / sesora_dimension_max_score / sesora_dimension_coverage_ratio
        - sesora_maturity_score / sesora_maturity_max_score / sesora_maturity_percentage / sesora_maturity_coverage_ratio
        """
        from sesora.store.sqlite_store import SQLiteDataStore
        from sesora.analyzers import get_analyzer_metadata

        db_path = cls.DB_DIR / db_name
        if not db_path.exists():
            raise FileNotFoundError(f"数据库文件不存在: {db_path}")

        with SQLiteDataStore(db_path) as store:
            cache = store.load_analysis_cache()

        if not cache:
            return "# sesora: no analysis cache available\n"

        metadata = get_analyzer_metadata()
        lines: list[str] = []

        def _lv(v: str) -> str:
            return v.replace("\\", "\\\\").replace('"', '\\"')

        # ---- Metric 层 ----
        for metric_name, help_text, val_fn in [
            ("sesora_metric_score", "Score of individual metric (evaluated items only)", lambda r: r["score"]),
            ("sesora_metric_max_score", "Max score of individual metric", lambda r: r["max_score"]),
            ("sesora_metric_coverage", "Whether metric was evaluated (1=evaluated, 0=not_evaluated)",
             lambda r: 0 if r.get("state") == "not_evaluated" else 1),
        ]:
            lines += [f"# HELP {metric_name} {help_text}", f"# TYPE {metric_name} gauge"]
            for key, r in cache.items():
                meta = metadata.get(key, {})
                labels = f'key="{_lv(key)}",dimension="{_lv(meta.get("dimension", ""))}",category="{_lv(meta.get("category", ""))}"'
                lines.append(f"{metric_name}{{{labels}}} {val_fn(r)}")

        # ---- Category 层聚合 ----
        cat_agg: dict[tuple[str, str], dict] = {}
        for key, r in cache.items():
            meta = metadata.get(key, {})
            dim, cat = meta.get("dimension", ""), meta.get("category", "")
            b = cat_agg.setdefault((dim, cat), {"score": 0, "max_score": 0, "total": 0, "evaluated": 0})
            b["total"] += 1
            if r.get("state") != "not_evaluated":
                b["score"] += r["score"]
                b["max_score"] += r["max_score"]
                b["evaluated"] += 1

        for metric_name, help_text, val_fn in [
            ("sesora_category_score", "Aggregated score per category (evaluated items only)", lambda b: b["score"]),
            ("sesora_category_max_score", "Aggregated max score per category", lambda b: b["max_score"]),
            ("sesora_category_coverage_ratio", "Coverage ratio per category (0-1)",
             lambda b: round(b["evaluated"] / b["total"], 4) if b["total"] else 0.0),
        ]:
            lines += [f"# HELP {metric_name} {help_text}", f"# TYPE {metric_name} gauge"]
            for (dim, cat), b in cat_agg.items():
                labels = f'dimension="{_lv(dim)}",category="{_lv(cat)}"'
                lines.append(f"{metric_name}{{{labels}}} {val_fn(b)}")

        # ---- Dimension 层聚合 ----
        dim_agg: dict[str, dict] = {}
        for (dim, _), b in cat_agg.items():
            bucket = dim_agg.setdefault(dim, {"score": 0, "max_score": 0, "total": 0, "evaluated": 0})
            for k in ("score", "max_score", "total", "evaluated"):
                bucket[k] += b[k]

        for metric_name, help_text, val_fn in [
            ("sesora_dimension_score", "Aggregated score per dimension (evaluated items only)", lambda b: b["score"]),
            ("sesora_dimension_max_score", "Aggregated max score per dimension", lambda b: b["max_score"]),
            ("sesora_dimension_coverage_ratio", "Coverage ratio per dimension (0-1)",
             lambda b: round(b["evaluated"] / b["total"], 4) if b["total"] else 0.0),
        ]:
            lines += [f"# HELP {metric_name} {help_text}", f"# TYPE {metric_name} gauge"]
            for dim, b in dim_agg.items():
                lines.append(f'{metric_name}{{dimension="{_lv(dim)}"}} {val_fn(b)}')

        # ---- 总体层 ----
        total_score = sum(b["score"] for b in dim_agg.values())
        total_max = sum(b["max_score"] for b in dim_agg.values())
        total_items = sum(b["total"] for b in dim_agg.values())
        evaluated_items = sum(b["evaluated"] for b in dim_agg.values())
        total_pct = round(total_score / total_max * 100, 2) if total_max else 0.0
        coverage = round(evaluated_items / total_items, 4) if total_items else 0.0

        lines += [
            "# HELP sesora_maturity_score Overall maturity score (evaluated items only)",
            "# TYPE sesora_maturity_score gauge",
            f"sesora_maturity_score {total_score}",
            "# HELP sesora_maturity_max_score Overall max score",
            "# TYPE sesora_maturity_max_score gauge",
            f"sesora_maturity_max_score {total_max}",
            "# HELP sesora_maturity_percentage Overall maturity percentage (0-100)",
            "# TYPE sesora_maturity_percentage gauge",
            f"sesora_maturity_percentage {total_pct}",
            "# HELP sesora_maturity_coverage_ratio Overall evaluation coverage ratio (0-1)",
            "# TYPE sesora_maturity_coverage_ratio gauge",
            f"sesora_maturity_coverage_ratio {coverage}",
        ]

        return "\n".join(lines) + "\n"

    @classmethod
    def _build_results_and_summary(
        cls,
        raw_results: list,
        metadata: dict,
    ) -> tuple[list[AnalyzeResult], list[DimensionSummary], int, int, float, str]:
        """将 ScoreResult 列表转换为 API 响应需要的结构。"""
        results = []
        for r in raw_results:
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
                ai_assisted=any(
                    "使用 Agent 辅助评估（agent-assist）" in str(ev)
                    for ev in (r.evidence or [])
                ),
            ))

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

        total_pct = (total_score / total_max * 100) if total_max > 0 else 0
        overall_maturity = cls.get_maturity_level(total_pct)
        return results, summary, total_score, total_max, round(total_pct, 1), overall_maturity

    @classmethod
    def _cached_dict_to_score_result(cls, d: dict):
        """将缓存字典恢复为伪 ScoreResult 可迭代对象（鸭子类型）。"""
        from sesora.core.analyzer import ScoreResult, ScoreState
        state_map = {s.value: s for s in ScoreState}
        return ScoreResult(
            key=d["key"],
            state=state_map.get(d["state"], ScoreState.NOT_EVALUATED),
            score=d["score"],
            max_score=d["max_score"],
            reason=d["reason"],
            evidence=d.get("evidence", []),
        )

    @classmethod
    def run_analysis(
        cls,
        keys: list[str] = None,
        db_name: str = "sesora.db",
        agent_assist: bool = False,
        agent_assist_keys: Optional[list[str]] = None,
        agent_assist_temperature: Optional[float] = None,
        incremental: bool = False,
    ) -> tuple[list[AnalyzeResult], list[DimensionSummary], int, int, float, str, dict]:
        """
        执行评估分析（支持增量模式）

        Args:
            keys: 要执行的分析器 key 列表，None 表示全部
            db_name: 数据库文件名
            agent_assist: 是否启用 Agent 辅助
            incremental: 是否使用增量评估模式

        Returns:
            (results, summary, total_score, total_max, percentage, maturity, incremental_info) 元组
            incremental_info 包含本次增量评估的元数据
        """
        from sesora.store.sqlite_store import SQLiteDataStore
        from sesora.engine import AssessmentEngine
        from sesora.analyzers import get_analyzer_metadata
        from sesora.utils.incremental import IncrementalTracker

        db_path = cls.DB_DIR / db_name

        if not db_path.exists():
            raise FileNotFoundError(f"数据库文件不存在: {db_path}")

        with SQLiteDataStore(db_path) as store:
            engine = AssessmentEngine(store=store)
            metadata = get_analyzer_metadata()

            # 确定全部可用的 key 列表（保持顺序）
            all_keys = keys if keys else [a.key() for a in engine.registry.get_all()]

            tracker = IncrementalTracker(store, metadata)

            incremental_info: dict = {"mode": "full", "recomputed_keys": [], "cached_keys": [], "dirty_dataitems": []}

            if incremental and tracker.has_cache():
                dirty_items = tracker.get_dirty_dataitems()
                affected_keys = tracker.get_affected_keys()
                # 只在 all_keys 范围内重算
                recompute_keys = [k for k in affected_keys if k in set(all_keys)]

                incremental_info = {
                    "mode": "incremental",
                    "dirty_dataitems": dirty_items,
                    "recomputed_keys": recompute_keys,
                    "cached_keys": [k for k in all_keys if k not in set(recompute_keys)],
                }

                if recompute_keys:
                    with agent_assist_env(
                        enabled=agent_assist,
                        keys=agent_assist_keys,
                        temperature=agent_assist_temperature,
                    ):
                        new_score_results = engine.registry.run_by_keys(store, recompute_keys)

                    merged_dicts = tracker.merge_with_cache(new_score_results, all_keys)
                    # 更新缓存
                    cache = store.load_analysis_cache()
                    for r in new_score_results:
                        from sesora.utils.incremental import _score_result_to_dict
                        cache[r.key] = _score_result_to_dict(r)
                    store.save_analysis_cache(cache)
                else:
                    merged_dicts = tracker.load_cache(all_keys)

                tracker.commit(recompute_keys)

                # 将缓存字典转为 ScoreResult
                score_results = [cls._cached_dict_to_score_result(d) for d in merged_dicts]
            else:
                # 全量评估
                with agent_assist_env(
                    enabled=agent_assist,
                    keys=agent_assist_keys,
                    temperature=agent_assist_temperature,
                ):
                    score_results = engine.registry.run_by_keys(store, all_keys)

                tracker.save_full_cache(score_results)

            results, summary, total_score, total_max, total_pct, overall_maturity = \
                cls._build_results_and_summary(score_results, metadata)

            return results, summary, total_score, total_max, total_pct, overall_maturity, incremental_info
