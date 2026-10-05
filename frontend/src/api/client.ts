import type {
  AppConfig,
  AuditEntry,
  Dashboard,
  DocumentInfo,
  Experiment,
  ExperimentDetail,
  FieldValue,
  QAResult,
  RecommendationResult,
  User,
} from "./types";

import { env } from "../config/env";

const BASE = env.apiBase;
const TOKEN_KEY = "cellloop.token";
/** AI-backed calls (extraction, Q&A, model fitting) legitimately take longer. */
const SLOW_MS = 180_000;

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: session lasts for this page only */
  }
}

/** Every failed API call surfaces as an ApiError with a message that is safe to show users. */
export class ApiError extends Error {
  constructor(
    /** HTTP status, or 0 when the request never got a response (offline, server down, timeout). */
    public status: number,
    /** Raw `detail` from the API (string, object or validation-error list). */
    public detail: unknown,
    /** Stable machine-readable code from the API, e.g. "not_found", "ai_rate_limited". */
    public code: string = "error",
    /** Server correlation ID (X-Request-ID): quote it when reporting a problem. */
    public requestId: string | null = null,
    message?: string,
  ) {
    super(message ?? ApiError.describe(status, detail));
    this.name = "ApiError";
  }

  get retryable(): boolean {
    return this.status === 0 || this.status === 429 || this.status >= 500;
  }

  static describe(status: number, detail: unknown): string {
    const fromDetail = (() => {
      if (typeof detail === "string" && detail) return detail;
      if (detail && typeof detail === "object" && !Array.isArray(detail)) {
        const m = (detail as Record<string, unknown>).message;
        if (typeof m === "string") return m;
      }
      if (Array.isArray(detail)) return detail.map((e) => (e as { msg?: string }).msg ?? String(e)).join("; ");
      return null;
    })();
    if (status === 401) return "Your session has expired. Please sign in again.";
    if (status === 403) return fromDetail ?? "You don't have permission to do that.";
    if (status === 404) return fromDetail ?? "We couldn't find what you were looking for.";
    if (status === 413) return fromDetail ?? "That file is too large.";
    if (status === 429) return "Too many requests. Please wait a moment and try again.";
    if (status >= 500) return fromDetail ?? "The server ran into a problem. Please try again.";
    return fromDetail ?? `Request failed (HTTP ${status}).`;
  }
}

interface RequestOptions {
  timeoutMs?: number;
}

async function request<T>(path: string, init: RequestInit = {}, opts: RequestOptions = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");

  const controller = new AbortController();
  const timeoutMs = opts.timeoutMs ?? env.apiTimeoutMs;
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers, signal: controller.signal });
  } catch (err) {
    clearTimeout(timer);
    if (controller.signal.aborted) {
      throw new ApiError(0, null, "timeout", null, `The server took longer than ${Math.round(timeoutMs / 1000)} s to respond. Please try again.`);
    }
    throw new ApiError(0, String(err), "network_error", null,
      "Can't reach the CellLoop server. Check your connection, or that the API is running (./start.sh).");
  }
  clearTimeout(timer);

  const requestId = res.headers.get("X-Request-ID");
  if (res.status === 401 && token) {
    setToken(null);
    window.dispatchEvent(new Event("cellloop:unauthorized"));
  }
  if (!res.ok) {
    let body: { detail?: unknown; code?: string; message?: string; request_id?: string } = {};
    try {
      body = await res.json();
    } catch {
      /* non-JSON error page (e.g. a proxy's 502) */
    }
    const message = res.status === 422 && typeof body.message === "string" ? body.message : undefined;
    // A proxy error with no JSON body usually means the API process itself is down.
    if ((res.status === 502 || res.status === 504) && body.detail === undefined) {
      throw new ApiError(0, null, "api_unreachable", requestId,
        "The CellLoop API isn't responding. If you're running locally, start it with ./start.sh.");
    }
    throw new ApiError(res.status, body.detail ?? res.statusText, body.code ?? "error", body.request_id ?? requestId, message);
  }
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError(res.status, null, "bad_response", requestId, "The server sent a response we couldn't read. Please try again.");
  }
}

const json = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const api = {
  config: () => request<AppConfig>("/api/config"),
  devUsers: () => request<User[]>("/api/auth/dev-users"),
  devLogin: (email: string) => request<{ token: string; user: User }>("/api/auth/dev-login", json({ email })),
  me: () => request<User>("/api/auth/me"),

  documents: () => request<DocumentInfo[]>("/api/documents"),
  document: (id: string) => request<DocumentInfo>(`/api/documents/${id}`),
  upload: (form: FormData) => request<DocumentInfo>("/api/documents", { method: "POST", body: form }, { timeoutMs: SLOW_MS }),
  reextract: (id: string) => request<DocumentInfo>(`/api/documents/${id}/reextract`, { method: "POST" }),
  async documentBlobUrl(id: string): Promise<string> {
    const res = await fetch(`${BASE}/api/documents/${id}/file`, {
      headers: { Authorization: `Bearer ${getToken() ?? ""}` },
    });
    if (!res.ok) {
      let body: { detail?: unknown; code?: string; request_id?: string } = {};
      try {
        body = await res.json();
      } catch {
        /* not JSON */
      }
      throw new ApiError(res.status, body.detail ?? res.statusText, body.code, body.request_id ?? res.headers.get("X-Request-ID"));
    }
    return URL.createObjectURL(await res.blob());
  },

  experiments: (params: Record<string, string | number | undefined> = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && qs.set(k, String(v)));
    return request<{ total: number; items: Experiment[] }>(`/api/experiments?${qs}`);
  },
  experiment: (id: string) => request<ExperimentDetail>(`/api/experiments/${id}`),
  updateDraft: (id: string, values: Record<string, FieldValue>) =>
    request<ExperimentDetail>(`/api/experiments/${id}`, { method: "PATCH", body: JSON.stringify({ values }) }),
  approve: (id: string, values: Record<string, FieldValue>, comment: string, acknowledge_warnings = false) =>
    request<ExperimentDetail>(`/api/experiments/${id}/approve`, json({ values, comment, acknowledge_warnings }), { timeoutMs: SLOW_MS }),
  reject: (id: string, reason: string) => request<ExperimentDetail>(`/api/experiments/${id}/reject`, json({ reason })),

  recommend: (body: { n: number; target_temp_c?: number; target_asr?: number; filters?: Record<string, string> }) =>
    request<RecommendationResult>("/api/recommendations", json(body), { timeoutMs: SLOW_MS }),
  ask: (question: string) => request<QAResult>("/api/qa", json({ question }), { timeoutMs: SLOW_MS }),
  dashboard: () => request<Dashboard>("/api/dashboard"),
  audit: (params: { entity_id?: string; action?: string } = {}) => {
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]);
    return request<AuditEntry[]>(`/api/audit?${qs}`);
  },
};
