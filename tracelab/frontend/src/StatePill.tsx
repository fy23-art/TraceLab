import { kindLabel } from "./format";
import type { State } from "./types";

const LABEL: Record<State, string> = {
  queued: "Queued",
  retrying: "Retrying",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
  dead: "Dead letter",
};

export function StatePill({ state }: { state: State }) {
  return (
    <span className={`pill pill-${state}`}>
      <i aria-hidden="true" />
      {LABEL[state]}
    </span>
  );
}

export function ResultCell({ code, kind }: { code: number | null; kind: string | null }) {
  if (code == null && !kind) return <span className="muted">–</span>;
  const bad = code != null ? code >= 400 : true;
  return (
    <span className={bad ? "bad" : "good"}>
      {code ?? ""} {kind && <span className="muted">{kindLabel(kind)}</span>}
    </span>
  );
}
