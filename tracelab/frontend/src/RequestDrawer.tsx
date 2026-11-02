import { useEffect, useState } from "react";
import { api } from "./api";
import { ago, clock, fmtMs, fmtSeconds, inFuture, kindLabel } from "./format";
import { ResultCell, StatePill } from "./StatePill";
import { TraceTimeline } from "./TraceTimeline";
import type { Attempt, RequestDetail } from "./types";
import { usePolling } from "./usePolling";

interface Props {
  id: string;
  onClose: () => void;
  onOpen: (id: string) => void;
  onChanged: () => void;
}

export function RequestDrawer({ id, onClose, onOpen, onChanged }: Props) {
  const { data: req, error } = usePolling(() => api.get(id), [id], 2500);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function run(action: () => Promise<{ id: string }>, openResult: boolean) {
    setBusy(true);
    setActionError(null);
    try {
      const result = await action();
      onChanged();
      if (openResult) onOpen(result.id);
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="scrim" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="Request details" onClick={(e) => e.stopPropagation()}>
        <header className="drawer-head">
          <button className="ghost close" onClick={onClose} aria-label="Close details">
            Close
          </button>
          {req ? (
            <>
              <div className="drawer-title">
                <span className="method">{req.method}</span>
                <span className="url" title={req.url}>{req.url}</span>
              </div>
              <div className="drawer-sub">
                <StatePill state={req.state} />
                <code className="muted">{req.id}</code>
                {req.replay_of && (
                  <button className="link" onClick={() => onOpen(req.replay_of!)}>
                    Replay of {req.replay_of.slice(0, 8)}
                  </button>
                )}
              </div>
            </>
          ) : (
            <p className="muted">{error ? error.message : "Loading…"}</p>
          )}
        </header>

        {req && (
          <div className="drawer-body">
            <div className="actions">
              <button disabled={busy} onClick={() => run(() => api.replay(req.id), true)}>
                Replay request
              </button>
              {req.state === "dead" && (
                <button className="secondary" disabled={busy} onClick={() => run(() => api.requeue(req.id, 3), false)}>
                  Retry 3 more times
                </button>
              )}
              {actionError && <span className="bad" role="alert">{actionError}</span>}
            </div>

            <Diagnosis req={req} />

            <section>
              <h3>Attempts</h3>
              {req.state === "retrying" && (
                <p className="muted">
                  Next attempt {inFuture(req.next_run_at)} (attempt {req.attempt_count + 1} of {req.max_attempts}).
                </p>
              )}
              <TraceTimeline attempts={req.attempts} />
              <div className="attempts">
                {req.attempts.map((a) => (
                  <AttemptDetails key={a.number} attempt={a} />
                ))}
              </div>
            </section>

            <section>
              <h3>Request</h3>
              <dl className="kv">
                <dt>Created</dt>
                <dd>{ago(req.created_at)} ({clock(req.created_at, true)})</dd>
                <dt>Timeout</dt>
                <dd>{fmtSeconds(req.timeout_s)}</dd>
                <dt>Retry policy</dt>
                <dd>
                  up to {req.max_attempts} attempts, backoff {fmtSeconds(req.backoff_base_s)} doubling to{" "}
                  {fmtSeconds(req.backoff_max_s)}
                </dd>
                {req.idempotency_key && (
                  <>
                    <dt>Idempotency key</dt>
                    <dd><code>{req.idempotency_key}</code></dd>
                  </>
                )}
              </dl>
              {Object.keys(req.headers).length > 0 && (
                <>
                  <h4>Headers</h4>
                  <pre className="code">{Object.entries(req.headers).map(([k, v]) => `${k}: ${v}`).join("\n")}</pre>
                </>
              )}
              {req.body && (
                <>
                  <h4>Body</h4>
                  <pre className="code">{req.body}</pre>
                </>
              )}
              {Object.keys(req.headers).length > 0 && (
                <p className="muted small">Credentials in headers are masked here and never returned by the API.</p>
              )}
            </section>
          </div>
        )}
      </aside>
    </div>
  );
}

function Diagnosis({ req }: { req: RequestDetail }) {
  if (!req.diagnosis || req.state === "succeeded") return null;
  const d = req.diagnosis;
  const last = req.attempts[req.attempts.length - 1];
  return (
    <section className="diagnosis" aria-label="Why it failed">
      <h3>
        Why it failed: {kindLabel(d.kind)}
        {last?.status_code ? <span className="muted"> (HTTP {last.status_code})</span> : null}
      </h3>
      <p>{d.explanation}</p>
      <p>
        <strong>What to do:</strong> {d.suggestion}
      </p>
      <p className="muted small">
        {d.retryable
          ? req.state === "dead"
            ? `This kind of failure is retried. It still failed after ${req.attempt_count} attempts, so it was moved to the dead-letter queue.`
            : "This kind of failure is retried automatically with backoff."
          : "This kind of failure is not retried because sending the same request again would not help."}
      </p>
    </section>
  );
}

function AttemptDetails({ attempt: a }: { attempt: Attempt }) {
  return (
    <details className="attempt">
      <summary>
        <span>#{a.number}</span>
        <ResultCell code={a.status_code} kind={a.error_kind} />
        <span className="muted">{fmtMs(a.latency_ms)}</span>
        {a.will_retry && a.retry_in_s != null && <span className="muted">retry after {fmtSeconds(a.retry_in_s)}</span>}
      </summary>
      <dl className="kv">
        <dt>Started</dt>
        <dd>{clock(a.started_at, true)}</dd>
        {a.error_message && (
          <>
            <dt>Error</dt>
            <dd>{a.error_message}</dd>
          </>
        )}
        {a.response_bytes != null && (
          <>
            <dt>Response size</dt>
            <dd>{a.response_bytes} bytes</dd>
          </>
        )}
      </dl>
      {Object.keys(a.response_headers).length > 0 && (
        <pre className="code">{Object.entries(a.response_headers).map(([k, v]) => `${k}: ${v}`).join("\n")}</pre>
      )}
      {a.response_body && <pre className="code">{a.response_body}</pre>}
    </details>
  );
}
