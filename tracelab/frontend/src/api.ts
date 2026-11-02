import type { Page, RequestDetail, RequestSummary, Stats, SubmitPayload } from "./types";

const KEY_STORAGE = "tracelab.apiKey";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const apiKey = {
  get: () => {
    try {
      return localStorage.getItem(KEY_STORAGE) ?? "";
    } catch {
      return "";
    }
  },
  set: (value: string) => {
    try {
      value ? localStorage.setItem(KEY_STORAGE, value) : localStorage.removeItem(KEY_STORAGE);
    } catch {
      /* storage unavailable: key lasts for this page load only */
    }
  },
};

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  const key = apiKey.get();
  if (key) headers.set("X-API-Key", key);

  const res = await fetch(`/api${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export interface ListParams {
  state?: string;
  q?: string;
  host?: string;
  limit: number;
  offset: number;
}

export const api = {
  stats: (windowHours: number, bucketMinutes: number) =>
    call<Stats>(`/stats?window_hours=${windowHours}&bucket_minutes=${bucketMinutes}`),
  list: (p: ListParams) => {
    const qs = new URLSearchParams({ limit: String(p.limit), offset: String(p.offset) });
    if (p.state) qs.set("status", p.state);
    if (p.q) qs.set("q", p.q);
    if (p.host) qs.set("host", p.host);
    return call<Page>(`/requests?${qs}`);
  },
  get: (id: string) => call<RequestDetail>(`/requests/${id}`),
  submit: (payload: SubmitPayload, idempotencyKey?: string) =>
    call<RequestSummary>("/requests", {
      method: "POST",
      body: JSON.stringify(payload),
      headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
    }),
  replay: (id: string) => call<RequestSummary>(`/requests/${id}/replay`, { method: "POST" }),
  requeue: (id: string, extraAttempts = 3) =>
    call<RequestSummary>(`/dlq/${id}/requeue`, {
      method: "POST",
      body: JSON.stringify({ extra_attempts: extraAttempts }),
    }),
};
