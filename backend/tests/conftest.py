"""
conftest.py — Shared test fixtures

Provides:
  - db_session: async database session for integration tests
"""

import pytest_asyncio

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from backend.database import Base

# Use an in-memory SQLite database for tests
TEST_DATABASE_URL = "sqlite+aiosqlite://"


@pytest_asyncio.fixture
async def db_session():
    """
    Create a clean in-memory database for each test.

    Creates all tables before the test and drops them after.
    Each test gets a dedicated session; changes are rolled back after the test.
    """
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create a session
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = session_factory()
    # ponytail: in-memory singletons (claim manager + teammate state) are NOT
    # torn down by the DB rollback above. Reset them so each test starts with
    # no stray claims / available teammates — otherwise a teammate registered
    # by one test silently assigns nodes in another (breaks fail-fast, etc.).
    from backend.services.autonomous.task_claim import get_claim_manager
    from backend.services.autonomous.teammate_state import get_state_manager
    cm = get_claim_manager()
    cm._claims = {}
    cm._owners = {}
    get_state_manager()._states = {}
    try:
        yield session
    finally:
        await session.rollback()
        await session.close()
        await engine.dispose()
