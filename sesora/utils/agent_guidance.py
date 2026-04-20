import json
import os
import re
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests
from dotenv import load_dotenv

from sesora.analyzers import get_analyzer_metadata
from sesora.core.context import AssessmentContext
from sesora.core.report import AssessmentReport
from sesora.engine import AssessmentEngine
from sesora.store.sqlite_store import SQLiteDataStore


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=True)


SYSTEM_PROMPT = """
你是云原生成熟度改进顾问。你的任务是基于结构化评估结果和原始证据，输出优先级明确、可执行、可追溯的改进建议。

严格遵守以下要求：
1. 优先关注低得分区域和低覆盖率区域。
2. 不要编造不存在的数据；若证据不足，要明确指出数据缺口。
3. 建议必须和提供的证据绑定，尽量落到具体工程动作。
4. 如果用户反馈提供了成本、时间、风险或组织约束，必须在建议中显式体现。
5. 仅输出合法 JSON，不要输出 Markdown 代码块。

输出 JSON 结构：
{
  "diagnosis_summary": "一句到两句总结",
  "focus_areas": ["重点领域1", "重点领域2"],
  "prioritized_recommendations": [
    {
      "priority": "P1|P2|P3",
      "title": "建议标题",
      "scope": "影响范围",
      "rationale": "为什么优先处理",
      "actions": ["动作1", "动作2"],
      "evidence": ["证据1", "证据2"],
      "dependencies": ["前置条件或依赖，可为空"]
    }
  ],
  "data_gaps": [
    {
      "scope": "缺口范围",
      "gap": "缺少什么数据",
      "why_it_matters": "为什么影响判断",
      "suggested_collection": "建议补什么数据"
    }
  ],
  "follow_up_questions": ["建议继续确认的问题"]
}
""".strip()


PLANNER_PROMPT = """
你是云原生成熟度改进顾问的诊断规划器。
请先基于聚合分数定位首轮重点，再仅按需请求必要细节。

要求：
1. 重点关注低得分区域（低 S_g）和低覆盖区域（低 C_g）。
2. 不要一次性请求所有指标细节，只请求支撑首轮建议所需的最小集合。
3. 仅输出合法 JSON，不要输出 Markdown。

输出 JSON 结构：
{
    "focus_keys": ["metric_key1", "metric_key2"],
    "required_metric_keys": ["metric_keyA", "metric_keyB"],
    "required_dataitems": ["dataitem.name1", "dataitem.name2"],
    "rationale": "一句话说明为何选这些重点"
}
""".strip()


@contextmanager
def agent_assist_env(
    enabled: bool,
    keys: Optional[list[str]] = None,
    temperature: Optional[float] = None,
):
    managed_keys = [
        "SESORA_AGENT_ASSIST_ENABLED",
        "SESORA_AGENT_ASSIST_KEYS",
        "SESORA_AGENT_ASSIST_TEMPERATURE",
    ]
    backup = {key: os.environ.get(key) for key in managed_keys}

    try:
        if enabled:
            os.environ["SESORA_AGENT_ASSIST_ENABLED"] = "1"
            if keys:
                os.environ["SESORA_AGENT_ASSIST_KEYS"] = ",".join(keys)
            else:
                os.environ.pop("SESORA_AGENT_ASSIST_KEYS", None)

            if temperature is not None:
                os.environ["SESORA_AGENT_ASSIST_TEMPERATURE"] = str(temperature)
            else:
                os.environ.pop("SESORA_AGENT_ASSIST_TEMPERATURE", None)
        else:
            for key in managed_keys:
                os.environ.pop(key, None)

        yield
    finally:
        for key, value in backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def serialize_value(value: Any) -> Any:
    if is_dataclass(value):
        return {key: serialize_value(val) for key, val in asdict(value).items()}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize_value(val) for key, val in value.items()}
    return value


