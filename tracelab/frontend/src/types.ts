export type State = "queued" | "retrying" | "running" | "succeeded" | "failed" | "dead";

export interface RequestSummary {
  id: string;
  method: string;
  url: string;
  host: string;
  status: string;
  state: State;
  attempt_count: number;
  max_attempts: number;
  next_run_at: string;
  last_status_code: number | null;
  last_error_kind: string | null;
  last_latency_ms: number | null;
  replay_of: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface Attempt {
  number: number;
  started_at: string;
  finished_at: string;
  latency_ms: number;
  outcome: "success" | "failure";
  status_code: number | null;
  error_kind: string | null;
  error_message: string | null;
  retryable: boolean;
  will_retry: boolean;
  retry_in_s: number | null;
  response_headers: Record<string, string>;
  response_body: string | null;
  response_bytes: number | null;
}

export interface Diagnosis {
  kind: string;
  retryable: boolean;
  explanation: string;
  suggestion: string;
}

export interface RequestDetail extends RequestSummary {
  headers: Record<string, string>;
  body: string | null;
  timeout_s: number;
  backoff_base_s: number;
  backoff_max_s: number;
  idempotency_key: string | null;
  attempts: Attempt[];
  diagnosis: Diagnosis | null;
}

export interface Page {
  items: RequestSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface Latency {
  avg: number | null;
  p50: number | null;
  p95: number | null;
  p99: number | null;
}

export interface Stats {
  window_hours: number;
  bucket_minutes: number;
  attempts: { total: number; success: number; failure: number; success_rate: number | null; error_rate: number | null };
  latency_ms: Latency;
  queue: { ready: number; scheduled: number; running: number; dead: number; failed: number; succeeded: number };
  failure_kinds: { kind: string; count: number }[];
  top_hosts: { host: string; attempts: number; error_rate: number; p95: number | null }[];
  timeseries: { ts: string; success: number; failure: number; p50: number | null; p95: number | null }[];
}

export interface SubmitPayload {
  method: string;
  url: string;
  headers: Record<string, string>;
  body?: string | null;
  timeout_s: number;
  max_attempts: number;
  backoff_base_s: number;
  backoff_max_s: number;
}
