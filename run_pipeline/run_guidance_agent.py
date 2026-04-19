#!/usr/bin/env python3
"""
Agent-Based Improvement Guidance 运行工具

最小化实现两阶段改进指导流程：
1. Initial Diagnosis: 基于评估报告和相关原始数据生成首轮诊断与建议
2. Iterative Refinement: 接受用户反馈后，补充更聚焦的上下文并生成下一轮建议

该工具复用现有 SQLite 数据库、分析器和 .env 中的 OpenAI 兼容模型配置，
不依赖 Web API 或前端变更。
"""

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
env_path = PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=env_path, override=True)
sys.path.insert(0, str(PROJECT_ROOT))

from run_pipeline.run_analyzer import load_run_cases
from sesora.analyzers import get_analyzer_metadata
from sesora.core.context import AssessmentContext
from sesora.core.report import AssessmentReport
from sesora.engine import AssessmentEngine
from sesora.store.sqlite_store import SQLiteDataStore


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="基于原始数据和评分结果运行改进建议 Agent 循环",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基于数据库运行首轮诊断
  python run_pipeline/run_guidance_agent.py --all

  # 仅针对部分分析项生成建议
  python run_pipeline/run_guidance_agent.py --key ha_redundancy mon_metrics_depth

  # 进入交互式 refinement
  python run_pipeline/run_guidance_agent.py --all --interactive

  # 通过命令行直接提供两轮反馈
  python run_pipeline/run_guidance_agent.py --all --feedback "先做低成本项" "只关注可观测性"