def flatten_report(report: AssessmentReport, metadata: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for dimension in report.dimensions:
        for category in dimension.categories:
            for item in category.items:
                item_meta = metadata.get(item.key, {})
                items.append(
                    {
                        "key": item.key,
                        "dimension": item_meta.get("dimension", dimension.dimension),
                        "category": item_meta.get("category", category.category),
                        "state": item.state.value,
                        "score": item.score,
                        "max_score": item.max_score,
                        "score_percentage": round(item.score_percentage, 2),
                        "reason": item.reason,
                        "evidence": item.evidence,
                        "required_data": item_meta.get("required_data", []),
                        "optional_data": item_meta.get("optional_data", []),
                    }
                )
    return items


def build_hierarchy_context(report: AssessmentReport, metadata: dict[str, dict[str, Any]]) -> dict[str, Any]:
    dimensions_payload = []
    for dimension in report.dimensions:
        categories_payload = []
        for category in dimension.categories:
            total_items = len(category.items)
            coverage_ratio = round((category.evaluated_count / total_items * 100), 2) if total_items else 0.0
            item_payload = []
            for item in category.items:
                item_meta = metadata.get(item.key, {})
                item_payload.append(
                    {
                        "key": item.key,
                        "state": item.state.value,
                        "score": item.score,
                        "max_score": item.max_score,
                        "score_percentage": round(item.score_percentage, 2),
                        "reason": item.reason,
                        "evidence": item.evidence[:6],
                        "required_data": item_meta.get("required_data", []),
                        "optional_data": item_meta.get("optional_data", []),
                    }
                )

            categories_payload.append(
                {
                    "category": category.category,
                    "score": category.category_score,
                    "max_score": category.category_max,
                    "score_percentage": round(category.score_percentage, 2),
                    "coverage_ratio": coverage_ratio,
                    "evaluated_count": category.evaluated_count,
                    "not_evaluated_count": category.not_evaluated_count,
                    "items": item_payload,
                }
            )

        dimensions_payload.append(
            {
                "dimension": dimension.dimension,
                "score": dimension.dimension_score,
                "max_score": dimension.dimension_max,
                "score_percentage": round(dimension.score_percentage, 2),
                "coverage_ratio": round(dimension.coverage_ratio, 2),
                "evaluated_count": dimension.evaluated_count,
                "not_evaluated_count": dimension.not_evaluated_count,
                "categories": categories_payload,
            }
        )

    return {
        "task_id": report.task_id,
        "executed_at": report.executed_at.isoformat() if report.executed_at else None,
        "summary": {
            "evaluated_score": report.summary.evaluated_score if report.summary else 0,
            "evaluated_max": report.summary.evaluated_max if report.summary else 0,
            "maturity_percentage": round(report.summary.maturity_percentage, 2) if report.summary else 0,
            "coverage_ratio": round(report.summary.coverage_ratio, 2) if report.summary else 0,
            "evaluated_items": report.summary.evaluated_items if report.summary else 0,
            "not_evaluated_items": report.summary.not_evaluated_items if report.summary else 0,
        },
        "dimensions": dimensions_payload,
    }


def build_hierarchy_summary_context(report: AssessmentReport, metadata: dict[str, dict[str, Any]]) -> dict[str, Any]:
    dimensions_payload = []
    for dimension in report.dimensions:
        categories_payload = []
        for category in dimension.categories:
            total_items = len(category.items)
            coverage_ratio = round((category.evaluated_count / total_items * 100), 2) if total_items else 0.0

            scored_items = [item for item in category.items if item.state.value != "not_evaluated"]
            weak_items = sorted(
                scored_items,
                key=lambda item: (item.score_percentage, -item.max_score, item.key),
            )[:3]

            categories_payload.append(
                {
                    "category": category.category,
                    "score": category.category_score,
                    "max_score": category.category_max,
                    "score_percentage": round(category.score_percentage, 2),
                    "coverage_ratio": coverage_ratio,
                    "evaluated_count": category.evaluated_count,
                    "not_evaluated_count": category.not_evaluated_count,
                    "weak_item_keys": [item.key for item in weak_items],
                }
            )

        dimensions_payload.append(
            {
                "dimension": dimension.dimension,
                "score": dimension.dimension_score,
                "max_score": dimension.dimension_max,
                "score_percentage": round(dimension.score_percentage, 2),
                "coverage_ratio": round(dimension.coverage_ratio, 2),
                "evaluated_count": dimension.evaluated_count,
                "not_evaluated_count": dimension.not_evaluated_count,
                "categories": categories_payload,
            }
        )

    return {
        "task_id": report.task_id,
        "executed_at": report.executed_at.isoformat() if report.executed_at else None,
        "summary": {
            "evaluated_score": report.summary.evaluated_score if report.summary else 0,
            "evaluated_max": report.summary.evaluated_max if report.summary else 0,
            "maturity_percentage": round(report.summary.maturity_percentage, 2) if report.summary else 0,
            "coverage_ratio": round(report.summary.coverage_ratio, 2) if report.summary else 0,
            "evaluated_items": report.summary.evaluated_items if report.summary else 0,
            "not_evaluated_items": report.summary.not_evaluated_items if report.summary else 0,
        },
        "dimensions": dimensions_payload,
    }


def rank_focus_items(
    flat_items: list[dict[str, Any]],
    explicit_keys: Optional[list[str]],
    feedback: str,
    max_focus: int,
) -> list[str]:
    available_keys = {item["key"] for item in flat_items}
    if explicit_keys:
        return [key for key in explicit_keys if key in available_keys][:max_focus]

    scored_items = [item for item in flat_items if item["state"] != "not_evaluated"]
    scored_items.sort(key=lambda item: (item["score_percentage"], item["max_score"] * -1, item["key"]))
    sparse_items = [item for item in flat_items if item["state"] == "not_evaluated"]

    selected: list[str] = []

    if feedback:
        lowered_feedback = feedback.lower()
        raw_tokens = re.split(r"[\s,，;；、/]+", lowered_feedback)
        tokens = [token for token in raw_tokens if len(token) >= 2]

        def item_match_score(item: dict[str, Any]) -> int:
            haystacks = [
                str(item["key"]).lower(),
                str(item["dimension"]).lower(),
                str(item["category"]).lower(),
                str(item["reason"]).lower(),
                " ".join(str(ev).lower() for ev in item.get("evidence", [])),
            ]
            score = 0
            for token in tokens:
                if any(token in haystack for haystack in haystacks):
                    score += 1
            if lowered_feedback and any(lowered_feedback in haystack for haystack in haystacks):
                score += 2
            return score

        matched = sorted(flat_items, key=lambda item: (item_match_score(item), -item["max_score"]), reverse=True)
        for item in matched:
            if item_match_score(item) <= 0:
                continue
            if item["key"] not in selected:
                selected.append(item["key"])
            if len(selected) >= max_focus:
                return selected

    for item in scored_items:
        if item["key"] not in selected:
            selected.append(item["key"])
        if len(selected) >= max_focus:
            return selected

    for item in sparse_items:
        if item["key"] not in selected:
            selected.append(item["key"])
        if len(selected) >= max_focus:
            break

    return selected[:max_focus]


def build_raw_data_snapshot(
    store: SQLiteDataStore,
    metadata: dict[str, dict[str, Any]],
    focus_keys: list[str],
    max_dataitems: int,
    max_records: int,
) -> dict[str, Any]:
    selected_dataitems: list[str] = []
    for key in focus_keys:
        item_meta = metadata.get(key, {})
        for dataitem in item_meta.get("required_data", []):
            if dataitem not in selected_dataitems:
                selected_dataitems.append(dataitem)
        for dataitem in item_meta.get("optional_data", []):
            if dataitem not in selected_dataitems:
                selected_dataitems.append(dataitem)

    snapshot: dict[str, Any] = {}
    for dataitem in selected_dataitems[:max_dataitems]:
        available = store.available(dataitem)
        records = store.get(dataitem) if available else []
        snapshot[dataitem] = {
            "available": available,
            "records_count": len(records),
            "sample_records": [serialize_value(record) for record in records[:max_records]],
        }
    return snapshot


def build_prompt(
    stage: str,
    hierarchy_context: dict[str, Any],
    focus_keys: list[str],
    raw_snapshot: dict[str, Any],
    previous_guidance: Optional[dict[str, Any]] = None,
    feedback: str = "",
) -> str:
    prompt_payload = {
        "stage": stage,
        "task": "为云原生成熟度评估结果生成改进建议",
        "method": {
            "initial_diagnosis": "优先查看低 S_g 和低 C_g 区域，并结合 evidence 与 raw data 诊断根因",
            "iterative_refinement": "结合用户反馈重新聚焦，并在提供的更深层数据中给出更贴合约束的建议",
        },
        "focus_keys": focus_keys,
        "hierarchy_context": hierarchy_context,
        "raw_data_snapshot": raw_snapshot,
    }

    if previous_guidance is not None:
        prompt_payload["previous_guidance"] = previous_guidance
    if feedback:
        prompt_payload["user_feedback"] = feedback

    return json.dumps(prompt_payload, ensure_ascii=False, indent=2)


def build_planner_prompt(
    stage: str,
    hierarchy_summary_context: dict[str, Any],
    candidate_focus_keys: list[str],
    max_focus: int,
    previous_guidance: Optional[dict[str, Any]] = None,
    feedback: str = "",
) -> str:
    payload = {
        "stage": stage,
        "task": "从聚合成熟度结果中定位重点并请求最小必要细节",
        "max_focus": max_focus,
        "candidate_focus_keys": candidate_focus_keys,
        "hierarchy_summary_context": hierarchy_summary_context,
    }
    if previous_guidance is not None:
        payload["previous_guidance"] = previous_guidance
    if feedback:
        payload["user_feedback"] = feedback
    return json.dumps(payload, ensure_ascii=False, indent=2)


def parse_planner_result(
    planner_result: dict[str, Any],
    fallback_focus_keys: list[str],
    max_focus: int,
) -> tuple[list[str], list[str], list[str]]:
    raw_focus = planner_result.get("focus_keys") or []
    raw_metric_keys = planner_result.get("required_metric_keys") or []
    raw_dataitems = planner_result.get("required_dataitems") or []

    focus_keys = [str(key) for key in raw_focus if str(key).strip()]
    if not focus_keys:
        focus_keys = fallback_focus_keys[:max_focus]

    required_metric_keys = [str(key) for key in raw_metric_keys if str(key).strip()]
    for key in focus_keys:
        if key not in required_metric_keys:
            required_metric_keys.append(key)

    required_dataitems = [str(name) for name in raw_dataitems if str(name).strip()]
    return focus_keys[:max_focus], required_metric_keys, required_dataitems


def build_metric_detail_bundle(
    flat_items: list[dict[str, Any]],
    metric_keys: list[str],
    max_evidence: int = 4,
) -> list[dict[str, Any]]:
    lookup = {item["key"]: item for item in flat_items}
    details: list[dict[str, Any]] = []
    for key in metric_keys:
        item = lookup.get(key)
        if item is None:
            continue
        details.append(
            {
                "key": item["key"],
                "dimension": item["dimension"],
                "category": item["category"],
                "state": item["state"],
                "score": item["score"],
                "max_score": item["max_score"],
                "score_percentage": item["score_percentage"],
                "reason": item["reason"],
                "evidence": item.get("evidence", [])[:max_evidence],
                "required_data": item.get("required_data", []),
                "optional_data": item.get("optional_data", []),
            }
        )
    return details


def build_selected_raw_data_snapshot(
    store: SQLiteDataStore,
    dataitems: list[str],
    max_dataitems: int,
    max_records: int,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for dataitem in dataitems[:max_dataitems]:
        available = store.available(dataitem)
        records = store.get(dataitem) if available else []
        snapshot[dataitem] = {
            "available": available,
            "records_count": len(records),
            "sample_records": [serialize_value(record) for record in records[:max_records]],
        }
    return snapshot


def resolve_llm_config(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model_name: Optional[str] = None,
) -> tuple[str, str, str]:
    resolved_api_key = api_key or os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")
    resolved_base_url = base_url or os.getenv("BASE_URL") or os.getenv("OPENAI_BASE_URL")
    resolved_model_name = model_name or os.getenv("MODEL_NAME") or os.getenv("OPENAI_MODEL")

    if not resolved_api_key:
        raise ValueError("缺少 API Key，请设置 API_KEY 或传入 api_key")
    if not resolved_base_url:
        raise ValueError("缺少 Base URL，请设置 BASE_URL 或传入 base_url")
    if not resolved_model_name:
        raise ValueError("缺少模型名称，请设置 MODEL_NAME 或传入 model_name")

    return resolved_api_key, resolved_base_url.rstrip("/"), resolved_model_name


def extract_json_object(content: str) -> dict[str, Any]:
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


def call_llm(
    api_key: str,
    base_url: str,
    model_name: str,
    temperature: float,
    prompt: str,
) -> tuple[dict[str, Any], str]:
    response = requests.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model_name,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=180,
    )
    response.raise_for_status()

    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    return extract_json_object(content), content


def call_llm_with_prompt(
    api_key: str,
    base_url: str,
    model_name: str,
    temperature: float,
    system_prompt: str,
    prompt: str,
) -> tuple[dict[str, Any], str]:
    response = requests.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model_name,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=180,
    )
    response.raise_for_status()

    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    return extract_json_object(content), content


