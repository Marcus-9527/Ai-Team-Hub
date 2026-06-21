"""
shadow_verify.py — FSM vs Coordinator Shadow Mode Verification

Runs the SAME task through both:
  1. FSM orchestrator (orchestrator_fsm.py → /api/orchestrator/run)
  2. Legacy coordinator (coordinator.py → /api/coordinator/process)

Compares: output, latency, token usage.
"""

import asyncio
import json
import sys
import time
import uuid

sys.path.insert(0, "/home/liunx/workspace/ai-team-hub")

from backend.services.orchestrator_fsm import create_fsm_orchestrator
from backend.services.coordinator import get_coordinator
from backend.database import async_session
from sqlalchemy import select
from backend.models import APIKey

TASK = "Write a Python function that checks if a string is a valid email address using regex. Include 3 test cases."
PROVIDER = "deepseek"
MODEL = "deepseek-chat"


async def get_api_key(provider: str) -> str:
    try:
        async with async_session() as sess:
            result = await sess.execute(
                select(APIKey).where(APIKey.provider == provider).limit(1)
            )
            key_obj = result.scalar_one_or_none()
            if key_obj and key_obj.api_key:
                return key_obj.api_key
    except Exception:
        pass
    return ""


async def run_fsm(task: str, api_key: str) -> dict:
    """Run task through FSM orchestrator. Returns result + metrics."""
    orch = create_fsm_orchestrator(
        provider=PROVIDER,
        model=MODEL,
        api_key=api_key,
        max_retries=3,
    )

    start = time.monotonic()
    ctx = await orch.run(task)
    latency = time.monotonic() - start

    trace = orch.get_trace_report()
    events = trace.get("events", [])

    # Count LLM calls from trace
    llm_calls = sum(1 for e in events if e.get("type") == "agent_dispatch" or "dispatch" in str(e.get("step", "")))

    return {
        "engine": "FSM v4",
        "task_id": ctx.task_id,
        "trace_id": orch.trace_id,
        "state": ctx.state,
        "intent": ctx.intent,
        "plan": ctx.plan,
        "execution_result": ctx.execution_result,
        "review_result": ctx.review_result,
        "final_result": ctx.final_result[:500] if ctx.final_result else "",
        "final_result_len": len(ctx.final_result) if ctx.final_result else 0,
        "retry_count": ctx.retry_count,
        "error": ctx.error,
        "latency_s": round(latency, 3),
        "trace_events": len(events),
        "llm_calls": llm_calls,
        "trace_report": trace,
    }


async def run_coordinator(task: str) -> dict:
    """Run task through legacy coordinator. Returns result + metrics."""
    coord = get_coordinator()

    start = time.monotonic()
    result = await coord.process(task, intent="")
    latency = time.monotonic() - start

    return {
        "engine": "Coordinator v1",
        "task_id": result.task_id,
        "intent": result.metadata.get("intent", ""),
        "agents_used": result.metadata.get("agents_used", []),
        "agent_outputs": [
            {
                "agent_id": o.agent_id,
                "result": o.result[:300] if o.result else "",
                "confidence": o.confidence,
                "tokens_used": o.tokens_used,
            }
            for o in result.agent_outputs
        ],
        "final_result": result.final_result[:500] if result.final_result else "",
        "final_result_len": len(result.final_result) if result.final_result else 0,
        "merged": result.merged,
        "latency_s": round(latency, 3),
        "llm_calls": len(result.agent_outputs),
    }


def compare(fsm: dict, coord: dict) -> dict:
    """Compare FSM vs Coordinator results."""
    return {
        "output_length_diff": fsm["final_result_len"] - coord["final_result_len"],
        "latency_diff_s": round(fsm["latency_s"] - coord["latency_s"], 3),
        "fsm_latency_s": fsm["latency_s"],
        "coord_latency_s": coord["latency_s"],
        "fsm_llm_calls": fsm["llm_calls"],
        "coord_llm_calls": coord["llm_calls"],
        "fsm_retries": fsm["retry_count"],
        "fsm_error": fsm["error"],
        "fsm_state": fsm["state"],
        "both_produced_output": bool(fsm["final_result"] and coord["final_result"]),
        "fsm_output_preview": fsm["final_result"][:200],
        "coord_output_preview": coord["final_result"][:200],
    }


