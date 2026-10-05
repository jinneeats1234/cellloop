// Typed access to build-time environment variables (VITE_*). Documented in frontend/.env.example.
// Vite inlines these at build time, so they are public: never put secrets here.
// Runtime settings that the backend owns (auth mode, AI provider, targets) come from GET /api/config.

function str(value: string | undefined, fallback = ""): string {
  return (value ?? fallback).trim();
}

function positiveInt(value: string | undefined, fallback: number, name: string): number {
  if (value === undefined || value.trim() === "") return fallback;
  const n = Number(value);
  if (!Number.isInteger(n) || n <= 0) {
    console.warn(`[config] ${name}="${value}" is not a positive integer; using ${fallback}.`);
    return fallback;
  }
  return n;
}

const raw = import.meta.env;

export const env = {
  /** API origin. Empty = same origin (the dev server proxies /api; nginx does in Docker). */
  apiBase: str(raw.VITE_API_BASE).replace(/\/+$/, ""),
  /** Default request timeout. Slow AI endpoints use their own longer limits (see api/client.ts). */
  apiTimeoutMs: positiveInt(raw.VITE_API_TIMEOUT_MS, 30_000, "VITE_API_TIMEOUT_MS"),
  cognito: {
    domain: str(raw.VITE_COGNITO_DOMAIN).replace(/\/+$/, ""),
    clientId: str(raw.VITE_COGNITO_CLIENT_ID),
    redirectUri: str(raw.VITE_COGNITO_REDIRECT_URI) || `${window.location.origin}/auth/callback`,
  },
} as const;

export const cognitoConfigured = Boolean(env.cognito.domain && env.cognito.clientId);