def _run_report(
    store: SQLiteDataStore,
    keys: Optional[list[str]] = None,
    agent_assist: bool = False,
    agent_assist_keys: Optional[list[str]] = None,
    agent_assist_temperature: Optional[float] = None,
) -> tuple[list[str], AssessmentReport]:
    engine = AssessmentEngine(store=store)
    analysis_keys = keys
    if analysis_keys is None:
        analysis_keys = [analyzer.key() for analyzer in engine.registry.get_all()]

    task = engine.create_task(AssessmentContext())
    with agent_assist_env(
        enabled=agent_assist,
        keys=agent_assist_keys,
        temperature=agent_assist_temperature,
    ):
        report = engine.run_analysis(task, keys=analysis_keys)
    return analysis_keys, report


def create_guidance_session(
    store: SQLiteDataStore,
    keys: Optional[list[str]] = None,
    focus_keys: Optional[list[str]] = None,
    max_focus: int = 6,
    max_dataitems: int = 12,
    max_records: int = 3,
    temperature: float = 0.1,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model_name: Optional[str] = None,
    agent_assist: bool = False,
    agent_assist_keys: Optional[list[str]] = None,
    agent_assist_temperature: Optional[float] = None,
) -> dict[str, Any]:
    resolved_api_key, resolved_base_url, resolved_model_name = resolve_llm_config(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
    )
    metadata = get_analyzer_metadata()
    analysis_keys, report = _run_report(
        store,
        keys=keys,
        agent_assist=agent_assist,
        agent_assist_keys=agent_assist_keys,
        agent_assist_temperature=agent_assist_temperature,
    )

    flat_items = flatten_report(report, metadata)
    hierarchy_context = build_hierarchy_summary_context(report, metadata)
    ranked_focus_keys = rank_focus_items(flat_items, focus_keys, "", max_focus)

    planner_prompt = build_planner_prompt(
        stage="Initial Diagnosis",
        hierarchy_summary_context=hierarchy_context,
        candidate_focus_keys=ranked_focus_keys,
        max_focus=max_focus,
    )
    planner_result, planner_raw_response = call_llm_with_prompt(
        api_key=resolved_api_key,
        base_url=resolved_base_url,
        model_name=resolved_model_name,
        temperature=temperature,
        system_prompt=PLANNER_PROMPT,
        prompt=planner_prompt,
    )

    selected_focus_keys, requested_metric_keys, requested_dataitems = parse_planner_result(
        planner_result=planner_result,
        fallback_focus_keys=ranked_focus_keys,
        max_focus=max_focus,
    )

    detail_metrics = build_metric_detail_bundle(flat_items, requested_metric_keys)
    requested_dataitems = list(dict.fromkeys(requested_dataitems))

    metadata_dataitems: list[str] = []
    for key in selected_focus_keys:
        item_meta = metadata.get(key, {})
        for dataitem in item_meta.get("required_data", []):
            if dataitem not in metadata_dataitems:
                metadata_dataitems.append(dataitem)
        for dataitem in item_meta.get("optional_data", []):
            if dataitem not in metadata_dataitems:
                metadata_dataitems.append(dataitem)

    for dataitem in metadata_dataitems:
        if dataitem not in requested_dataitems:
            requested_dataitems.append(dataitem)

    raw_snapshot = build_selected_raw_data_snapshot(
        store=store,
        dataitems=requested_dataitems,
        max_dataitems=max_dataitems,
        max_records=max_records,
    )

    prompt = build_prompt(
        stage="Initial Diagnosis",
        hierarchy_context=hierarchy_context,
        focus_keys=selected_focus_keys,
        raw_snapshot={
            "selected_metric_details": detail_metrics,
            "selected_raw_data": raw_snapshot,
        },
    )
    guidance, raw_response = call_llm(
        api_key=resolved_api_key,
        base_url=resolved_base_url,
        model_name=resolved_model_name,
        temperature=temperature,
        prompt=prompt,
    )

    generated_at = datetime.now().isoformat()
    return {
        "generated_at": generated_at,
        "updated_at": generated_at,
        "model": resolved_model_name,
        "analysis_keys": analysis_keys,
        "agent_assist": agent_assist,
        "agent_assist_keys": agent_assist_keys or [],
        "agent_assist_temperature": agent_assist_temperature,
        "max_focus": max_focus,
        "max_dataitems": max_dataitems,
        "max_records": max_records,
        "temperature": temperature,
        "summary": hierarchy_context["summary"],
        "hierarchy_context": hierarchy_context,
        "flat_items": flat_items,
        "turns": [
            {
                "stage": "initial_diagnosis",
                "focus_keys": selected_focus_keys,
                "raw_data_items": list(raw_snapshot.keys()),
                "requested_metric_keys": requested_metric_keys,
                "planner": planner_result,
                "planner_raw_response": planner_raw_response,
                "guidance": guidance,
                "raw_response": raw_response,
            }
        ],
    }


