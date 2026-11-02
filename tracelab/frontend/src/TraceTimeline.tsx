import { fmtMs, fmtSeconds } from "./format";
import type { Attempt } from "./types";

/**
 * A waterfall of every attempt on one time axis. Bars are the requests themselves; the dashed
 * segments between them are the backoff waits, so retry behaviour is visible at a glance.
 */
export function TraceTimeline({ attempts }: { attempts: Attempt[] }) {
  if (attempts.length === 0) return <p className="muted">No attempts yet. A worker will pick this up shortly.</p>;

  const t = (iso: string) => new Date(iso).getTime();
  const t0 = t(attempts[0].started_at);
  const span = Math.max(1, t(attempts[attempts.length - 1].finished_at) - t0);
  const pos = (ms: number) => `${Math.min(100, (ms / span) * 100)}%`;

  return (
    <ol className="trace" aria-label="Attempt timeline">
      {attempts.map((a, i) => {
        const start = t(a.started_at) - t0;
        const prevEnd = i > 0 ? t(attempts[i - 1].finished_at) - t0 : null;
        const widthPct = Math.max(1.2, (a.latency_ms / span) * 100);
        const ok = a.outcome === "success";
        return (
          <li key={a.number} className="trace-row">
            <span className="trace-label">#{a.number}</span>
            <div className="trace-lane">
              {prevEnd != null && start > prevEnd && (
                <span
                  className="trace-wait"
                  style={{ left: pos(prevEnd), width: `${((start - prevEnd) / span) * 100}%` }}
                  title={`Waited ${fmtSeconds((start - prevEnd) / 1000)} before this attempt`}
                />
              )}
              <span
                className={`trace-bar ${ok ? "ok" : "fail"}`}
                style={{ left: pos(start), width: `${Math.min(widthPct, 100 - (start / span) * 100)}%` }}
              />
            </div>
            <span className={`trace-result ${ok ? "good" : "bad"}`}>
              {a.status_code ?? "error"} · {fmtMs(a.latency_ms)}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
