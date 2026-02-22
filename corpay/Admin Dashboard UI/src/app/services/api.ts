import axios from 'axios';

/**
 * Normalize the provided base (trim, drop trailing slashes). Returns null when empty.
 */
function normalizeBase(raw?: string | null): string | null {
  if (!raw) return null;
  const trimmed = String(raw).trim().replace(/\/+$/, '');
  return trimmed || null;
}

function productionFallbackBase(isBrowser: boolean): string | null {
  // If no VITE_API_URL is set and we are on the Vercel admin domain, point to the Railway backend.
  if (isBrowser && typeof window !== 'undefined') {
    const host = window.location.hostname;
    if (host.includes('finaltryadmin.vercel.app')) {
      return 'https://finaltry-production-0eb2.up.railway.app';
    }
  }
  return null;
}

/**
 * Build an API base URL that avoids common production pitfalls:
 * - Avoid mixed content on HTTPS (auto-upgrade http:// to https:// when possible)
 * - Avoid shipping localhost/127.0.0.1 in production (fallback to window.origin)
 * - Ensure /api is appended exactly once
 */
export function getBaseURL(): string {
  const envBase = normalizeBase(import.meta.env.VITE_API_URL);
  const isBrowser = typeof window !== 'undefined';

  let base = envBase;

  if (envBase && isBrowser) {
    const isLocalEnv = /^(https?:\/\/)?(localhost|127\.0\.0\.1)([:/]|$)/i.test(envBase);
    const isHttpsPage = window.location.protocol === 'https:';
    const currentHostIsLocal = /^(localhost|127\.0\.0\.1)$/i.test(window.location.hostname);

    // If env points to localhost but app is running on a real domain, use current origin instead.
    if (isLocalEnv && !currentHostIsLocal && window.location.origin) {
      base = window.location.origin;
    }

    // Auto-upgrade to https to avoid mixed-content blocks on production domains.
    if (base?.startsWith('http://') && isHttpsPage) {
      base = `https://${base.replace(/^http:\/\//i, '')}`;
    }
  }

  if (!base) {
    // No env provided: try a production fallback, then current origin, else /api
    base = productionFallbackBase(isBrowser) || (isBrowser && window.location.origin ? window.location.origin : '/api');
  }

  const finalBase = String(base).replace(/\/+$/, '');
  if (!finalBase) return '/api';
  const hasApiSuffix = /\/api$/i.test(finalBase);
  return hasApiSuffix ? finalBase : `${finalBase}/api`;
}

/** Alias for login and other services: base for POST/GET (e.g. .../api). */
export const apiBaseURL = getBaseURL();

export const api = axios.create({
  baseURL: apiBaseURL,
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

/**
 * Origin (no /api) for endpoints like /health.
 * Mirrors the base URL normalization to avoid localhost/mixed-content issues.
 */
export function getOrigin(): string {
  const envBase = normalizeBase(import.meta.env.VITE_API_URL);
  const isBrowser = typeof window !== 'undefined';

  let origin = envBase;

  if (envBase && isBrowser) {
    const isLocalEnv = /^(https?:\/\/)?(localhost|127\.0\.0\.1)([:/]|$)/i.test(envBase);
    const isHttpsPage = window.location.protocol === 'https:';
    const currentHostIsLocal = /^(localhost|127\.0\.0\.1)$/i.test(window.location.hostname);

    if (isLocalEnv && !currentHostIsLocal && window.location.origin) {
      origin = window.location.origin;
    }

    if (origin?.startsWith('http://') && isHttpsPage) {
      origin = `https://${origin.replace(/^http:\/\//i, '')}`;
    }
  }

  if (!origin) {
    origin = productionFallbackBase(isBrowser) || (isBrowser && window.location.origin ? window.location.origin : '');
  }

  return String(origin).replace(/\/+$/, '');
}

// Request path should NOT start with / so we get baseURL + '/' + path (e.g. /api/admin/auth/login)
export function apiPath(path: string): string {
  const p = path.startsWith('/') ? path.slice(1) : path;
  const base = getBaseURL();
  return base.endsWith('/') ? `${base}${p}` : `${base}/${p}`;
}