def refine_guidance_session(
    store: SQLiteDataStore,
    session_payload: dict[str, Any],
    feedback: str,
    max_focus: Optional[int] = None,
    max_dataitems: Optional[int] = None,
    max_records: Optional[int] = None,
    temperature: Optional[float] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model_name: Optional[str] = None,
) -> dict[str, Any]:
    if not feedback or not feedback.strip():
        raise ValueError("反馈内容不能为空")

    session = deepcopy(session_payload)
    flat_items = session.get("flat_items") or []
    hierarchy_context = session.get("hierarchy_context") or {}
    turns = session.get("turns") or []
    if not flat_items or not hierarchy_context or not turns:
        raise ValueError("缺少有效的 guidance session 上下文")

    resolved_api_key, resolved_base_url, resolved_model_name = resolve_llm_config(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name or session.get("model"),
    )
    metadata = get_analyzer_metadata()
    resolved_max_focus = max_focus if max_focus is not None else int(session.get("max_focus", 6))
    resolved_max_dataitems = max_dataitems if max_dataitems is not None else int(session.get("max_dataitems", 12))
    resolved_max_records = max_records if max_records is not None else int(session.get("max_records", 3))
    resolved_temperature = temperature if temperature is not None else float(session.get("temperature", 0.1))

    refinement_focus = rank_focus_items(flat_items, None, feedback, resolved_max_focus)
    previous_guidance = turns[-1].get("guidance")

    planner_prompt = build_planner_prompt(
        stage="Iterative Refinement",
        hierarchy_summary_context=hierarchy_context,
        candidate_focus_keys=refinement_focus,
        max_focus=resolved_max_focus,
        previous_guidance=previous_guidance,
        feedback=feedback,
    )
    planner_result, planner_raw_response = call_llm_with_prompt(
        api_key=resolved_api_key,
        base_url=resolved_base_url,
        model_name=resolved_model_name,
        temperature=resolved_temperature,
        system_prompt=PLANNER_PROMPT,
        prompt=planner_prompt,
    )

    selected_focus_keys, requested_metric_keys, requested_dataitems = parse_planner_result(
        planner_result=planner_result,
        fallback_focus_keys=refinement_focus,
        max_focus=resolved_max_focus,
    )

    detail_metrics = build_metric_detail_bundle(flat_items, requested_metric_keys)
    requested_dataitems = list(dict.fromkeys(requested_dataitems))

    metadata_dataitems: list[str] = []
    for key in selected_focus_keys:
        item_meta = metadata.get(key, {})
        for dataitem in item_meta.get("required_data", []):
            if dataitem not in metadata_dataitems:
                metadata_dataitems.append(dataitem)
        for dataitem in item_meta.get("optional_data", []):
            if dataitem not in metadata_dataitems:
                metadata_dataitems.append(dataitem)

    for dataitem in metadata_dataitems:
        if dataitem not in requested_dataitems:
            requested_dataitems.append(dataitem)

    refinement_snapshot = build_selected_raw_data_snapshot(
        store=store,
        dataitems=requested_dataitems,
        max_dataitems=resolved_max_dataitems,
        max_records=resolved_max_records,
    )

    prompt = build_prompt(
        stage="Iterative Refinement",
        hierarchy_context=hierarchy_context,
        focus_keys=selected_focus_keys,
        raw_snapshot={
            "selected_metric_details": detail_metrics,
            "selected_raw_data": refinement_snapshot,
        },
        previous_guidance=previous_guidance,
        feedback=feedback,
    )
    guidance, raw_response = call_llm(
        api_key=resolved_api_key,
        base_url=resolved_base_url,
        model_name=resolved_model_name,
        temperature=resolved_temperature,
        prompt=prompt,
    )

    session["updated_at"] = datetime.now().isoformat()
    session["model"] = resolved_model_name
    session["turns"].append(
        {
            "stage": "iterative_refinement",
            "feedback": feedback,
            "focus_keys": selected_focus_keys,
            "raw_data_items": list(refinement_snapshot.keys()),
            "requested_metric_keys": requested_metric_keys,
            "planner": planner_result,
            "planner_raw_response": planner_raw_response,
            "guidance": guidance,
            "raw_response": raw_response,
        }
    )
    return session


def current_guidance_turn(session_payload: dict[str, Any]) -> dict[str, Any]:
    turns = session_payload.get("turns") or []
    return turns[-1] if turns else {}
