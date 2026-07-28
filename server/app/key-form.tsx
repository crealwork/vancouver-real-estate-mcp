"use client";

import { useState } from "react";

type Result =
  | { kind: "idle" }
  | { kind: "sending" }
  | { kind: "sent"; endpoint: string }
  | { kind: "key"; key: string; endpoint: string }
  | { kind: "error"; message: string };

export function KeyForm() {
  const [email, setEmail] = useState("");
  const [result, setResult] = useState<Result>({ kind: "idle" });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setResult({ kind: "sending" });
    try {
      const res = await fetch("/api/request-key", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const body = await res.json();
      if (!res.ok) {
        setResult({ kind: "error", message: body.error ?? "something went wrong" });
      } else if (body.key) {
        setResult({ kind: "key", key: body.key, endpoint: body.endpoint });
      } else {
        setResult({ kind: "sent", endpoint: body.endpoint });
      }
    } catch {
      setResult({ kind: "error", message: "network error — try again" });
    }
  }

  return (
    <div className="keyform">
      <style>{css}</style>
      <form onSubmit={submit}>
        <input
          type="email"
          required
          placeholder="you@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={result.kind === "sending"}
        />
        <button type="submit" disabled={result.kind === "sending"}>
          {result.kind === "sending" ? "Sending…" : "Send me a key"}
        </button>
      </form>

      {result.kind === "sent" && (
        <p className="ok">Key sent. Check your inbox for setup instructions.</p>
      )}
      {result.kind === "key" && (
        <div className="ok">
          <p>Your key:</p>
          <pre>{result.key}</pre>
          <p>Add it to Claude Code:</p>
          <pre>{`claude mcp add --transport http vanre ${result.endpoint} \\
  --header "Authorization: Bearer ${result.key}"`}</pre>
        </div>
      )}
      {result.kind === "error" && <p className="err">{result.message}</p>}
    </div>
  );
}

const css = `
  .keyform form { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
  .keyform input {
    flex: 1 1 260px; padding: 11px 14px; font-size: 15px;
    border: 1px solid #d3d7de; border-radius: 8px; background: transparent; color: inherit;
  }
  .keyform input:focus { outline: 2px solid #16181d; outline-offset: 1px; }
  .keyform button {
    padding: 11px 20px; font-size: 15px; font-weight: 550; cursor: pointer;
    border: 0; border-radius: 8px; background: #16181d; color: #fff;
  }
  .keyform button:disabled { opacity: .55; cursor: default; }
  .keyform pre {
    background: #f3f4f6; padding: 12px 14px; border-radius: 8px; overflow-x: auto;
    font: 12.5px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap;
    word-break: break-all;
  }
  .keyform .ok { font-size: 14px; }
  .keyform .err { font-size: 14px; color: #b42318; }
  @media (prefers-color-scheme: dark) {
    .keyform input { border-color: #2a2e36; }
    .keyform input:focus { outline-color: #e8eaed; }
    .keyform button { background: #e8eaed; color: #0d0f13; }
    .keyform pre { background: #1c1f25; }
    .keyform .err { color: #f97066; }
  }
`;
