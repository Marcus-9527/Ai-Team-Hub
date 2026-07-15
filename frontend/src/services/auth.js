/**
 * Shared API auth — injects the JWT (Bearer) into every backend request.
 * The master API key (VITE_API_KEY) is now optional legacy fallback only;
 * the SPA authenticates with its own account token.
 */
export const BASE = import.meta.env.VITE_API_BASE || '';
const TOKEN_KEY = 'aihub_token';
const USER_KEY = 'aihub_user';
const WS_KEY = 'aihub_ws';

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || '';
}
export function setSession(token, user, workspaceId) {
  localStorage.setItem(TOKEN_KEY, token);
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
  if (workspaceId) localStorage.setItem(WS_KEY, workspaceId);
}
export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(WS_KEY);
}
export function getSessionUser() {
  try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null'); } catch { return null; }
}
export function isLoggedIn() {
  return !!getToken();
}

export function authHeaders(extra = {}) {
  const h = { 'Content-Type': 'application/json', ...extra };
  const t = getToken();
  if (t) h['Authorization'] = `Bearer ${t}`;
  return h;
}

export function authFetch(url, options = {}) {
  const headers = { ...authHeaders(), ...(options.headers || {}) };
  return fetch(url, { ...options, headers });
}
