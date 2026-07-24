"""
Database setup: async SQLAlchemy engine (SQLite via aiosqlite or PostgreSQL via asyncpg).
"""
import logging
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger("database")

DB_PATH = os.environ.get("AI_TEAM_HUB_DB", os.path.join(os.path.dirname(__file__), "..", "data", "aiteamhub.db"))
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

DATABASE_URL = os.environ.get(
    "AI_TEAM_HUB_DATABASE_URL",
    f"sqlite+aiosqlite:///{DB_PATH}",
)


def get_sync_db_url() -> str:
    """Resolve sync DB URL (strips async driver suffix for sync engines)."""
    url = os.environ.get("AI_TEAM_HUB_DATABASE_URL", "")
    if url:
        return url.replace("+aiosqlite", "").replace("+asyncpg", "")
    return f"sqlite:///{DB_PATH}"


_is_sqlite = "sqlite" in DATABASE_URL

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    """Create all tables + enable WAL mode for concurrent writes (SQLite only)."""
    from sqlalchemy import text
    from backend.models import Channel, Teammate, APIKey, Message, FileUpload, FileChunk  # noqa: F401
    from backend.models import TaskModel, TaskStepModel, TaskExecutionModel  # noqa: F401
    from backend.models import TaskApprovalModel  # noqa: F401
    from backend.models import TaskPolicyModel  # noqa: F401
    from backend.models import TaskPlanReviewModel  # noqa: F401
    from backend.models import ExecutionResultModel  # noqa: F401
    from backend.models import ExecutionRecordModel  # noqa: F401
    from backend.models import ExecutionEventModel  # noqa: F401
    from backend.models import ArtifactModel  # noqa: F401
    from backend.models import EvaluationRecordModel  # noqa: F401
    from backend.models import DAGDefinitionModel  # noqa: F401
    from backend.models import DAGNodeModel  # noqa: F401
    from backend.models import PolicyDecisionModel  # noqa: F401
    from backend.models import TeammateTemplate  # noqa: F401
    from backend.models import BoardTask  # noqa: F401
    from backend.models import SessionTrigger, SessionTurn  # noqa: F401
    from backend.models import User, Workspace, WorkspaceMember  # noqa: F401
    from backend.models import OrganizationRun  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if _is_sqlite:
            await conn.execute(text("PRAGMA journal_mode=WAL;"))
            await conn.execute(text("PRAGMA synchronous=NORMAL;"));

    if _is_sqlite:
        await _migrate_columns()

    # Seed preset templates on startup (ponytail: sync seed, routes/teammates.py lazy seed is a fallback)
    from backend.models import TeammateTemplate as TplModel
    from sqlalchemy import func as sa_func
    from backend.routes.teammates import PRESET_TEMPLATES
    async with async_session() as db:
        cnt = await db.execute(sa_func.count(TplModel.id))
        if cnt.scalar() == 0:
            for tpl in PRESET_TEMPLATES:
                db.add(TplModel(**tpl))
            await db.commit()


async def _migrate_columns() -> None:
    """Add any missing columns to existing tables (idempotent ALTER TABLE)."""
    from sqlalchemy import text

    expected = {
        "channels": [
            ("workspace_id", "VARCHAR", None),
        ],
        "teammates": [
            ("workspace_id", "VARCHAR", None),
        ],
        "apikeys": [
            ("workspace_id", "VARCHAR", None),
        ],
        "tasks": [
            ("review_status", "VARCHAR", "pending"),
            ("git_commit", "VARCHAR", None),
            ("files_changed", "JSON", "[]"),
            ("commands_run", "JSON", "[]"),
            ("test_result", "TEXT", ""),
            ("review_comments", "TEXT", ""),
            ("review_rounds", "INTEGER", "0"),
            ("replan_decisions", "JSON", "[]"),
            ("replan_count", "INTEGER", "0"),
            ("parent_task_id", "VARCHAR", None),
            ("child_task_ids", "JSON", "[]"),
            ("dependency", "JSON", "[]"),
            ("techlead_summary", "TEXT", ""),
            ("techlead_decision", "JSON", None),
            ("run_id", "VARCHAR", None),
        ],
        "task_steps": [
            ("deps", "JSON", "[]"),
        ],
        "board_tasks": [
            ("workspace_id", "VARCHAR", None),
            ("channel_id", "VARCHAR", None),
            ("source_message_id", "VARCHAR", None),
            ("title", "VARCHAR", None),
            ("description", "TEXT", ""),
            ("status", "VARCHAR", "open"),
            ("priority", "INTEGER", "2"),
            ("assignee_id", "VARCHAR", None),
            ("assignee_name", "VARCHAR", None),
            ("created_by", "VARCHAR", "system"),
            ("completed_at", "DATETIME", None),
        ],
        "session_triggers": [
            ("task_id", "VARCHAR", None),
            ("teammate_id", "VARCHAR", None),
            ("run_id", "VARCHAR", None),
            ("status", "VARCHAR", "active"),
            ("ended_at", "DATETIME", None),
        ],
        "session_turns": [
            ("turn_type", "VARCHAR", None),
            ("execution_id", "VARCHAR", None),
            ("failure", "TEXT", None),
            ("metadata_json", "JSON", None),
        ],
    }

    async with async_session() as db:
        for table, cols in expected.items():
            try:
                res = await db.execute(text(f"PRAGMA table_info({table})"))
                existing = {row[1] for row in res.fetchall()}
                for col, col_type, default in cols:
                    if col in existing:
                        continue
                    ddl = f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"
                    if default is not None:
                        ddl += f" DEFAULT '{default}'"
                    await db.execute(text(ddl))
                    logger.info("[DB] migrated: added column %s.%s", table, col)
            except Exception as e:
                logger.warning("[DB] column migration skipped for %s: %s", table, e)
        await db.commit()


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session


async def backfill_legacy_workspace() -> None:
    """ponytail: map every pre-auth row (workspace_id IS NULL) to one 'legacy'
    workspace so existing data lands in a workspace instead of breaking scope.
    Idempotent. Upgrade path: real per-tenant workspaces via /api/workspaces."""
    from sqlalchemy import text, select
    from backend.models import Workspace, WorkspaceMember, User

    async with async_session() as db:
        try:
            existing = (await db.execute(text("SELECT id FROM workspaces WHERE id = 'legacy'"))).first()
            if not existing:
                ws = Workspace(id="legacy", name="Default", owner_id="legacy")
                db.add(ws)
                await db.commit()
            # rows without a workspace → legacy
            for table in ("channels", "teammates", "apikeys"):
                await db.execute(
                    text(f"UPDATE {table} SET workspace_id = 'legacy' WHERE workspace_id IS NULL OR workspace_id = ''")
                )
            await db.commit()
        except Exception as e:
            logger.warning("[DB] legacy workspace backfill skipped: %s", e)
