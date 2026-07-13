import asyncio, sys, logging
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(name)s %(levelname)s %(message)s")
sys.path.insert(0, "/home/liunx/workspace/ai-team-hub/backend")
from backend.services.runtime.executor import ExecutionRuntime

async def main():
    rt = ExecutionRuntime(max_workers=4)
    tid = await rt.submit(description="hello", wait=False)
    print("submitted", tid)
    try:
        task = await asyncio.wait_for(rt.wait(tid, timeout=20.0), timeout=25.0)
        print("wait returned:", task.status if task else None, "| error:", task.error[:80] if task and task.error else None)
    except asyncio.TimeoutError:
        print("!!! wait TIMED OUT after 20s — event never set")

asyncio.run(main())
