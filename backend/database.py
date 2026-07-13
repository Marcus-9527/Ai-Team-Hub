"""
Database setup: SQLite via aiosqlite, async SQLAlchemy.
"""
import logging
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger("database")

DB_PATH = os.environ.get("AI_TEAM_HUB_DB", os.path.join(os.path.dirname(__file__), "..", "data", "aiteamhub.db"))
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    """Create all tables + enable WAL mode for concurrent writes."""
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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("PRAGMA journal_mode=WAL;"))
        await conn.execute(text("PRAGMA synchronous=NORMAL;"))

    # ── Idempotent column migration (SQLite: create_all won't add columns
    #    to tables that already exist). Safe to run every startup. ──
    await _migrate_columns()


async def _migrate_columns() -> None:
    """Add any missing columns to existing tables (idempotent ALTER TABLE)."""
    from sqlalchemy import text
    from backend.database import async_session

    # (table, column, sql_type) — only columns added after the original schema.
    expected = {
        "tasks": [
            ("review_status", "VARCHAR", "pending"),
            ("git_commit", "VARCHAR", None),
            ("files_changed", "JSON", "[]"),
            ("commands_run", "JSON", "[]"),
            ("test_result", "TEXT", ""),
            ("review_comments", "TEXT", ""),
            ("review_rounds", "INTEGER", "0"),
            ("parent_task_id", "VARCHAR", None),
            ("child_task_ids", "JSON", "[]"),
            ("dependency", "JSON", "[]"),
        ],
        "task_steps": [
            ("deps", "JSON", "[]"),
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
