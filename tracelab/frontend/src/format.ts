export function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return "–";
  if (ms < 1) return "<1 ms";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;
}

export function fmtPct(value: number | null | undefined): string {
  if (value == null) return "–";
  const pct = value * 100;
  return `${pct >= 10 || pct === 0 ? pct.toFixed(0) : pct.toFixed(1)}%`;
}

export function fmtSeconds(s: number): string {
  return s < 1 ? `${Math.round(s * 1000)} ms` : s < 60 ? `${s.toFixed(1)} s` : `${(s / 60).toFixed(1)} min`;
}

export function ago(iso: string, now = Date.now()): string {
  const diff = Math.round((now - new Date(iso).getTime()) / 1000);
  if (diff < 5) return "just now";
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function inFuture(iso: string, now = Date.now()): string {
  const diff = Math.round((new Date(iso).getTime() - now) / 1000);
  return diff <= 0 ? "now" : `in ${fmtSeconds(diff)}`;
}

export function clock(iso: string, withSeconds = false): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    ...(withSeconds ? { second: "2-digit" } : {}),
  });
}

/** "dns_failure" -> "DNS failure" style labels for failure kinds. */
export function kindLabel(kind: string | null | undefined): string {
  if (!kind) return "–";
  return kind.replace(/_/g, " ").replace(/^dns/, "DNS").replace(/^tls/, "TLS");
}
