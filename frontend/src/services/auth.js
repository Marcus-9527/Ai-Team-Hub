/**
 * Shared API auth — injects the master API key (VITE_API_KEY) into every
 * backend request so the locked /api + /v1 routes accept the SPA.
 */
export const BASE = import.meta.env.VITE_API_BASE || '';
export const API_KEY = import.meta.env.VITE_API_KEY || '';
// Admin key — gates sensitive management write endpoints. Separate from the
// public master API key so it never has to live in the client bundle's plain
// sight the way VITE_API_KEY does. Set VITE_ADMIN_KEY at build time.
export const ADMIN_KEY = import.meta.env.VITE_ADMIN_KEY || '';

export function authHeaders(extra = {}) {
  const h = { 'Content-Type': 'application/json', ...extra };
  if (API_KEY) h['X-API-Key'] = API_KEY;
  if (ADMIN_KEY) h['X-Admin-Key'] = ADMIN_KEY;
  return h;
}

export function authFetch(url, options = {}) {
  const headers = { ...authHeaders(), ...(options.headers || {}) };
  return fetch(url, { ...options, headers });
}
