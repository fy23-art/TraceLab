import { useCallback, useState } from "react";
import { api, apiKey, ApiError } from "./api";
import { Overview, WINDOWS } from "./Overview";
import { RequestDrawer } from "./RequestDrawer";
import { RequestsView } from "./RequestsView";
import { SubmitDialog } from "./SubmitDialog";
import { usePolling } from "./usePolling";

type Tab = "overview" | "requests" | "dead";

export default function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [selected, setSelected] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [windowKey, setWindowKey] = useState("6h");
  const [host, setHost] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [keyDraft, setKeyDraft] = useState("");

  const win = WINDOWS.find((w) => w.key === windowKey) ?? WINDOWS[2];
  const { data: stats, error, reload } = usePolling(() => api.stats(win.hours, win.bucket), [win.hours, win.bucket, refresh]);

  const changed = useCallback(() => {
    setRefresh((n) => n + 1);
    void reload();
  }, [reload]);

  if (error instanceof ApiError && error.status === 401) {
    return (
      <main className="gate">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            apiKey.set(keyDraft.trim());
            changed();
          }}
        >
          <h1>TraceLab</h1>
          <p className="muted">This instance requires an API key.</p>
          <label>
            API key
            <input type="password" value={keyDraft} onChange={(e) => setKeyDraft(e.target.value)} autoFocus autoComplete="off" />
          </label>
          {apiKey.get() && <p className="bad" role="alert">That key was rejected.</p>}
          <button type="submit" disabled={!keyDraft.trim()}>Continue</button>
        </form>
      </main>
    );
  }

  const open = (t: Tab) => () => setTab(t);
  const nav = (t: Tab, label: string, badge?: number) => (
    <button className={`nav ${tab === t ? "active" : ""}`} aria-current={tab === t ? "page" : undefined} onClick={open(t)}>
      {label}
      {badge ? <span className="badge">{badge}</span> : null}
    </button>
  );

  return (
    <div className="shell">
      <aside className="rail">
        <div className="brand">
          <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden="true">
            <path d="M5 9h9M10 16h14M7 23h7" stroke="#3cc8a8" strokeWidth="3" strokeLinecap="round" />
          </svg>
          TraceLab
        </div>
        <nav aria-label="Sections">
          {nav("overview", "Overview")}
          {nav("requests", "Requests")}
          {nav("dead", "Dead letters", stats?.queue.dead)}
        </nav>
        <button className="primary-action" onClick={() => setSubmitting(true)}>Send a request</button>
        <div className="rail-foot">
          {error ? <span className="bad">API unreachable</span> : <span className="muted">Live, updates every 5 s</span>}
          {apiKey.get() && (
            <button className="link" onClick={() => { apiKey.set(""); changed(); }}>Forget API key</button>
          )}
        </div>
      </aside>

      <main className="main">
        {tab === "overview" && (
          <Overview
            stats={stats}
            windowKey={windowKey}
            onWindow={setWindowKey}
            onHost={(h) => { setHost(h); setTab("requests"); }}
            onSubmit={() => setSubmitting(true)}
          />
        )}
        {tab === "requests" && (
          <RequestsView
            key="requests"
            title="Requests"
            emptyText="No requests match. Send one to see its attempts and timing here."
            selectedId={selected}
            onSelect={setSelected}
            refreshToken={refresh}
            hostFilter={host}
            onHostFilter={setHost}
          />
        )}
        {tab === "dead" && (
          <RequestsView
            key="dead"
            fixedState="dead"
            title="Dead letters"
            hint="Requests that kept failing and ran out of attempts. Open one to see why, then retry or replay it."
            emptyText="Nothing here. Every request either succeeded or is still being retried."
            selectedId={selected}
            onSelect={setSelected}
            refreshToken={refresh}
            hostFilter={host}
            onHostFilter={setHost}
          />
        )}
      </main>

      {selected && <RequestDrawer id={selected} onClose={() => setSelected(null)} onOpen={setSelected} onChanged={changed} />}
      {submitting && (
        <SubmitDialog
          onClose={() => setSubmitting(false)}
          onSubmitted={(id) => {
            setSubmitting(false);
            setTab("requests");
            setSelected(id);
            changed();
          }}
        />
      )}
    </div>
  );
}
