"""
增量评估追踪器

提供基于数据依赖图的增量评估能力：
- 每次 store.put() 自动将数据项标记为脏（dirty）
- 评估时只对存在脏依赖的 analyzer 重新运行
- 通过 SQLite 持久化脏标记和上次评估结果缓存

典型用法：
    # 采集完成后 dirty 已自动标记（由 SQLiteDataStore.put() 完成）

    # 评估时选择增量模式
    tracker = IncrementalTracker(store, get_analyzer_metadata())
    affected_keys = tracker.get_affected_keys()

    if affected_keys:
        new_results = engine.registry.run_by_keys(store, affected_keys)
        merged = tracker.merge_with_cache(new_results, all_metadata_keys)
        tracker.commit(affected_keys)   # 清除脏标记，更新缓存
    else:
        merged = tracker.load_cache(all_metadata_keys)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sesora.store.sqlite_store import SQLiteDataStore


class IncrementalTracker:
    """
    增量评估追踪器。

    依赖 SQLiteDataStore 的 dirty 持久化接口，无需额外状态。
    """

    def __init__(self, store: "SQLiteDataStore", metadata: dict[str, dict[str, Any]]) -> None:
        self._store = store
        self._metadata = metadata

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    def get_dirty_dataitems(self) -> list[str]:
        """返回自上次分析以来被修改的数据项名称列表。"""
        return self._store.get_dirty_dataitems()

    def get_affected_keys(self) -> list[str]:
        """
        根据脏数据项和分析器依赖关系，返回需要重新评估的 analyzer key 列表。

        若无任何脏数据项，返回空列表。
        """
        dirty = set(self._store.get_dirty_dataitems())
        if not dirty:
            return []

        affected: list[str] = []
        for key, meta in self._metadata.items():
            deps: set[str] = set(meta.get("required_data") or [])
            deps.update(meta.get("optional_data") or [])
            if deps & dirty:
                affected.append(key)
        return affected

    def has_cache(self) -> bool:
        """是否存在上次评估缓存。"""
        return self._store.has_analysis_cache()

    # ------------------------------------------------------------------
    # 缓存操作
    # ------------------------------------------------------------------

    def load_cache(self, all_keys: list[str]) -> list[dict[str, Any]]:
        """
        从缓存加载上次评估结果。

        Args:
            all_keys: 全部 analyzer key 列表，用于按顺序排列结果。

        Returns:
            结果字典列表，顺序与 all_keys 一致；缓存中不存在的 key 被忽略。
        """
        cache = self._store.load_analysis_cache()
        return [cache[k] for k in all_keys if k in cache]

    def merge_with_cache(
        self,
        new_results: list[Any],
        all_keys: list[str],
    ) -> list[dict[str, Any]]:
        """
        将新评估结果与缓存合并，返回完整结果集。

        新结果中存在的 key 覆盖缓存，其余 key 保留缓存值。

        Args:
            new_results: 刚评估完成的 ScoreResult 列表。
            all_keys: 全部 analyzer key 列表，用于排列输出顺序。

        Returns:
            合并后按 all_keys 顺序排列的结果字典列表。
        """
        cache = self._store.load_analysis_cache()

        for result in new_results:
            cache[result.key] = _score_result_to_dict(result)

        return [cache[k] for k in all_keys if k in cache]

    def commit(self, evaluated_keys: list[str]) -> None:
        """
        评估完成后调用：清除脏标记，将当前缓存状态写回持久化存储。

        Args:
            evaluated_keys: 本次已重新评估的 key 列表（用于决策，当前实现清除全部脏标记）。
        """
        self._store.clear_dirty_dataitems()

    def save_full_cache(self, results: list[Any]) -> None:
        """
        全量评估完成后调用：将全量结果写入缓存并清除脏标记。

        Args:
            results: 全量评估的 ScoreResult 列表。
        """
        cache = {r.key: _score_result_to_dict(r) for r in results}
        self._store.save_analysis_cache(cache)
        self._store.clear_dirty_dataitems()


def _score_result_to_dict(result: Any) -> dict[str, Any]:
    """将 ScoreResult 序列化为可 JSON 存储的字典。"""
    return {
        "key": result.key,
        "state": result.state.value if hasattr(result.state, "value") else str(result.state),
        "score": result.score,
        "max_score": result.max_score,
        "reason": result.reason,
        "evidence": list(result.evidence) if result.evidence else [],
    }
