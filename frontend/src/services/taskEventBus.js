/**
 * taskEventBus.js — Global event emitter for task lifecycle events
 *
 * Decouples SSE parsers (ChannelView) from Task consumers.
 * Import and call `dispatch(event)` from any SSE stream that sees
 * task_started / step_started / step_completed / task_completed / approval_required.
 *
 * Subscribe via `subscribe(handler)` — returns unsubscribe fn.
 * Handlers receive the raw SSE event object.
 */
const handlers = new Set();

/** Dispatch a task event to all subscribers. */
export function dispatchTaskEvent(event) {
  handlers.forEach(fn => {
    try { fn(event); } catch (e) { console.error('[taskEventBus] handler error:', e); }
  });
}

/** Subscribe to task events. Returns unsubscribe function. */
export function subscribeTaskEvents(fn) {
  handlers.add(fn);
  return () => handlers.delete(fn);
}

/** Check if an SSE event is a task-related event type. */
export function isTaskEventType(type) {
  return [
    'task_started',
    'step_started',
    'step_completed',
    'task_completed',
    'approval_required',
    // V3.0 Phase B: Task Intelligence Dashboard
    'execution_started',
    'execution_completed',
    'execution_quality_updated',
    'plan_created',
    'approval_completed',
    // V3.1 Phase B: Memory Workspace
    'memory_updated',
  ].includes(type);
}