""",
    )
    parser.add_argument("--db_path", default="data/sesora.db", help="SQLite 数据库文件路径")
    parser.add_argument("--config", "-c", type=str, default=None, help="分析器配置 JSON 文件")
    parser.add_argument("--key", "-k", nargs="+", default=None, help="要运行的分析器 key（可指定多个）")
    parser.add_argument("--all", "-a", action="store_true", help="运行所有分析器")
    parser.add_argument("--focus-key", nargs="+", default=None, help="显式指定首轮重点分析的评估项 key")
    parser.add_argument("--feedback", nargs="*", default=[], help="按顺序提供 refinement 反馈")
    parser.add_argument("--interactive", action="store_true", help="首轮输出后进入交互式 refinement")
    parser.add_argument("--max-focus", type=int, default=6, help="每轮最多聚焦的评估项数量")
    parser.add_argument("--max-dataitems", type=int, default=12, help="每轮最多附带的 DataItem 数量")
    parser.add_argument("--max-records", type=int, default=3, help="每个 DataItem 最多附带的样本记录数")
    parser.add_argument("--temperature", type=float, default=0.1, help="模型温度")
    parser.add_argument("--api-key", dest="api_key", default=None, help="覆盖环境变量 API_KEY")
    parser.add_argument("--base-url", dest="base_url", default=None, help="覆盖环境变量 BASE_URL")
    parser.add_argument("--model", dest="model_name", default=None, help="覆盖环境变量 MODEL_NAME")
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 文件路径")
    return parser.parse_args()


def resolve_db_path(raw_path: str) -> Path:
    db_path = Path(raw_path)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    return db_path


def resolve_keys(args: argparse.Namespace) -> Optional[list[str]]:
    if args.key:
        return args.key
    if args.all:
        return None
    if args.config:
        config_path = Path(args.config)
        if not config_path.is_absolute():
            config_path = PROJECT_ROOT / config_path
        return load_run_cases(config_path)
    return None


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


def resolve_llm_config(args: argparse.Namespace) -> tuple[str, str, str]:
    api_key = args.api_key or os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = args.base_url or os.getenv("BASE_URL") or os.getenv("OPENAI_BASE_URL")
    model_name = args.model_name or os.getenv("MODEL_NAME") or os.getenv("OPENAI_MODEL")

    if not api_key:
        raise ValueError("缺少 API Key，请设置 API_KEY 或传入 --api-key")
    if not base_url:
        raise ValueError("缺少 Base URL，请设置 BASE_URL 或传入 --base-url")
    if not model_name:
        raise ValueError("缺少模型名称，请设置 MODEL_NAME 或传入 --model")

    return api_key, base_url.rstrip("/"), model_name


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


def print_guidance(stage: str, focus_keys: list[str], guidance: dict[str, Any]) -> None:
    print("\n" + "=" * 70)
    print(f"{stage} 结果")
    print("=" * 70)
    print(f"聚焦评估项: {', '.join(focus_keys) if focus_keys else '-'}")
    print(f"诊断摘要: {guidance.get('diagnosis_summary', '-')}")

    focus_areas = guidance.get("focus_areas", [])
    if focus_areas:
        print("重点领域:")
        for area in focus_areas:
            print(f"  - {area}")

    recommendations = guidance.get("prioritized_recommendations", [])
    if recommendations:
        print("优先建议:")
        for index, recommendation in enumerate(recommendations, start=1):
            print(f"  {index}. [{recommendation.get('priority', 'P2')}] {recommendation.get('title', '-')}")
            print(f"     范围: {recommendation.get('scope', '-')}")
            print(f"     原因: {recommendation.get('rationale', '-')}")
            for action in recommendation.get("actions", []):
                print(f"     - {action}")

    data_gaps = guidance.get("data_gaps", [])
    if data_gaps:
        print("数据缺口:")
        for gap in data_gaps:
            print(f"  - {gap.get('scope', '-')}: {gap.get('gap', '-')}")

    questions = guidance.get("follow_up_questions", [])
    if questions:
        print("后续问题:")
        for question in questions:
            print(f"  - {question}")


def save_session(session_payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(session_payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_output_path(raw_output: Optional[str]) -> Path:
    if raw_output:
        output_path = Path(raw_output)
        if not output_path.is_absolute():
            output_path = PROJECT_ROOT / output_path
        return output_path

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return PROJECT_ROOT / "results" / timestamp / f"guidance_session_{timestamp}.json"


def collect_feedback_loop(initial_feedbacks: list[str], interactive: bool) -> list[str]:
    feedbacks = [feedback for feedback in initial_feedbacks if feedback]
    if not interactive:
        return feedbacks

    print("\n进入 refinement 交互模式，输入 exit 或空行结束。")
    while True:
        try:
            feedback = input("反馈> ").strip()
        except EOFError:
            break
        if not feedback or feedback.lower() in {"exit", "quit", "q"}:
            break
        feedbacks.append(feedback)
    return feedbacks


def main() -> int:
    args = parse_args()
    db_path = resolve_db_path(args.db_path)
    if not db_path.exists():
        print(f"错误: 数据库文件不存在: {db_path}")
        return 1

    api_key, base_url, model_name = resolve_llm_config(args)
    metadata = get_analyzer_metadata()
    output_path = build_output_path(args.output)
    requested_keys = resolve_keys(args)

    print("=" * 70)
    print("SESORA Agent-Based Improvement Guidance")
    print("=" * 70)
    print(f"数据库: {db_path}")
    print(f"模型: {model_name}")
    print(f"输出: {output_path}")

    with SQLiteDataStore(db_path) as store:
        engine = AssessmentEngine(store=store)
        if requested_keys is None:
            requested_keys = [analyzer.key() for analyzer in engine.registry.get_all()]

        task = engine.create_task(AssessmentContext())
        report = engine.run_analysis(task, keys=requested_keys)

        flat_items = flatten_report(report, metadata)
        hierarchy_context = build_hierarchy_context(report, metadata)
        focus_keys = rank_focus_items(flat_items, args.focus_key, "", args.max_focus)
        raw_snapshot = build_raw_data_snapshot(store, metadata, focus_keys, args.max_dataitems, args.max_records)

        initial_prompt = build_prompt(
            stage="Initial Diagnosis",
            hierarchy_context=hierarchy_context,
            focus_keys=focus_keys,
            raw_snapshot=raw_snapshot,
        )
        initial_guidance, initial_raw_response = call_llm(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            temperature=args.temperature,
            prompt=initial_prompt,
        )

        print_guidance("Initial Diagnosis", focus_keys, initial_guidance)

        session_payload: dict[str, Any] = {
            "generated_at": datetime.now().isoformat(),
            "db_path": str(db_path),
            "model": model_name,
            "summary": hierarchy_context["summary"],
            "turns": [
                {
                    "stage": "initial_diagnosis",
                    "focus_keys": focus_keys,
                    "raw_data_items": list(raw_snapshot.keys()),
                    "guidance": initial_guidance,
                    "raw_response": initial_raw_response,
                }
            ],
        }
        save_session(session_payload, output_path)

        feedbacks = collect_feedback_loop(args.feedback, args.interactive)
        previous_guidance = initial_guidance

        for turn_index, feedback in enumerate(feedbacks, start=1):
            refinement_focus = rank_focus_items(flat_items, None, feedback, args.max_focus)
            refinement_snapshot = build_raw_data_snapshot(
                store,
                metadata,
                refinement_focus,
                args.max_dataitems,
                args.max_records,
            )
            refinement_prompt = build_prompt(
                stage="Iterative Refinement",
                hierarchy_context=hierarchy_context,
                focus_keys=refinement_focus,
                raw_snapshot=refinement_snapshot,
                previous_guidance=previous_guidance,
                feedback=feedback,
            )
            refinement_guidance, refinement_raw_response = call_llm(
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
                temperature=args.temperature,
                prompt=refinement_prompt,
            )

            print_guidance(f"Iterative Refinement #{turn_index}", refinement_focus, refinement_guidance)
            session_payload["turns"].append(
                {
                    "stage": "iterative_refinement",
                    "feedback": feedback,
                    "focus_keys": refinement_focus,
                    "raw_data_items": list(refinement_snapshot.keys()),
                    "guidance": refinement_guidance,
                    "raw_response": refinement_raw_response,
                }
            )
            save_session(session_payload, output_path)
            previous_guidance = refinement_guidance

    print("\n完成，结果已写入输出文件。")
    return 0


if __name__ == "__main__":
    sys.exit(main())