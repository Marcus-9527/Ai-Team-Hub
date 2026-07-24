"""Phase 2.1: Session 模型升级验收。

Covers:
- SessionTrigger 新字段（task_id, teammate_id, status, ended_at）
- SessionTurn 新字段（turn_type, execution_id, failure, metadata）
- close_trigger / record_failed_turn
- TriggerType.SYSTEM
- 向后兼容（旧 caller 不传新参数仍能工作）
"""
import os, tempfile, atexit, asyncio

_db = tempfile.NamedTemporaryFile(suffix=".test-session.db", delete=False)
os.environ["AI_TEAM_HUB_DB"] = _db.name
os.environ["AI_TEAM_HUB_API_KEY"] = "test-key"
os.environ["AI_TEAM_HUB_AUTH_DISABLED"] = "1"

@atexit.register
def _cleanup():
    try:
        os.unlink(_db.name)
    except OSError:
        pass

from backend.database import init_db, async_session
asyncio.run(init_db())

from backend.models.session import (
    SessionTrigger, SessionTurn, TriggerType,
)
from backend.services.session.session_hooks import SessionHooks


def test_session_upgrade():
    """一次跑完所有新字段，不需要 fixtures。"""
    async def _run():
        async with async_session() as db:
            hooks = SessionHooks(db)

            # ── 1. SessionTrigger 新字段 ──
            t1 = await hooks.open_trigger(
                channel_id="ch_test", user_msg_id="msg_1",
                trigger_type=TriggerType.SYSTEM,
                task_id="task_abc", teammate_id="tm_xyz",
            )
            assert t1.task_id == "task_abc"
            assert t1.teammate_id == "tm_xyz"
            assert t1.status == "active"
            assert t1.ended_at is None
            assert t1.trigger_type == TriggerType.SYSTEM.value

            # ── 2. close_trigger ──
            await hooks.close_trigger(t1.id)
            await db.refresh(t1)
            assert t1.status == "completed"
            assert t1.ended_at is not None

            # ── 3. SessionTurn 新字段 ──
            turn = await hooks.start_turn(t1.id, teammate_id="tm_xyz")
            turn.turn_type = "llm_response"
            turn.execution_id = "exec_001"
            turn.failure = None
            turn.metadata_json = {"model": "gpt-4", "temperature": 0.7}
            await db.flush()

            await db.refresh(turn)
            assert turn.turn_type == "llm_response"
            assert turn.execution_id == "exec_001"
            assert turn.failure is None
            assert turn.metadata_json == {"model": "gpt-4", "temperature": 0.7}

            # ── 4. record_failed_turn ──
            ft = await hooks.record_failed_turn(
                t1.id, teammate_id="tm_xyz",
                failure="API rate limit exceeded",
                execution_id="exec_002",
                metadata={"error_code": 429},
            )
            assert ft.failure == "API rate limit exceeded"
            assert ft.execution_id == "exec_002"
            assert ft.metadata_json == {"error_code": 429}
            assert ft.action == "responded"

            # ── 5. 向后兼容：不加新参数 ──
            t2 = await hooks.open_trigger(
                channel_id="ch_old", user_msg_id="msg_legacy",
            )
            assert t2.task_id is None
            assert t2.teammate_id is None
            assert t2.status == "active"

            # ── 6. TriggerType.SYSTEM enum ──
            assert TriggerType.SYSTEM.value == "system"
            assert TriggerType.SYSTEM in TriggerType

            # ── 7. 关系验证 ──
            turns = await hooks.turns_for_trigger(t1.id)
            assert len(turns) >= 2  # start_turn + record_failed_turn

        await db.commit()
    asyncio.run(_run())
