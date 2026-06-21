/**
 * API client for AI Team Hub backend.
 */
const BASE = import.meta.env.VITE_API_BASE || 'https://ai-team-hub.wt5371.workers.dev/api';

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
export const listChannels = () => request('/channels');
export const createChannel = (data) => request('/channels', { method: 'POST', body: JSON.stringify(data) });
export const deleteChannel = (id) => request(`/channels/${id}`, { method: 'DELETE' });
export const addTeammateToChannel = (channelId, teammateId) =>
  request(`/channels/${channelId}/teammates/${teammateId}`, { method: 'POST' });
export const removeTeammateFromChannel = (channelId, teammateId) =>
  request(`/channels/${channelId}/teammates/${teammateId}`, { method: 'DELETE' });

// ── Teammates ──
export const listTeammates = () => request('/teammates');
export const createTeammate = (data) => request('/teammates', { method: 'POST', body: JSON.stringify(data) });
export const updateTeammate = (id, data) => request(`/teammates/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
export const deleteTeammate = (id) => request(`/teammates/${id}`, { method: 'DELETE' });

// ── API Keys ──
export const listAPIKeys = () => request('/apikeys');
export const createAPIKey = (data) => request('/apikeys', { method: 'POST', body: JSON.stringify(data) });
export const deleteAPIKey = (id) => request(`/apikeys/${id}`, { method: 'DELETE' });

// ── Messages ──
export const listMessages = (channelId) => request(`/messages/${channelId}`);

/** Send user message + optionally trigger AI teammate. Returns Response for streaming. */
export const sendMessage = (channelId, content, teammateId = null, authorName = 'You', attachments = null, skipUserSave = false) =>
  fetch(`${BASE}/messages/${channelId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, teammate_id: teammateId, author_name: authorName, attachments, skip_user_save: skipUserSave }),
  });

/** Post a system message (e.g. 'xxx joined the channel') */
export const sendSystemMessage = (channelId, content) =>
  request(`/messages/${channelId}/system`, { method: 'POST', body: JSON.stringify({ content }) });

/** Upload a file to a channel */
export const uploadFileMsg = (channelId, file, authorName = 'You') => {
  const form = new FormData();
  form.append('file', file);
  form.append('author_name', authorName);
  return fetch(`${BASE}/messages/${channelId}/file`, { method: 'POST', body: form });
};

// ── Messages ──
export const clearMessages = (channelId) => request(`/messages/${channelId}`, { method: 'DELETE' });

// ── Models ──
export const fetchModels = (providerId, apiKeyId = '') => {
  const qs = apiKeyId ? `?api_key_id=${encodeURIComponent(apiKeyId)}` : '';
  return request(`/models/${providerId}${qs}`);
};

/** Fetch OpenRouter models directly (public API, no key needed) */
export const fetchOpenRouterModels = async () => {
  const res = await fetch('https://openrouter.ai/api/v1/models');
  if (!res.ok) throw new Error('Failed to fetch OpenRouter models');
  const data = await res.json();
  return (data.data || []).map(m => ({
    id: m.id,
    name: m.name || m.id,
    context_length: m.context_length || 0,
    is_free: (m.pricing?.prompt === '0'),
    pricing: m.pricing || {},
  }));
};
