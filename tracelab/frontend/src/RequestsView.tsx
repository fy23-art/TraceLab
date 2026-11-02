import { useEffect, useState } from "react";
import { api } from "./api";
import { ago, fmtMs } from "./format";
import { ResultCell, StatePill } from "./StatePill";
import { usePolling } from "./usePolling";

const PAGE = 20;
const STATES = ["", "queued", "retrying", "running", "succeeded", "failed", "dead"] as const;
const STATE_LABEL: Record<string, string> = {
  "": "All states", queued: "Queued", retrying: "Retrying", running: "Running",
  succeeded: "Succeeded", failed: "Failed", dead: "Dead letter",
};

interface Props {
  /** Pin the list to one state (used by the dead-letter view). */
  fixedState?: string;
  title: string;
  hint?: string;
  emptyText: string;
  selectedId: string | null;
  onSelect: (id: string) => void;
  refreshToken: number;
  hostFilter: string;
  onHostFilter: (host: string) => void;
}

export function RequestsView({ fixedState, title, hint, emptyText, selectedId, onSelect, refreshToken, hostFilter, onHostFilter }: Props) {
  const [state, setState] = useState(fixedState ?? "");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => {
      setQ(search);
      setOffset(0);
    }, 250);
    return () => clearTimeout(t);
  }, [search]);

  const activeState = fixedState ?? state;
  const { data, error, loading } = usePolling(
    () => api.list({ state: activeState || undefined, q: q || undefined, host: hostFilter || undefined, limit: PAGE, offset }),
    [activeState, q, hostFilter, offset, refreshToken],
  );

  const total = data?.total ?? 0;
  const items = data?.items ?? [];

  return (
    <section className="view">
      <header className="view-head">
        <div>
          <h1>{title}</h1>
          {hint && <p className="muted">{hint}</p>}
        </div>
      </header>

      <div className="filters">
        {!fixedState && (
          <label>
            <span className="sr-only">State</span>
            <select value={state} onChange={(e) => { setState(e.target.value); setOffset(0); }}>
              {STATES.map((s) => (
                <option key={s} value={s}>{STATE_LABEL[s]}</option>
              ))}
            </select>
          </label>
        )}
        <label className="grow">
          <span className="sr-only">Search URLs</span>
          <input type="search" placeholder="Search by URL" value={search} onChange={(e) => setSearch(e.target.value)} />
        </label>
        {hostFilter && (
          <button className="chip active" onClick={() => onHostFilter("")} title="Clear host filter">
            host: {hostFilter} ×
          </button>
        )}
      </div>

      {error && <p className="bad" role="alert">{error.message}</p>}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Request</th>
              <th>State</th>
              <th className="num">Attempts</th>
              <th>Last result</th>
              <th className="num">Latency</th>
              <th className="num">Created</th>
            </tr>
          </thead>
          <tbody>
            {items.map((r) => (
              <tr
                key={r.id}
                className={r.id === selectedId ? "selected" : ""}
                tabIndex={0}
                onClick={() => onSelect(r.id)}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(r.id))}
              >
                <td className="req-cell">
                  <span className="method">{r.method}</span>
                  <span className="url" title={r.url}>{r.url}</span>
                  {r.replay_of && <span className="tag">replay</span>}
                </td>
                <td><StatePill state={r.state} /></td>
                <td className="num">{r.attempt_count}/{r.max_attempts}</td>
                <td><ResultCell code={r.last_status_code} kind={r.last_error_kind} /></td>
                <td className="num">{fmtMs(r.last_latency_ms)}</td>
                <td className="num muted">{ago(r.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && items.length === 0 && <p className="empty">{emptyText}</p>}
      </div>

      <footer className="pager">
        <span className="muted">
          {total === 0 ? "0 requests" : `${offset + 1}–${Math.min(offset + PAGE, total)} of ${total}`}
        </span>
        <div>
          <button className="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
          <button className="secondary" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Next</button>
        </div>
      </footer>
    </section>
  );
}
