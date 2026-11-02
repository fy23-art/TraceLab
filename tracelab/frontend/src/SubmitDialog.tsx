import { useEffect, useRef, useState } from "react";
import { api } from "./api";

interface Props {
  onClose: () => void;
  onSubmitted: (id: string) => void;
}

const PRESETS = [
  { label: "Succeeds", url: "https://httpbin.org/status/200", extra: {} },
  { label: "Server error, retried", url: "https://httpbin.org/status/503", extra: { max_attempts: 3, backoff_base_s: 0.5 } },
  { label: "Times out", url: "https://httpbin.org/delay/5", extra: { timeout_s: 1.5, max_attempts: 2, backoff_base_s: 0.5 } },
  { label: "Not found, not retried", url: "https://httpbin.org/status/404", extra: {} },
];

function parseHeaders(text: string): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const idx = line.indexOf(":");
    if (idx > 0) headers[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
  }
  return headers;
}

export function SubmitDialog({ onClose, onSubmitted }: Props) {
  const [method, setMethod] = useState("GET");
  const [url, setUrl] = useState("");
  const [headers, setHeaders] = useState("");
  const [body, setBody] = useState("");
  const [timeout, setTimeoutS] = useState(10);
  const [maxAttempts, setMaxAttempts] = useState(4);
  const [backoffBase, setBackoffBase] = useState(1);
  const [backoffMax, setBackoffMax] = useState(60);
  const [idem, setIdem] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const urlRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    urlRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function applyPreset(p: (typeof PRESETS)[number]) {
    setMethod("GET");
    setUrl(p.url);
    setTimeoutS(p.extra.timeout_s ?? 10);
    setMaxAttempts(p.extra.max_attempts ?? 4);
    setBackoffBase(p.extra.backoff_base_s ?? 1);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await api.submit(
        {
          method,
          url: url.trim(),
          headers: parseHeaders(headers),
          body: method === "GET" || method === "HEAD" || !body ? null : body,
          timeout_s: timeout,
          max_attempts: maxAttempts,
          backoff_base_s: backoffBase,
          backoff_max_s: Math.max(backoffMax, backoffBase),
        },
        idem.trim() || undefined,
      );
      onSubmitted(created.id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const hasBody = !["GET", "HEAD"].includes(method);

  return (
    <div className="scrim center" onClick={onClose}>
      <form className="dialog" role="dialog" aria-modal="true" aria-label="Send a request" onSubmit={submit} onClick={(e) => e.stopPropagation()}>
        <h2>Send a request</h2>
        <div className="chips" role="group" aria-label="Example requests">
          {PRESETS.map((p) => (
            <button type="button" key={p.label} className="chip" onClick={() => applyPreset(p)}>
              {p.label}
            </button>
          ))}
        </div>

        <div className="row">
          <label className="method-field">
            Method
            <select value={method} onChange={(e) => setMethod(e.target.value)}>
              {["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"].map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </label>
          <label className="grow">
            URL
            <input ref={urlRef} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://api.example.com/orders" required />
          </label>
        </div>

        <label>
          Headers (one per line, Name: value)
          <textarea rows={3} value={headers} onChange={(e) => setHeaders(e.target.value)} placeholder={"Authorization: Bearer …\nAccept: application/json"} spellCheck={false} />
        </label>

        {hasBody && (
          <label>
            Body
            <textarea rows={4} value={body} onChange={(e) => setBody(e.target.value)} spellCheck={false} />
          </label>
        )}

        <fieldset>
          <legend>Retry policy</legend>
          <div className="row">
            <label>
              Timeout (s)
              <input type="number" min={0.1} max={30} step={0.1} value={timeout} onChange={(e) => setTimeoutS(+e.target.value)} />
            </label>
            <label>
              Max attempts
              <input type="number" min={1} max={10} value={maxAttempts} onChange={(e) => setMaxAttempts(+e.target.value)} />
            </label>
            <label>
              First backoff (s)
              <input type="number" min={0.05} max={60} step={0.05} value={backoffBase} onChange={(e) => setBackoffBase(+e.target.value)} />
            </label>
            <label>
              Backoff cap (s)
              <input type="number" min={0.1} max={3600} value={backoffMax} onChange={(e) => setBackoffMax(+e.target.value)} />
            </label>
          </div>
        </fieldset>

        <label>
          Idempotency key (optional)
          <input value={idem} onChange={(e) => setIdem(e.target.value)} placeholder="Submitting the same key twice returns the original request" />
        </label>

        {error && <p className="bad" role="alert">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" disabled={busy || !url.trim()}>
            {busy ? "Sending…" : "Send request"}
          </button>
        </div>
      </form>
    </div>
  );
}
