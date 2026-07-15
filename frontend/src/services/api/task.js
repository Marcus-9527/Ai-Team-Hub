/**
 * api/task.js — Task REST API Client
 *
 * Matches backend routes/tasks.py (v2.5+ Task Runtime).
 * All methods return parsed JSON, throw on non-2xx.
 */
import { BASE, authHeaders } from '../auth';

async function request(url, options = {}) {
  const res = await fetch(`${BASE}${url}`, {
    headers: { ...authHeaders(), ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    let msg = text;
    try { msg = JSON.parse(text).detail || text; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

// ── Task CRUD ──

/** Create a new task. */
export const createTask = (data) =>
  request('/api/tasks', { method: 'POST', body: JSON.stringify(data) });

/** List tasks with optional filters. */
export const listTasks = (params = {}) => {
  const qs = new URLSearchParams();
  if (params.channel_id) qs.set('channel_id', params.channel_id);
  if (params.status) qs.set('status', params.status);
  if (params.workspace_id) qs.set('workspace_id', params.workspace_id);
  if (params.limit) qs.set('limit', String(params.limit));
  if (params.offset) qs.set('offset', String(params.offset));
  return request(`/api/tasks${qs.toString() ? `?${qs}` : ''}`);
};

/** Get task detail (with steps). */
export const getTask = (taskId) =>
  request(`/api/tasks/${taskId}`);

/** Update task metadata. */
export const updateTask = (taskId, data) =>
  request(`/api/tasks/${taskId}`, { method: 'PATCH', body: JSON.stringify(data) });

/** Delete a task. */
export const deleteTask = (taskId) =>
  request(`/api/tasks/${taskId}`, { method: 'DELETE' });

// ── Task Lifecycle ──

export const planTask = (taskId) =>
  request(`/api/tasks/${taskId}/plan`, { method: 'POST' });

export const executeTask = (taskId) =>
  request(`/api/tasks/${taskId}/execute`, { method: 'POST' });

export const pauseTask = (taskId) =>
  request(`/api/tasks/${taskId}/pause`, { method: 'POST' });

export const resumeTask = (taskId) =>
  request(`/api/tasks/${taskId}/resume`, { method: 'POST' });

export const cancelTask = (taskId) =>
  request(`/api/tasks/${taskId}/cancel`, { method: 'POST' });

export const completeTask = (taskId) =>
  request(`/api/tasks/${taskId}/complete`, { method: 'POST' });

export const failTask = (taskId) =>
  request(`/api/tasks/${taskId}/fail`, { method: 'POST' });

// ── Task Steps ──

export const addStep = (taskId, data) =>
  request(`/api/tasks/${taskId}/steps`, { method: 'POST', body: JSON.stringify(data) });

export const listSteps = (taskId) =>
  request(`/api/tasks/${taskId}/steps`);

export const getStep = (taskId, stepId) =>
  request(`/api/tasks/${taskId}/steps/${stepId}`);

export const updateStep = (taskId, stepId, data) =>
  request(`/api/tasks/${taskId}/steps/${stepId}`, { method: 'PATCH', body: JSON.stringify(data) });

// ── Progress & Executions ──

export const getTaskProgress = (taskId) =>
  request(`/api/tasks/${taskId}/progress`);

export const listExecutions = (taskId, stepId) =>
  request(`/api/tasks/${taskId}/executions`, {
    method: 'POST',
    body: JSON.stringify({ step_id: stepId }),
  });

// V3.0 Phase B: Task Intelligence Dashboard
/** List all executions for a task (across all steps). */
export const getTaskExecutions = (taskId) =>
  request(`/api/tasks/${taskId}/executions`);

/** List all execution results for a task. */
export const getTaskResults = (taskId) =>
  request(`/api/tasks/${taskId}/results`);

/** Get aggregated analytics for a task. */
export const getTaskAnalytics = (taskId) =>
  request(`/api/tasks/${taskId}/analytics`);

// V3.1 Phase B: Memory Workspace API
/** Get task memory from all levels. */
export const getTaskMemory = (taskId) =>
  request(`/api/tasks/${taskId}/memory`);


// ── Approvals (Phase C1) ──

export const listApprovals = (taskId, status) => {
  const qs = status ? `?status=${encodeURIComponent(status)}` : '';
  return request(`/api/tasks/${taskId}/approvals${qs}`);
};

export const approveApproval = (approvalId, data = {}) =>
  request(`/api/tasks/approvals/${approvalId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ approved_by: 'user', ...data }),
  });

export const rejectApproval = (approvalId, data = {}) =>
  request(`/api/tasks/approvals/${approvalId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ approved_by: 'user', ...data }),
  });

// ── Plan ──

export const getTaskPlan = (taskId) =>
  request(`/api/tasks/${taskId}/plan`);

export const applyTaskPlan = (taskId, force = false) =>
  request(`/api/tasks/${taskId}/plan/apply`, {
    method: 'POST',
    body: JSON.stringify({ force }),
  });

// ── Policy ──

export const getTaskPolicy = (taskId) =>
  request(`/api/tasks/${taskId}/policy`);

export const updateTaskPolicy = (taskId, data) =>
  request(`/api/tasks/${taskId}/policy`, { method: 'PUT', body: JSON.stringify(data) });

// ── Phase 27: DAG & Runs ──

export const getTaskDag = (taskId) =>
  request(`/api/tasks/${taskId}/dag`);

export const listTaskRuns = (taskId) =>
  request(`/api/tasks/${taskId}/runs`);

export const getTaskRunDetail = (taskId, runId) =>
  request(`/api/tasks/${taskId}/runs/${runId}`);
