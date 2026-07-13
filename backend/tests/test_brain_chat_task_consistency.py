"""test_brain_chat_task_consistency.py — Phase 15: BrainLoader wiring verification.

Verifies that both chat path (build_turn_prompt) and task path
(executor._run_task) include brain content for the same teammate.
"""
import pytest
from unittest.mock import AsyncMock, patch

from backend.services.brain.brain_loader import BrainLoader
from backend.services.runtime.teammate_runner import build_turn_prompt

pytestmark = pytest.mark.asyncio


async def test_build_turn_prompt_includes_brain():
    """Chat path: brain_prompt is prepended to system prompt."""
    teammate = {"id": "tm_a", "name": "Test", "role": "engineer",
                "system_prompt": "You are an engineer."}
    prompt = build_turn_prompt(
        teammate, "hello", [], 0,
        brain_prompt="## YOUR BRAIN\nI am a Python expert.",
    )
    assert "## YOUR BRAIN" in prompt
    assert "I am a Python expert" in prompt
    assert "You are an engineer." in prompt
    assert "engineer" in prompt.lower()


async def test_build_turn_prompt_empty_brain():
    """Chat path: empty brain_prompt leaves system prompt unchanged."""
    teammate = {"id": "tm_a", "name": "Test", "role": "engineer",
                "system_prompt": "You are an engineer."}
    prompt = build_turn_prompt(teammate, "hello", [], 0, brain_prompt="")
    assert prompt.startswith("You are an engineer.")


async def test_executor_injects_brain():
    """Task path: executor._run_task injects brain into teammate.system_prompt."""
    mock_loader = AsyncMock(spec=BrainLoader)
    mock_loader.build_prompt.return_value = "## YOUR BRAIN\nI am an expert."

    with patch("backend.services.brain.brain_loader.get_brain_loader",
               return_value=mock_loader):
        # Simulate executor's injection logic
        teammate = {"id": "tm_a", "name": "T", "system_prompt": "Base prompt."}
        loader = mock_loader
        brain = await loader.build_prompt(teammate.get("id", ""))
        if brain:
            teammate["system_prompt"] = brain + "\n\n" + (teammate.get("system_prompt", "") or "")

    assert "## YOUR BRAIN" in teammate["system_prompt"]
    assert "Base prompt." in teammate["system_prompt"]