async def main():
    print("=" * 60)
    print("SHADOW VERIFICATION: FSM v4 vs Coordinator v1")
    print("=" * 60)
    print(f"\nTask: {TASK[:80]}...")
    print(f"Provider: {PROVIDER}, Model: {MODEL}\n")

    # Get API key
    api_key = await get_api_key(PROVIDER)
    if not api_key:
        print("ERROR: No API key found in database")
        sys.exit(1)
    print(f"API key: {api_key[:8]}...{api_key[-4:]}")

    # Run FSM
    print("\n" + "-" * 40)
    print("Running FSM v4...")
    print("-" * 40)
    try:
        fsm_result = await run_fsm(TASK, api_key)
        print(f"  State: {fsm_result['state']}")
        print(f"  Latency: {fsm_result['latency_s']}s")
        print(f"  LLM calls: {fsm_result['llm_calls']}")
        print(f"  Retries: {fsm_result['retry_count']}")
        print(f"  Output length: {fsm_result['final_result_len']}")
        if fsm_result['error']:
            print(f"  Error: {fsm_result['error']}")
    except Exception as e:
        print(f"  FSM FAILED: {e}")
        import traceback
        traceback.print_exc()
        fsm_result = {"error": str(e), "final_result": "", "final_result_len": 0, "latency_s": 0, "llm_calls": 0, "retry_count": 0, "state": "ERROR"}

    # Run Coordinator
    print("\n" + "-" * 40)
    print("Running Coordinator v1...")
    print("-" * 40)
    try:
        coord_result = await run_coordinator(TASK)
        print(f"  Latency: {coord_result['latency_s']}s")
        print(f"  LLM calls: {coord_result['llm_calls']}")
        print(f"  Agents used: {coord_result['agents_used']}")
        print(f"  Output length: {coord_result['final_result_len']}")
        print(f"  Merged: {coord_result['merged']}")
    except Exception as e:
        print(f"  Coordinator FAILED: {e}")
        import traceback
        traceback.print_exc()
        coord_result = {"error": str(e), "final_result": "", "final_result_len": 0, "latency_s": 0, "llm_calls": 0, "agents_used": [], "merged": False}

    # Compare
    print("\n" + "=" * 60)
    print("COMPARISON")
    print("=" * 60)
    comp = compare(fsm_result, coord_result)
    for k, v in comp.items():
        print(f"  {k}: {v}")

    # Save full results
    output = {
        "task": TASK,
        "provider": PROVIDER,
        "model": MODEL,
        "fsm": fsm_result,
        "coordinator": coord_result,
        "comparison": comp,
        "timestamp": time.time(),
    }
    with open("/home/liunx/workspace/ai-team-hub/shadow_verify_result.json", "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nFull results saved to shadow_verify_result.json")

    # Verdict
    print("\n" + "=" * 60)
    print("VERDICT")
    print("=" * 60)
    if fsm_result.get("state") == "DONE" and fsm_result.get("final_result"):
        if coord_result.get("final_result"):
            print("✅ FSM COMPLETE — both engines produced output")
            print(f"   FSM latency: {fsm_result['latency_s']}s vs Coordinator: {coord_result['latency_s']}s")
            if fsm_result['latency_s'] <= coord_result['latency_s'] * 1.5:
                print("   ✅ FSM latency is within 1.5x of coordinator")
            else:
                print("   ⚠️ FSM latency is >1.5x coordinator (expected: FSM has more steps)")
        else:
            print("✅ FSM COMPLETE — coordinator failed but FSM succeeded")
    else:
        print("❌ FSM DID NOT COMPLETE — coordinator still needed")


if __name__ == "__main__":
    asyncio.run(main())
