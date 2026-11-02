import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { clock, fmtMs, fmtPct, kindLabel } from "./format";
import type { Stats } from "./types";

export const WINDOWS = [
  { key: "1h", label: "Last hour", hours: 1, bucket: 5 },
  { key: "6h", label: "Last 6 hours", hours: 6, bucket: 15 },
  { key: "24h", label: "Last 24 hours", hours: 24, bucket: 60 },
  { key: "7d", label: "Last 7 days", hours: 168, bucket: 360 },
] as const;

const C = { ok: "#3cc8a8", bad: "#f0675a", p50: "#6aa7f8", p95: "#f2b84b", grid: "#263543", axis: "#8497a8" };

const tooltipStyle = {
  contentStyle: { background: "#17222d", border: "1px solid #33475a", borderRadius: 6, fontSize: 12 },
  labelStyle: { color: "#dce6ee" },
  itemStyle: { color: "#dce6ee" },
  cursor: { fill: "rgba(132,151,168,.12)" },
};

interface Props {
  stats: Stats | null;
  windowKey: string;
  onWindow: (key: string) => void;
  onHost: (host: string) => void;
  onSubmit: () => void;
}

export function Overview({ stats, windowKey, onWindow, onHost, onSubmit }: Props) {
  if (!stats) return <p className="muted pad">Loading…</p>;

  const { attempts, latency_ms: lat, queue } = stats;
  const longWindow = stats.window_hours > 24;
  const data = stats.timeseries.map((p) => ({
    ...p,
    label: longWindow ? new Date(p.ts).toLocaleDateString([], { month: "short", day: "numeric", hour: "2-digit" }) : clock(p.ts),
  }));
  const maxKind = Math.max(1, ...stats.failure_kinds.map((k) => k.count));
  // A line needs two points to draw; show dots while traffic is sparse so the chart is never blank.
  const sparse = data.filter((p) => p.p50 != null).length < 3;

  return (
    <section className="view">
      <header className="view-head">
        <h1>Overview</h1>
        <label>
          <span className="sr-only">Time window</span>
          <select value={windowKey} onChange={(e) => onWindow(e.target.value)}>
            {WINDOWS.map((w) => (
              <option key={w.key} value={w.key}>{w.label}</option>
            ))}
          </select>
        </label>
      </header>

      {attempts.total === 0 && queue.ready + queue.scheduled + queue.running === 0 ? (
        <div className="empty-hero">
          <h2>No traffic in this window</h2>
          <p>Send a request and TraceLab will record every attempt, retry and failure here.</p>
          <button onClick={onSubmit}>Send a request</button>
        </div>
      ) : (
        <>
          <dl className="vitals">
            <div>
              <dt>Success rate</dt>
              <dd className={attempts.error_rate != null && attempts.error_rate > 0.1 ? "bad" : "good"}>{fmtPct(attempts.success_rate)}</dd>
              <dd className="sub">{attempts.success} of {attempts.total} attempts</dd>
            </div>
            <div>
              <dt>Latency p50 / p95</dt>
              <dd>{fmtMs(lat.p50)} <span className="muted">/</span> {fmtMs(lat.p95)}</dd>
              <dd className="sub">p99 {fmtMs(lat.p99)}</dd>
            </div>
            <div>
              <dt>Queue</dt>
              <dd>{queue.ready + queue.scheduled + queue.running} open</dd>
              <dd className="sub">{queue.ready} ready, {queue.scheduled} waiting to retry, {queue.running} running</dd>
            </div>
            <div>
              <dt>Dead letters</dt>
              <dd className={queue.dead > 0 ? "bad" : ""}>{queue.dead}</dd>
              <dd className="sub">{queue.failed} failed without retry</dd>
            </div>
          </dl>

          <div className="charts">
            <figure>
              <figcaption>Attempts per interval</figcaption>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={data} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
                  <CartesianGrid stroke={C.grid} vertical={false} />
                  <XAxis dataKey="label" stroke={C.axis} tick={{ fontSize: 11 }} minTickGap={32} tickLine={false} />
                  <YAxis stroke={C.axis} tick={{ fontSize: 11 }} allowDecimals={false} tickLine={false} axisLine={false} />
                  <Tooltip {...tooltipStyle} />
                  <Bar dataKey="success" name="Succeeded" stackId="a" fill={C.ok} isAnimationActive={false} />
                  <Bar dataKey="failure" name="Failed" stackId="a" fill={C.bad} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </figure>
            <figure>
              <figcaption>Latency (ms)</figcaption>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={data} margin={{ top: 6, right: 8, left: -10, bottom: 0 }}>
                  <CartesianGrid stroke={C.grid} vertical={false} />
                  <XAxis dataKey="label" stroke={C.axis} tick={{ fontSize: 11 }} minTickGap={32} tickLine={false} />
                  <YAxis stroke={C.axis} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                  <Tooltip {...tooltipStyle} formatter={(v: number) => fmtMs(v)} />
                  <Line dataKey="p50" name="p50" stroke={C.p50} dot={sparse ? { r: 3 } : false} strokeWidth={2} connectNulls isAnimationActive={false} />
                  <Line dataKey="p95" name="p95" stroke={C.p95} dot={sparse ? { r: 3 } : false} strokeWidth={2} connectNulls isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </figure>
          </div>

          <div className="split">
            <section>
              <h2>Why attempts fail</h2>
              {stats.failure_kinds.length === 0 ? (
                <p className="muted">No failed attempts in this window.</p>
              ) : (
                <ul className="bars">
                  {stats.failure_kinds.map((k) => (
                    <li key={k.kind}>
                      <span>{kindLabel(k.kind)}</span>
                      <span className="bar-track"><span style={{ width: `${(k.count / maxKind) * 100}%` }} /></span>
                      <span className="num">{k.count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section>
              <h2>Hosts</h2>
              <table className="compact">
                <thead>
                  <tr><th>Host</th><th className="num">Attempts</th><th className="num">Errors</th><th className="num">p95</th></tr>
                </thead>
                <tbody>
                  {stats.top_hosts.map((h) => (
                    <tr key={h.host}>
                      <td><button className="link" onClick={() => onHost(h.host)}>{h.host}</button></td>
                      <td className="num">{h.attempts}</td>
                      <td className={`num ${h.error_rate > 0.1 ? "bad" : ""}`}>{fmtPct(h.error_rate)}</td>
                      <td className="num">{fmtMs(h.p95)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          </div>
        </>
      )}
    </section>
  );
}
