"""
Database setup — SQLite via aiosqlite, async SQLAlchemy.
"""
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

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
    from backend.models import Channel, Teammate, APIKey, Message  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("PRAGMA journal_mode=WAL;"))
        await conn.execute(text("PRAGMA synchronous=NORMAL;"))


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session
