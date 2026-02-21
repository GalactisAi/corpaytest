import axios from 'axios';

/**
 * Base URL with /api exactly once: ${VITE_API_URL}/api (or '/api' when no env).
 * All API request paths must be relative to this (e.g. 'admin/auth/login', 'dashboard/revenue').
 * Do NOT use paths starting with /api (would double to .../api/api/...).
 */
export function getBaseURL(): string {
  const base = import.meta.env.VITE_API_URL;
  if (base != null && String(base).trim() !== '') {
    const trimmed = String(base).replace(/\/+$/, '');
    return trimmed ? `${trimmed}/api` : '/api';
  }
  return '/api';
}

/** Alias for login and other services: base for POST/GET (e.g. .../api). */
export const apiBaseURL = getBaseURL();

export const api = axios.create({
  baseURL: getBaseURL(),
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 60000, // 60s — slow database wake-ups don't crash initial login
});

// Log final request URL at runtime for verification; ensure FormData requests get multipart Content-Type
api.interceptors.request.use((config) => {
  const base = (config.baseURL || '').replace(/\/+$/, '');
  const path = config.url && config.url.startsWith('http') ? config.url : (config.url && config.url.startsWith('/') ? config.url : `/${config.url || ''}`);
  const finalUrl = path.startsWith('http') ? path : `${base}${path}`;
  console.log('[API]', config.method?.toUpperCase(), finalUrl);
  if (config.data instanceof FormData) {
    delete (config.headers as Record<string, unknown>)['Content-Type'];
  }
  return config;
});

/** Origin only (no /api) for routes like /health mounted at root. Uses VITE_API_URL when set. */
export function getOrigin(): string {
  const base = import.meta.env.VITE_API_URL;
  if (base != null && String(base).trim() !== '') return String(base).replace(/\/+$/, '');
  return typeof window !== 'undefined' ? window.location.origin : '';
}

// Request path should NOT start with / so we get baseURL + '/' + path (e.g. /api/admin/auth/login)
export function apiPath(path: string): string {
  const p = path.startsWith('/') ? path.slice(1) : path;
  const base = getBaseURL();
  return base.endsWith('/') ? `${base}${p}` : `${base}/${p}`;
}
