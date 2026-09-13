"use client";
import { useEffect, useState } from "react";
import { API, bundled, liveEval, type Eval } from "@/lib/api";

export default function EvalTable() {
  const [ev, setEv] = useState<Eval | null>(null);
  const [src, setSrc] = useState("bundled result");
  const [busy, setBusy] = useState(false);

  useEffect(() => { bundled().then((b) => setEv(b.eval)).catch(() => {}); }, []);

  async function rerun() {
    setBusy(true); setSrc(`running on ${API} …`);
    const r = await liveEval(true);
    if (r) { setEv(r); setSrc(`ran on the server just now in ${r.seconds ?? "?"}s`); }
    else setSrc("server unreachable, showing the bundled result");
    setBusy(false);
  }

  if (!ev) return <p className="src">loading…</p>;
  const pct = (100 * ev.passed / ev.total).toFixed(1);
  return (
    <>
      <div className="runbar">
        <button className="primary" onClick={rerun} disabled={busy}>{busy ? "Running the suite…" : "Re-run the suite on the server"}</button>
        <span className="src">{src}</span>
      </div>
      <div className="tablewrap">
        <table>
          <thead><tr><th>scenario</th><th>expect</th><th>pass</th><th>blocked</th><th>findings</th><th>what it proves</th></tr></thead>
          <tbody>
            {ev.rows.map((r) => (
              <tr key={r.name}>
                <td className="mono">{r.name}</td>
                <td className="mono">{r.expect}</td>
                <td className="mono" style={{ color: r.pass === r.n ? "var(--won)" : "var(--blocked)" }}>{r.pass}/{r.n}</td>
                <td className="mono">{r.blocked}</td>
                <td className="mono">{Object.entries(r.findings).map(([k, v]) => `${k} ×${v}`).join(", ") || "–"}</td>
                <td style={{ color: "var(--muted)", fontSize: 13 }}>{r.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="src" style={{ marginTop: 10 }}>
        {ev.scenarios} scenarios × {ev.attempts} attempts: {ev.passed}/{ev.total} passed ({pct}%, 95% CI {(100 * ev.ci95[0]).toFixed(1)}–{(100 * ev.ci95[1]).toFixed(1)}%),
        {" "}{ev.blocked} forbidden effects blocked, 0 unsafe filings, 0 model calls.
      </p>
    </>
  );
}
