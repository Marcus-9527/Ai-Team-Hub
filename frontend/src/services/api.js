/**
 * API client for AI Team Hub backend.
 */
import { BASE, authHeaders, getToken } from './auth';
import { toast } from './toast';

const TIMEOUT_MS = 15000;

async function request(url, options = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  let res;
  try {
    res = await fetch(`${BASE}${url}`, {
      headers: { ...authHeaders(), ...options.headers },
      ...options,
      signal: ctrl.signal,
    });
  } catch (e) {
    clearTimeout(timer);
    const msg = e.name === 'AbortError'
      ? '请求超时,后端可能没有响应'
      : '无法连接后端,请检查服务是否已启动';
    toast(msg);
    throw new Error(msg);
  }
  clearTimeout(timer);

  if (!res.ok) {
    const text = await res.text();
    let msg = text;
    try { msg = JSON.parse(text).detail || text; } catch {}
    toast(msg);
    throw new Error(msg);
  }
  return res.json();
}

// ── Auth ──
export const register = (email, password, displayName = '') =>
  request('/api/auth/register', { method: 'POST', body: JSON.stringify({ email, password, display_name: displayName }) });
export const login = (email, password) =>
  request('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
export const authMe = () => request('/api/auth/me');

// ── Health ──
export const healthCheck = () => request('/api/health');

// ── Channels ──
export const listChannels = () => request('/api/channels');
export const createChannel = (data) => request('/api/channels', { method: 'POST', body: JSON.stringify(data) });
export const deleteChannel = (id) => request(`/api/channels/${id}`, { method: 'DELETE' });

// ── Messages ──
export const listMessages = (channelId) => request(`/api/messages/${channelId}`);

/** Send user message — returns Response for streaming. */
export const sendMessage = (channelId, content, authorName = 'You', teammateIds = null) => {
  const body = { content, author_name: authorName };
  if (teammateIds) {
    body.teammate_ids = Array.isArray(teammateIds) ? teammateIds : [teammateIds];
  }
  return fetch(`${BASE}/api/messages/${channelId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(getToken() ? { 'Authorization': `Bearer ${getToken()}` } : {}) },
    body: JSON.stringify(body),
  });
};

/** Upload a file to a channel */
export const uploadFileMsg = (channelId, file, authorName = 'You') => {
  const form = new FormData();
  form.append('file', file);
  return fetch(`${BASE}/api/messages/${channelId}/file`, {
    method: 'POST',
    body: form,
    headers: getToken() ? { 'Authorization': `Bearer ${getToken()}`, 'X-Author-Name': authorName } : { 'X-Author-Name': authorName },
  });
};

/** Clear messages in a channel */
export const clearMessages = (channelId) => request(`/api/messages/${channelId}`, { method: 'DELETE' });

// ── API Keys ──
export const listAPIKeys = () => request('/api/apikeys');
export const createAPIKey = (data) => request('/api/apikeys', { method: 'POST', body: JSON.stringify(data) });
export const deleteAPIKey = (id) => request(`/api/apikeys/${id}`, { method: 'DELETE' });

// ── Teams ──
export const createTeamFromTemplate = (data) =>
  request('/api/teams/template', { method: 'POST', body: JSON.stringify(data) });
export const listTeammates = () => request('/api/teammates');
export const createTeammate = (data) => request('/api/teammates', { method: 'POST', body: JSON.stringify(data) });
export const updateTeammate = (id, data) => request(`/api/teammates/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
export const deleteTeammate = (id) => request(`/api/teammates/${id}`, { method: 'DELETE' });
export const addTeammateToChannel = (channelId, teammateId) =>
  request(`/api/channels/${channelId}/teammates/${teammateId}`, { method: 'POST' });
export const removeTeammateFromChannel = (channelId, teammateId) =>
  request(`/api/channels/${channelId}/teammates/${teammateId}`, { method: 'DELETE' });
export const sendSystemMessage = (channelId, content) =>
  request(`/api/messages/${channelId}/system`, { method: 'POST', body: JSON.stringify({ content }) });

// ── Models ──
export const fetchModels = (providerId, apiKeyId = '') => {
  const qs = apiKeyId ? `?api_key_id=${encodeURIComponent(apiKeyId)}` : '';
  return request(`/api/models/${providerId}${qs}`);
};

export const fetchAllModels = () => request('/api/models');

export const triggerModelSync = () => request('/api/models/sync', { method: 'POST' });

export const fetchOpenRouterModels = async () => {
  const data = await request('/api/models/openrouter');
  const list = data?.models || [];
  return list.map(m => ({ id: m.id, name: m.name || m.id, context_length: m.context_length, is_free: m.is_free, pricing: m.pricing }));
};

// ── Brain API (Phase 12) ──
export const listBrainFragments = (teammateId) => request(`/api/brain/fragments/${teammateId}`);
export const getBrainFragment = (teammateId, fragmentType) => request(`/api/brain/fragments/${teammateId}/${fragmentType}`);
export const listBrainFragmentVersions = (teammateId, fragmentType) =>
  request(`/api/brain/fragments/${teammateId}/${fragmentType}/versions`);
export const rollbackBrainFragment = (teammateId, fragmentType, targetVersion) =>
  request(`/api/brain/fragments/${teammateId}/${fragmentType}/rollback?target_version=${targetVersion}`, { method: 'POST' });
export const getBrainLoaderPrompt = (teammateId, extraContext = '') =>
  request(`/api/brain/loader/${teammateId}?extra_context=${encodeURIComponent(extraContext)}`);
export const listBrainFragmentTypes = () => request('/api/brain/fragment-types');
export const getBrainOverview = () => request('/api/brain');
export const triggerBrainConsolidation = (lookbackHours = 48) =>
  request(`/api/brain/consolidate?lookback_hours=${lookbackHours}`, { method: 'POST' });

// ── Phase 22: Teammate Profile ──
export const getTeammateProfile = (teammateId) =>
  request(`/api/teammates/${teammateId}/profile`);

// ── Phase 22: Execution Room ──
export const listExecutions = (status = '', limit = 20, offset = 0) => {
  let url = '/api/executions?';
  if (status) url += `status=${status}&`;
  url += `limit=${limit}&offset=${offset}`;
  return request(url);
};
export const getExecution = (executionId) =>
  request(`/api/executions/${executionId}`);

// ── Phase 22: Workspace Explorer ──
export const listArtifacts = (taskId = '', type = '', limit = 50) => {
  let url = '/api/artifacts?';
  if (taskId) url += `task_id=${taskId}&`;
  if (type) url += `type=${type}&`;
  url += `limit=${limit}`;
  return request(url);
};

// ── Phase 13: Autonomous Collaboration ──

// Teammate Runtime State
export const listTeammateStates = (filterState = '') =>
  request(`/api/autonomous/states${filterState ? `?filter_state=${filterState}` : ''}`);
export const getTeammateState = (teammateId) =>
  request(`/api/autonomous/states/${teammateId}`);
export const setTeammateState = (teammateId, state, taskId = '') =>
  request('/api/autonomous/states', {
    method: 'POST',
    body: JSON.stringify({ teammate_id: teammateId, state, task_id: taskId }),
  });

// Cede Protocol
export const cedeDecide = (teammateId, teammateName, message, channelId = '', messageId = '') =>
  request('/api/autonomous/cede/decide', {
    method: 'POST',
    body: JSON.stringify({ teammate_id: teammateId, teammate_name: teammateName, message, channel_id: channelId, message_id: messageId }),
  });

// Brain Proposals
export const listProposals = (status = '', teammateId = '', limit = 50) => {
  let url = '/api/autonomous/proposals?';
  if (status) url += `status=${status}&`;
  if (teammateId) url += `teammate_id=${teammateId}&`;
  url += `limit=${limit}`;
  return request(url);
};
export const listPendingProposals = () =>
  request('/api/autonomous/proposals/pending');
export const approveProposal = (proposalId, resolvedBy = 'user') =>
  request('/api/autonomous/proposals/approve', {
    method: 'POST',
    body: JSON.stringify({ proposal_id: proposalId, resolved_by: resolvedBy }),
  });
export const rejectProposal = (proposalId, resolvedBy = 'user') =>
  request('/api/autonomous/proposals/reject', {
    method: 'POST',
    body: JSON.stringify({ proposal_id: proposalId, resolved_by: resolvedBy }),
  });

// ── Teammate Blueprint Templates ──
export const listTemplates = () => request('/api/teammates/templates');
export const createFromTemplate = (data) =>
  request('/api/teammates/from-template', { method: 'POST', body: JSON.stringify(data) });

// ── Automation v2: Teammate Autonomous Jobs ──
export const listAutomationJobs = () => request('/api/automation-jobs');
export const createAutomationJob = (data) =>
  request('/api/automation-jobs', { method: 'POST', body: JSON.stringify(data) });
export const updateAutomationJob = (id, data) =>
  request(`/api/automation-jobs/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
export const deleteAutomationJob = (id) =>
  request(`/api/automation-jobs/${id}`, { method: 'DELETE' });
export const triggerAutomationJob = (id) =>
  request(`/api/automation-jobs/${id}/trigger`, { method: 'POST' });
export const listAutomationRuns = (jobId) =>
  request(`/api/automation-jobs/${jobId}/runs`);
export const listAllAutomationRuns = () =>
  request('/api/automation-jobs/runs');
// ── Board Tasks (Phase 28: claim board) ──
export const listBoardTasks = (channelId) =>
  request(`/api/channels/${channelId}/tasks`);
export const createBoardTask = (data) =>
  request('/api/board-tasks', { method: 'POST', body: JSON.stringify(data) });
export const updateBoardTask = (id, data) =>
  request(`/api/board-tasks/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
export const claimBoardTask = (id, assigneeId, assigneeName = '') =>
  request(`/api/board-tasks/${id}/claim`, {
    method: 'PATCH',
    body: JSON.stringify({ assignee_id: assigneeId, assignee_name: assigneeName }),
  });

