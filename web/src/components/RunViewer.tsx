"use client";
import { useEffect, useMemo, useState } from "react";
import { API, bundled, liveRuns, type Span, type Trace } from "@/lib/api";

function pill(s: Span) {
  if (s.kind === "effect") {
    const cls = s.result === "OK" ? "ok" : s.result === "BLOCKED" ? "blocked" : "err";
    return <span className={`pill ${cls}`}>{s.result}{s.reason ? ` · ${s.reason}` : ""}</span>;
  }
  if (s.kind === "gather") return <span className={`pill ${s.result === "skipped" ? "err" : ""}`}>{s.result}{s.received ? ` · received=${s.received}` : ""}</span>;
  if (s.kind === "decision") return <span className="pill">{s.verdict || s.status || ""}</span>;
  if (s.kind === "review") { const f = (s.findings || []) as string[]; return <span className={`pill ${f.length ? "blocked" : "ok"}`}>{f.length ? f.join(", ") : "clean"}</span>; }
  if (s.kind === "interaction") return <span className="pill">{s.approved ? "approved" : "held"}</span>;
  if (s.kind === "generation") return <span className="pill">{s.claims} claims · {s.dropped_uncited} dropped</span>;
  return null;
}

function explain(mode: string, spans: Span[]) {
  if (mode === "Skipped Work") {
    const g = spans.find((s) => s.kind === "gather" && s.result === "skipped");
    return g ? `${g.name} never ran its query (${g.why || "no input"}) and raised no error. The run still reported success.` : "a sub-agent never ran its query.";
  }
  if (mode === "Hallucination") return "a claim cited a record that is not in the evidence bundle, or a tracking number that appears in no source.";
  if (mode === "Instruction Violation") return "a claim without a citation. Dropped before filing; the gate blocked the submission.";
  if (mode === "Communication Failure") return "the report omitted the verdict or the amount.";
  if (mode === "Out of Scope Work") return "an effect outside the allowed list succeeded.";
  return "";
}

const label = (k: string) => k.replace(/[-_]/g, " ");

export default function RunViewer() {
  const [runs, setRuns] = useState<Record<string, Trace>>({});
  const [src, setSrc] = useState("loading…");
  const [sel, setSel] = useState<string>("");

  useEffect(() => {
    (async () => {
      const b = await bundled();
      let all: Record<string, Trace> = { ...b.examples };
      setRuns(all); setSrc("bundled traces");
      const first = Object.keys(all).sort((a) => (a.includes("skipped") ? -1 : 1))[0];
      setSel(first);
      const live = await liveRuns();
      if (live && Object.keys(live).length) { all = { ...all, ...live }; setRuns(all); setSrc(`live from ${API}`); }
      else setSrc("bundled traces · api warming up");
    })();
  }, []);

  const keys = useMemo(() => Object.keys(runs).sort((a, b) => (a.includes("skipped") ? -1 : 0) - (b.includes("skipped") ? -1 : 0)), [runs]);
  const t = runs[sel];
  const spans = t?.spans || [];
  const rep = spans.find((s) => s.kind === "report");
  const dec = spans.find((s) => s.name === "policy.decide");
  const finds = Array.from(new Set(spans.filter((s) => s.kind === "review").flatMap((s) => (s.findings || []) as string[])));

  return (
    <>
      <div className="runbar">
        <label htmlFor="runsel" className="src">run</label>
        <select id="runsel" value={sel} onChange={(e) => setSel(e.target.value)}>
          {keys.map((k) => <option key={k} value={k}>{label(k)}</option>)}
        </select>
        <span className="src">{src}</span>
      </div>
      <div className="viewer">
        <div className="panel">
          <h3>trace · {t?.dispute_id || ""}</h3>
          <div className="trace">
            {spans.map((s, i) => (
              <div className="span" key={i}>
                <span className="t">{(s.t || 0).toFixed(1)}s</span>
                <span className="k">{s.kind}</span>
                <span>{s.name}{s.target ? <span className="k"> {s.target}</span> : null}</span>
                {pill(s)}
              </div>
            ))}
          </div>
        </div>
        <div style={{ display: "grid", gap: 16, minWidth: 0 }}>
          <div className="panel"><h3>verdict &amp; report</h3><div className="report">{rep ? rep.text : "(no report)"}</div></div>
          <div className="panel">
            <h3>silent-failure detector</h3>
            {finds.length ? finds.map((m) => <div className="finding" key={m}><b>{m}</b><br />{explain(m, spans)}</div>)
              : <div className="clean">No findings. The run did what it reported.</div>}
          </div>
          <div className="panel">
            <h3>decision</h3>
            <div style={{ fontSize: 14 }}>
              <b>{(dec?.verdict || "").toUpperCase()}</b> · {dec?.reason || ""}
              {dec?.have ? <div className="src" style={{ marginTop: 6 }}>evidence: {(dec.have as string[]).join(", ")}</div> : null}
              {dec?.missing?.length ? <div className="src">missing: {(dec.missing as string[]).join(", ")}</div> : null}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
