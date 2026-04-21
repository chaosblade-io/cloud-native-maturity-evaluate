import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE_ROOT = PROJECT_ROOT / "data" / "knowledge"
KNOWLEDGE_DOCS_DIR = KNOWLEDGE_BASE_ROOT / "docs"
KNOWLEDGE_META_PATH = KNOWLEDGE_BASE_ROOT / "metadata.json"


def ensure_knowledge_base() -> None:
    KNOWLEDGE_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    if not KNOWLEDGE_META_PATH.exists():
        KNOWLEDGE_META_PATH.write_text("[]\n", encoding="utf-8")


def _now_iso() -> str:
    return datetime.now().isoformat()


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def _extract_title(path: Path) -> str:
    title = path.stem
    try:
        content = _safe_read_text(path)
    except Exception:
        return title

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip() or title
    return title


def _normalize_tags(tags: Optional[list[str]]) -> list[str]:
    if not tags:
        return []
    normalized = []
    seen = set()
    for tag in tags:
        value = str(tag).strip()
        if not value:
            continue
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(value)
    return normalized


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-").lower()
    return slug or "document"


def _load_metadata() -> list[dict[str, Any]]:
    ensure_knowledge_base()
    try:
        data = json.loads(KNOWLEDGE_META_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = []
    return data if isinstance(data, list) else []


def _save_metadata(records: list[dict[str, Any]]) -> None:
    ensure_knowledge_base()
    KNOWLEDGE_META_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def list_knowledge_docs() -> list[dict[str, Any]]:
    records = _load_metadata()
    valid_records = []
    for record in records:
        path = KNOWLEDGE_DOCS_DIR / record.get("stored_name", "")
        if not path.exists():
            continue
        item = dict(record)
        item["title"] = _extract_title(path)
        item["size"] = path.stat().st_size
        valid_records.append(item)
    return sorted(valid_records, key=lambda item: item.get("updated_at", ""), reverse=True)


def get_knowledge_doc_paths(doc_ids: Optional[list[str]]) -> tuple[list[Path], list[str]]:
    available = {item["id"]: KNOWLEDGE_DOCS_DIR / item["stored_name"] for item in list_knowledge_docs()}
    warnings: list[str] = []
    if not doc_ids:
        return [], warnings

    resolved = []
    for doc_id in doc_ids:
        key = str(doc_id).strip()
        if not key:
            continue
        path = available.get(key)
        if path is None:
            warnings.append(f"知识库文档不存在: {key}")
            continue
        resolved.append(path)
    return resolved, warnings


def create_knowledge_doc(filename: str, content: bytes, tags: Optional[list[str]] = None) -> dict[str, Any]:
    ensure_knowledge_base()
    if not filename.lower().endswith(".md"):
        raise ValueError("只支持 Markdown 文件")

    doc_id = uuid.uuid4().hex[:12]
    safe_name = _slugify(Path(filename).stem)
    stored_name = f"{doc_id}_{safe_name}.md"
    path = KNOWLEDGE_DOCS_DIR / stored_name
    path.write_bytes(content)

    now = _now_iso()
    record = {
        "id": doc_id,
        "name": filename,
        "stored_name": stored_name,
        "tags": _normalize_tags(tags),
        "created_at": now,
        "updated_at": now,
    }
    records = _load_metadata()
    records.append(record)
    _save_metadata(records)
    return next(item for item in list_knowledge_docs() if item["id"] == doc_id)


def update_knowledge_doc_tags(doc_id: str, tags: Optional[list[str]]) -> dict[str, Any]:
    records = _load_metadata()
    for record in records:
        if record.get("id") != doc_id:
            continue
        record["tags"] = _normalize_tags(tags)
        record["updated_at"] = _now_iso()
        _save_metadata(records)
        return next(item for item in list_knowledge_docs() if item["id"] == doc_id)
    raise FileNotFoundError(f"知识库文档不存在: {doc_id}")


def delete_knowledge_doc(doc_id: str) -> None:
    records = _load_metadata()
    remaining = []
    target = None
    for record in records:
        if record.get("id") == doc_id:
            target = record
            continue
        remaining.append(record)
    if target is None:
        raise FileNotFoundError(f"知识库文档不存在: {doc_id}")

    path = KNOWLEDGE_DOCS_DIR / target.get("stored_name", "")
    if path.exists():
        path.unlink()
    _save_metadata(remaining)
