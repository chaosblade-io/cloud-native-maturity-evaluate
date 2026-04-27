"""
Analyzer 的统一 Agent 辅助评估增强。

启用方式：
- SESORA_AGENT_ASSIST_ENABLED=1
- 可选：SESORA_AGENT_ASSIST_KEYS="k1,k2"

说明：
- 是否对某个 analyzer 启用由调用方先判断
- Agent 失败时自动回退原规则评分
"""

from __future__ import annotations

import json
import os
import re
import random
import hashlib
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any

import requests

from sesora.core.analyzer import ScoreResult, ScoreState


DEFAULT_SAMPLE_RECORDS = 10
DEFAULT_SAMPLE_SEED = 42


def is_agent_assist_enabled_for_analyzer(key: str) -> bool:
    enabled = os.getenv("SESORA_AGENT_ASSIST_ENABLED", "0")
    if enabled != "1":
        return False

    keys_raw = os.getenv("SESORA_AGENT_ASSIST_KEYS", "").strip()
    if not keys_raw:
        return True

    allow_keys = {k.strip() for k in keys_raw.split(",") if k.strip()}
    return key in allow_keys


def _serialize_value(value: Any) -> Any:
    if is_dataclass(value):
        return {k: _serialize_value(v) for k, v in asdict(value).items()}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    return value


def _extract_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", stripped)
        stripped = re.sub(r"\n```$", "", stripped)

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _llm_config() -> tuple[str, str, str] | None:
    api_key = os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("BASE_URL") or os.getenv("OPENAI_BASE_URL")
    model_name = os.getenv("MODEL_NAME") or os.getenv("OPENAI_MODEL")
    if not api_key or not base_url or not model_name:
        return None
    return api_key, base_url.rstrip("/"), model_name


def _stable_sample(records: list[Any], sample_size: int, seed_basis: str) -> list[Any]:
    if sample_size <= 0 or len(records) <= sample_size:
        return records[:sample_size] if sample_size > 0 else []

    digest = hashlib.sha256(seed_basis.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:8], "big")
    rng = random.Random(seed)
    selected_indices = sorted(rng.sample(range(len(records)), sample_size))
    return [records[i] for i in selected_indices]


def _build_data_snapshot(analyzer: Any, store: Any, max_records: int = DEFAULT_SAMPLE_RECORDS) -> dict[str, Any]:
    # It is possible to iterate over the whole data store but may be inefficient, so sample a subset of data items for now.
    dataitems: list[str] = []
    for name in analyzer.required_data():
        if name not in dataitems:
            dataitems.append(name)
    for name in analyzer.optional_data():
        if name not in dataitems:
            dataitems.append(name)

    snapshot: dict[str, Any] = {}
    for name in dataitems:
        available = store.available(name)
        records = store.get(name) if available else []
        sampled_records = _stable_sample(
            records=records,
            sample_size=max_records,
            seed_basis=f"{DEFAULT_SAMPLE_SEED}:{analyzer.key()}:{name}:{len(records)}",
        )
        snapshot[name] = {
            "available": available,
            "records_count": len(records),
            "sample_records": [_serialize_value(r) for r in sampled_records],
        }
    return snapshot


def _state_from_score(score: int) -> ScoreState:
    return ScoreState.SCORED if score > 0 else ScoreState.NOT_SCORED


def maybe_apply_agent_assisted_assessment(analyzer: Any, store: Any, original: ScoreResult) -> ScoreResult:
    if original.state == ScoreState.NOT_EVALUATED:
        return original

    config = _llm_config()
    if config is None:
        return ScoreResult(
            key=original.key,
            state=original.state,
            score=original.score,
            max_score=original.max_score,
            reason=original.reason,
            evidence=original.evidence + ["ℹ️ Agent 辅助评估未生效：缺少 API_KEY/BASE_URL/MODEL_NAME，已回退规则评分"],
        )

    api_key, base_url, model_name = config
    payload = {
        "metric_key": original.key,
        "dimension": analyzer.dimension(),
        "category": analyzer.category(),
        "max_score": analyzer.max_score(),
        "method": {
            "step_1": "Evidence Extraction: 从相关数据中提取证据 E_m",
            "step_2": "Evidence-Based Scoring: 基于 E_m 给出 0-max_score 分值与理由",
        },
        "rule_based_result": {
            "state": original.state.value,
            "score": original.score,
            "max_score": original.max_score,
            "reason": original.reason,
            "evidence": original.evidence[:8],
        },
        "data_snapshot": _build_data_snapshot(analyzer, store),
        "output_format": {
            "score": "integer within [0, max_score]",
            "reason": "string",
            "evidence": ["string"],
            "data_gaps": ["string"],
            "confidence": "float in [0,1]",
        },
    }

    system_prompt = (
        "你是云原生成熟度评估助手。请严格按两阶段执行："
        "先提取证据，再基于证据打分。不得编造。仅输出 JSON。"
    )

    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model_name,
                "temperature": float(
                    os.getenv("SESORA_AGENT_ASSIST_TEMPERATURE")
                    or os.getenv("SESORA_AGENT_TEMPERATURE", "0.1")
                ),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
            },
            timeout=120,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = _extract_json_object(content)

        score = int(parsed.get("score"))
        if score < 0:
            score = 0
        if score > analyzer.max_score():
            score = analyzer.max_score()

        reason = str(parsed.get("reason") or "Agent 辅助评估完成")

        evidence_raw = parsed.get("evidence") or []
        if not isinstance(evidence_raw, list):
            evidence_raw = [str(evidence_raw)]

        evidence = ["ℹ️ 使用 Agent 辅助评估（agent-assist）"]
        evidence.extend(str(item) for item in evidence_raw[:10])

        gaps = parsed.get("data_gaps") or []
        if isinstance(gaps, list):
            evidence.extend([f"⚠️ 数据缺口: {str(g)}" for g in gaps[:3]])

        confidence = parsed.get("confidence")
        if confidence is not None:
            evidence.append(f"ℹ️ 辅助评估置信度: {confidence}")

        return ScoreResult(
            key=original.key,
            state=_state_from_score(score),
            score=score,
            max_score=original.max_score,
            reason=reason,
            evidence=evidence,
        )
    except Exception:
        return ScoreResult(
            key=original.key,
            state=original.state,
            score=original.score,
            max_score=original.max_score,
            reason=original.reason,
            evidence=original.evidence + ["ℹ️ Agent 辅助评估失败，已回退规则评分"],
        )
