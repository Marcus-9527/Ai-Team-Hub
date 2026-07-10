/**
 * API client for AI Team Hub backend.
 */
const BASE = import.meta.env.VITE_API_BASE || '';

async function request(url, options = {}) {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
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
    headers: { 'Content-Type': 'application/json' },
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
    headers: { 'X-Author-Name': authorName },
  });
};

/** Clear messages in a channel */
export const clearMessages = (channelId) => request(`/api/messages/${channelId}`, { method: 'DELETE' });

// ── API Keys ──
export const listAPIKeys = () => request('/api/apikeys');
export const createAPIKey = (data) => request('/api/apikeys', { method: 'POST', body: JSON.stringify(data) });
export const deleteAPIKey = (id) => request(`/api/apikeys/${id}`, { method: 'DELETE' });

// ── Teammates ──
export const listTeammates = () => request('/api/teammates');
export const createTeammate = (data) => request('/api/teammates', { method: 'POST', body: JSON.stringify(data) });
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
  // 走后端代理避免 CORS
  const data = await request('/api/models/openrouter');
  // 后端返回 {provider, models: [...], count}
  const list = data?.models || [];
  return list.map(m => ({ id: m.id, name: m.name || m.id, context_length: m.context_length, is_free: m.is_free, pricing: m.pricing }));
};
