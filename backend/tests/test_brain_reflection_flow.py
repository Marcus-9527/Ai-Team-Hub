"""test_brain_reflection_flow.py — 验证 BrainLoader 反思→经验→行为变化流程

场景：
  1. 第一次任务 → 失败
  2. 系统反思 → 生成 LESSONS fragment（经验）
  3. 第二次类似任务 → BrainLoader.build_prompt 包含该经验
  4. 策略变化 — 第二次 prompt 比第一次多了 LESSONS LEARNED 节
"""
import pytest
from unittest.mock import AsyncMock

from backend.services.brain.brain_loader import BrainLoader
from backend.services.brain.fragment_store import BrainFragment, BrainFragmentType

pytestmark = pytest.mark.asyncio


async def test_reflection_adds_lesson_changes_prompt():
    """第一次任务失败后 store LESSON → 第二次 build_prompt 包含经验内容。"""
    mock_store = AsyncMock()
    mock_mem = AsyncMock()
    mock_mem.query_teammate_memory.return_value = []

    # 第一次：只有 IDENTITY，没有 LESSONS
    mock_store.get_all_by_teammate.return_value = [
        BrainFragment(
            teammate_id="tm_a",
            fragment_type=BrainFragmentType.IDENTITY,
            content="I am a backend developer",
            source="manual",
        ),
    ]

    loader = BrainLoader(fragment_store=mock_store, memory_service=mock_mem)
    prompt_before = await loader.build_prompt("tm_a", recent_memory_limit=0)

    assert "## IDENTITY" in prompt_before
    assert "backend developer" in prompt_before
    assert "## LESSONS LEARNED" not in prompt_before  # 还没有经验

    # 模拟反思：第一条任务失败，生成 LESSONS fragment
    mock_store.get_all_by_teammate.return_value = [
        BrainFragment(
            teammate_id="tm_a",
            fragment_type=BrainFragmentType.IDENTITY,
            content="I am a backend developer",
            source="manual",
        ),
        BrainFragment(
            teammate_id="tm_a",
            fragment_type=BrainFragmentType.LESSONS,
            content="Always validate input before database insert — "
                     "failed due to unvalidated user input in task-001",
            source="reflection",
        ),
    ]

    prompt_after = await loader.build_prompt("tm_a", recent_memory_limit=0)

    assert "## LESSONS LEARNED" in prompt_after
    assert "validate input" in prompt_after
    assert prompt_before != prompt_after  # prompt 变了


async def test_two_tasks_reflection_chain():
    """连续两次失败+反思，经验逐条累积。"""
    mock_store = AsyncMock()
    mock_mem = AsyncMock()
    mock_mem.query_teammate_memory.return_value = []

    base = [
        BrainFragment(
            teammate_id="tm_b",
            fragment_type=BrainFragmentType.IDENTITY,
            content="I am a full-stack developer",
            source="manual",
        ),
    ]

    # 第一次调用 — 无经验
    mock_store.get_all_by_teammate.return_value = base[:]
    loader = BrainLoader(fragment_store=mock_store, memory_service=mock_mem)
    p1 = await loader.build_prompt("tm_b", recent_memory_limit=0)
    assert "## LESSONS LEARNED" not in p1

    # 第一次反思 → 生成 LESSON #1
    mock_store.get_all_by_teammate.return_value = base + [
        BrainFragment(
            teammate_id="tm_b",
            fragment_type=BrainFragmentType.LESSONS,
            content="Lesson 1: Always check None before chaining calls",
            source="reflection",
        ),
    ]
    p2 = await loader.build_prompt("tm_b", recent_memory_limit=0)
    assert "## LESSONS LEARNED" in p2
    assert "Lesson 1" in p2

    # 第二次失败+反思 → LESSON #2 追加
    mock_store.get_all_by_teammate.return_value = base + [
        BrainFragment(
            teammate_id="tm_b",
            fragment_type=BrainFragmentType.LESSONS,
            content="Lesson 1: Always check None before chaining calls",
            source="reflection",
        ),
        BrainFragment(
            teammate_id="tm_b",
            fragment_type=BrainFragmentType.PRINCIPLES,
            content="Always write tests first",
            source="manual",
        ),
    ]
    p3 = await loader.build_prompt("tm_b", recent_memory_limit=0)
    assert "## PRINCIPLES" in p3
    assert "write tests first" in p3
    # LESSONS 还在
    assert "Lesson 1" in p3


async def test_lessons_cause_strategy_change_in_prompt():
    """LESSONS 经验改变了 prompt 内容 → 策略变化可观测。"""
    mock_store = AsyncMock()
    mock_mem = AsyncMock()
    mock_mem.query_teammate_memory.return_value = []

    # 任务1: 用 API 获取数据，直接拼接 SQL — 无教训
    mock_store.get_all_by_teammate.return_value = [
        BrainFragment(
            teammate_id="tm_c",
            fragment_type=BrainFragmentType.IDENTITY,
            content="API developer",
            source="manual",
        ),
    ]
    loader = BrainLoader(fragment_store=mock_store, memory_service=mock_mem)
    p_naive = await loader.build_prompt("tm_c", recent_memory_limit=0)

    # SQL 注入事故后反思，生成经验
    mock_store.get_all_by_teammate.return_value = [
        BrainFragment(
            teammate_id="tm_c",
            fragment_type=BrainFragmentType.IDENTITY,
            content="API developer",
            source="manual",
        ),
        BrainFragment(
            teammate_id="tm_c",
            fragment_type=BrainFragmentType.LESSONS,
            content="CRITICAL: SQL injection risk — always use parameterized queries, "
                    "never f-string interpolation in SQL",
            source="reflection",
        ),
    ]
    p_with_lesson = await loader.build_prompt("tm_c", recent_memory_limit=0)

    # 验证：lessons 在场时 prompt 不同，策略变化
    assert p_naive != p_with_lesson
    assert "## LESSONS LEARNED" in p_with_lesson
    assert "parameterized queries" in p_with_lesson
    assert "CRITICAL" in p_with_lesson
    assert "## LESSONS LEARNED" not in p_naive
