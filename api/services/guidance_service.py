"""
改进建议服务

封装 Agent 改进建议与反馈迭代流程，供 Web API 复用。
"""
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sesora.store.sqlite_store import SQLiteDataStore
from sesora.utils.agent_guidance import (
    create_guidance_session,
    current_guidance_turn,
    refine_guidance_session,
)


class GuidanceService:
    """改进建议服务类"""

    DB_DIR = PROJECT_ROOT / "data"
    DEFAULT_DB = DB_DIR / "sesora.db"

    @classmethod
    def generate_guidance(
        cls,
        keys: Optional[list[str]] = None,
        db_name: str = "sesora.db",
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
    ) -> tuple[dict, dict]:
        db_path = cls.DB_DIR / db_name
        if not db_path.exists():
            raise FileNotFoundError(f"数据库文件不存在: {db_path}")

        with SQLiteDataStore(db_path) as store:
            session = create_guidance_session(
                store=store,
                keys=keys,
                focus_keys=focus_keys,
                max_focus=max_focus,
                max_dataitems=max_dataitems,
                max_records=max_records,
                temperature=temperature,
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
                agent_assist=agent_assist,
                agent_assist_keys=agent_assist_keys,
                agent_assist_temperature=agent_assist_temperature,
            )
        session["db_name"] = db_name
        return session, current_guidance_turn(session)

    @classmethod
    def refine_guidance(
        cls,
        session: dict,
        feedback: str,
        db_name: Optional[str] = None,
        max_focus: Optional[int] = None,
        max_dataitems: Optional[int] = None,
        max_records: Optional[int] = None,
        temperature: Optional[float] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> tuple[dict, dict]:
        target_db_name = db_name or session.get("db_name") or "sesora.db"
        db_path = cls.DB_DIR / target_db_name
        if not db_path.exists():
            raise FileNotFoundError(f"数据库文件不存在: {db_path}")

        with SQLiteDataStore(db_path) as store:
            updated_session = refine_guidance_session(
                store=store,
                session_payload=session,
                feedback=feedback,
                max_focus=max_focus,
                max_dataitems=max_dataitems,
                max_records=max_records,
                temperature=temperature,
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
            )
        updated_session["db_name"] = target_db_name
        return updated_session, current_guidance_turn(updated_session)
