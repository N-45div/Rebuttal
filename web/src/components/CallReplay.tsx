"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

// Shapes written by rebuttal/replay.py into public/calls/<name>.json.
type Entry = { name: string; title: string };
type Turn = { offset_seconds: number; speaker: string; text: string };
type CallEvent = { message: string | null; type: string | null; offset: number | null };
type Check = { name: string; passed: boolean; detail: string; quote: string | null; offset: number | null };
type Outcome = { verdict: string; status: string | null; recovered: string | null; file: string | null; approved: boolean | null; report: string; run_id: string };
type Replay = {
  title: string;
  source: string;
  dispute: { id: string; reason: string | null };
  call: {
    id: string; status: string; confidence: number | null; duration_seconds: number | null;
    started_at: string | null; completed_at: string | null; to: string; script: string; idempotency_key: string;
  };
  events: CallEvent[];
  turns: Turn[];
  reported: Record<string, unknown>;
  accepted: Record<string, unknown>;
  usable: boolean;
  denied: boolean;
  checks: Check[];
  decision: string;
  outcome: Outcome | null;
};

const MEANINGFUL = /ring|answer|connect|complet|end|fail|busy|voicemail|hang|started/i;
const CLOSING = /complet|end|fail|busy|voicemail|hang/i;
const RULE = "A yes needs the customer's words; a no only needs to be possible.";
const CHECK_GAP = 1.1; // call-seconds between checks ticking in

const LABELS: Record<string, string> = {
  call_completed: "The call completed",
  confidence: "CALL-E is confident it finished the task",
  disclosure_spoken: "The caller said it was automated",
  no_payment_data_requested: "No payment details were asked for",
  customer_willing: "The customer agreed to talk",
  received_grounded: "“Received” is in the customer’s own words",
  recognises_charge_grounded: "“Recognises the charge” is in the customer’s own words",
};
const TONE: Record<string, string> = { "used as evidence": "won", "not used": "hold", "stops the filing": "blocked" };

const label = (n: string) => LABELS[n] || n.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
const shown = (v: unknown) => (v === undefined || v === null || v === "" ? "—" : String(v));

function mmss(s: number) {
  const v = Math.max(0, Math.floor(Number(s) || 0));
  return `${String(Math.floor(v / 60)).padStart(2, "0")}:${String(v % 60).padStart(2, "0")}`;
}
function signed(o: number | null) {
  return o === null || o === undefined ? "—" : `${o < 0 ? "−" : "+"}${Math.abs(o).toFixed(1)}s`;
}
function duration(d: number | null) {
  if (d === null || d === undefined) return "not recorded";
  return d >= 60 ? `${Math.floor(d / 60)} min ${Math.round(d % 60)} s` : `${Math.round(d)} s`;
}

// One clock in call-seconds: the transcript plays to the last turn + 2s, then the cross-examination reveals.
function timeline(d: Replay) {
  const last = d.turns.reduce((m, x) => Math.max(m, Number(x.offset_seconds) || 0), 0);
  const end = last + 2;
  const first = end + 0.7;
  const checks = d.checks.map((_, i) => first + i * CHECK_GAP);
  const table = first + d.checks.length * CHECK_GAP + 0.2;
  const decision = table + 1.4;
  const outcome = d.outcome ? decision + 1.8 : null;
  const done = (outcome ?? decision) + 2.4;
  return { end, checks, table, decision, outcome, done };
}

function why(d: Replay) {
  const failed = d.checks.filter((c) => !c.passed);
  if (d.decision === "used as evidence") {
    return failed.length
      ? "The call can go to the bank as a customer-communication document, carrying only the answers the customer actually gave."
      : "Every check passed, so the call can go to the bank as a customer-communication document.";
  }
  if (d.decision === "stops the filing") return "CALL-E reported a no, so Rebuttal files nothing for this dispute.";
  return failed.length
    ? `Not filed, because ${failed.map((c) => c.detail).join("; ")}.`
    : "Not filed: no answer was both reported by CALL-E and said by the customer.";
}

export default function CallReplay() {
  const [calls, setCalls] = useState<Entry[]>([]);
  const [name, setName] = useState("");
  const [data, setData] = useState<Replay | null>(null);
  const [error, setError] = useState("");
  const [speed, setSpeed] = useState(1);
  const [t, setT] = useState<number | null>(null); // null = at rest, everything shown
  const [played, setPlayed] = useState(false);
  const [reduced, setReduced] = useState(false);

  const rootRef = useRef<HTMLDivElement>(null);
  const raf = useRef<number | null>(null);
  const start = useRef(0);
  const now = useRef(0);
  const speedRef = useRef(1);
  const follow = useRef(true);
  const autoplay = useRef(false);

  const tl = useMemo(() => (data ? timeline(data) : null), [data]);

  const halt = useCallback(() => {
    if (raf.current !== null) cancelAnimationFrame(raf.current);
    raf.current = null;
    setT(null);
  }, []);

  const play = useCallback(() => {
    if (!tl) return;
    if (raf.current !== null) cancelAnimationFrame(raf.current);
    follow.current = true;
    start.current = performance.now();
    now.current = 0;
    setPlayed(false);
    setT(0);
    const tick = (ms: number) => {
      const v = Math.max(0, ((ms - start.current) / 1000) * speedRef.current);
      now.current = v;
      if (v >= tl.done) {
        raf.current = null;
        setT(null);
        setPlayed(true);
        return;
      }
      setT(v);
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
  }, [tl]);

  const changeSpeed = (s: number) => {
    start.current = performance.now() - (now.current * 1000) / s; // keep the clock where it is
    speedRef.current = s;
    setSpeed(s);
  };

  const choose = (n: string) => {
    if (n === name) return;
    autoplay.current = false;
    setName(n);
    const q = new URLSearchParams(window.location.search);
    q.set("c", n);
    q.delete("autoplay");
    window.history.replaceState(null, "", `${window.location.pathname}?${q.toString()}`);
  };

  useEffect(() => {
    const m = window.matchMedia("(prefers-reduced-motion: reduce)");
    const on = () => setReduced(m.matches);
    on();
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);

  useEffect(() => { if (reduced) halt(); }, [reduced, halt]);
  useEffect(() => () => { if (raf.current !== null) cancelAnimationFrame(raf.current); }, []);

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const s = q.get("speed") === "2" ? 2 : 1;
    speedRef.current = s;
    setSpeed(s);
    autoplay.current = q.get("autoplay") === "1";
    let live = true;
    fetch("/calls/index.json", { cache: "no-store" })
      .then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then((idx: { calls?: Entry[] }) => {
        if (!live) return;
        const list = idx.calls || [];
        setCalls(list);
        const want = q.get("c");
        setName(list.find((c) => c.name === want)?.name ?? list[0]?.name ?? "");
        if (!list.length) setError("No calls are listed in /calls/index.json yet.");
      })
      .catch(() => { if (live) setError("Could not load /calls/index.json."); });
    return () => { live = false; };
  }, []);

  useEffect(() => {
    if (!name) return;
    let live = true;
    halt();
    setPlayed(false);
    fetch(`/calls/${encodeURIComponent(name)}.json`, { cache: "no-store" })
      .then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then((d: Replay) => { if (live) { setData(d); setError(""); } })
      .catch(() => { if (live) setError(`Could not load /calls/${name}.json.`); });
    return () => { live = false; };
  }, [name, halt]);

  useEffect(() => {
    if (!data || reduced || !autoplay.current) return;
    const id = window.setTimeout(() => { autoplay.current = false; play(); }, 800);
    return () => window.clearTimeout(id);
  }, [data, reduced, play]);

  const playing = t !== null;

  // A reader who scrolls during playback takes the camera back.
  useEffect(() => {
    if (!playing) return;
    const off = () => { follow.current = false; };
    window.addEventListener("wheel", off, { passive: true });
    window.addEventListener("touchmove", off, { passive: true });
    window.addEventListener("keydown", off);
    return () => {
      window.removeEventListener("wheel", off);
      window.removeEventListener("touchmove", off);
      window.removeEventListener("keydown", off);
    };
  }, [playing]);

  const at = (x: number | null | undefined) => t === null || (x !== null && x !== undefined && t >= x);

  const events = useMemo(() => (data?.events || []).filter((e) => MEANINGFUL.test(e.message || "")), [data]);
  const cites = useMemo(() => {
    const m = new Map<number, number[]>();
    data?.checks.forEach((c, i) => {
      if (!c.quote) return;
      const ti = data.turns.findIndex((x) => x.text === c.quote && (c.offset === null || c.offset === undefined || x.offset_seconds === c.offset));
      if (ti >= 0) m.set(ti, [...(m.get(ti) || []), i]);
    });
    return m;
  }, [data]);

  const eventAt = (e: CallEvent) => (tl && CLOSING.test(e.message || "") ? tl.end : 0);
  const nTurns = data ? data.turns.filter((x) => at(x.offset_seconds)).length : 0;
  const nEvents = events.filter((e) => at(eventAt(e))).length;
  const nChecks = tl ? tl.checks.filter((x) => at(x)).length : 0;
  const showTable = !!tl && at(tl.table);
  const showDecision = !!tl && at(tl.decision);
  const showOutcome = !!tl && !!data?.outcome && at(tl.outcome);
  const revealKey = playing ? `${nTurns}.${nEvents}.${nChecks}.${showTable}.${showDecision}.${showOutcome}` : "";

  // Keep the newest line in frame while it plays (the page is filmed at 1920x1080).
  useEffect(() => {
    if (!revealKey || !follow.current || !rootRef.current) return;
    let bottom = 0;
    rootRef.current.querySelectorAll<HTMLElement>("[data-reveal]").forEach((el) => {
      bottom = Math.max(bottom, el.getBoundingClientRect().bottom);
    });
    const over = bottom - (window.innerHeight - 28);
    if (over > 1) window.scrollBy({ top: over, behavior: "smooth" });
  }, [revealKey]);

  if (!data || !tl) return <p className="src">{error || "Loading the call…"}</p>;

  const anim = playing ? " cr-anim" : "";
  const clock = t === null ? (played ? tl.end : 0) : Math.min(t, tl.end);
  const pct = t === null ? (played ? 100 : 0) : Math.min(100, (t / tl.end) * 100);
  const status = t === null
    ? played ? "Replayed. Everything is shown again." : "The whole call is shown. Play replays it from the first word."
    : t < tl.end ? "Call in progress" : t < tl.decision ? "Cross-examining CALL-E’s result" : "Decided";

  const reported = data.reported || {};
  const accepted = data.accepted || {};
  const fields = Array.from(new Set([...Object.keys(reported), ...Object.keys(accepted)]));
  const dropped = (f: string) => f in reported && f in accepted && shown(reported[f]) !== shown(accepted[f]);
  const o = data.outcome;
  const tone = TONE[data.decision] || "hold";

  return (
    <div className="cr" ref={rootRef}>
      {calls.length > 1 ? (
        <div className="cr-pick" role="group" aria-label="Calls">
          {calls.map((c) => (
            <button key={c.name} type="button" className="cr-tab" aria-pressed={c.name === name} onClick={() => choose(c.name)}>
              <span>{c.title}</span>
              <span className="mono">{c.name}</span>
            </button>
          ))}
        </div>
      ) : null}
      {error ? <p className="src">{error}</p> : null}

      <div className="panel cr-head">
        <div>
          <div className="eyebrow">{data.source}</div>
          <h3 className="cr-name">{data.title}</h3>
        </div>
        <dl className="cr-facts">
          <div><dt>dispute</dt><dd className="mono">{shown(data.dispute?.id)}</dd></div>
          <div><dt>reason</dt><dd>{data.dispute?.reason || "not recorded"}</dd></div>
          <div><dt>number called</dt>{data.call.to ? <dd className="mono">{data.call.to}</dd> : <dd className="cr-muted">none on record</dd>}</div>
          <div><dt>call id</dt><dd className="mono">{data.call.id}</dd></div>
          <div><dt>status · duration</dt><dd>{data.call.status} · {duration(data.call.duration_seconds)}</dd></div>
          <div><dt>CALL-E completion confidence</dt><dd className="mono">{data.call.confidence === null ? "not reported" : data.call.confidence.toFixed(2)}</dd></div>
          <div><dt>script version</dt><dd className="mono">{data.call.script}</dd></div>
          {data.call.started_at ? <div><dt>placed</dt><dd className="mono">{data.call.started_at.replace("T", " ").replace(/Z$/, " UTC")}</dd></div> : null}
          <div className="wide"><dt>idempotency key</dt><dd className="mono">{data.call.idempotency_key}</dd></div>
        </dl>
      </div>

      <div className="cr-stage">
        <div className="cr-controls">
          {reduced ? (
            <p className="cr-still">Replay is off because your system asks for reduced motion. The whole call is shown.</p>
          ) : (
            <>
              <button type="button" className="primary cr-play" onClick={playing ? halt : play}>{playing ? "Stop" : played ? "Play again" : "Play the call"}</button>
              <div className="cr-speed" role="group" aria-label="Playback speed">
                {[1, 2].map((s) => (
                  <button key={s} type="button" aria-pressed={speed === s} onClick={() => changeSpeed(s)}>{s}x</button>
                ))}
              </div>
            </>
          )}
          <span className="cr-clock mono">{mmss(clock)} / {mmss(tl.end)}</span>
          <span className="src" aria-live="polite">{status}</span>
        </div>
        <div className="cr-progress" aria-hidden="true"><i style={{ width: `${pct}%` }} /></div>

        <div className="cr-grid">
          <div className="panel">
            <h3>transcript · {data.turns.length} turns</h3>
            {data.turns.length ? (
              <ol className="cr-turns">
                {data.turns.map((x, i) => {
                  if (!at(x.offset_seconds)) return null;
                  const who = x.speaker === "customer" ? "customer" : "caller";
                  const quoted = (cites.get(i) || []).filter((ci) => at(tl.checks[ci]));
                  return (
                    <li key={i} data-reveal className={`cr-turn ${who}${quoted.length ? " cited" : ""}${anim}`}>
                      <div className="cr-bubble">
                        <div className="cr-who">
                          <span>{who === "customer" ? "Customer" : "Caller · CALL-E"}</span>
                          {quoted.length ? <span className="cr-cite">quoted in check {quoted.map((c) => c + 1).join(", ")}</span> : null}
                          <span>{mmss(x.offset_seconds)}</span>
                        </div>
                        <p>{x.text}</p>
                      </div>
                    </li>
                  );
                })}
              </ol>
            ) : <p className="cr-muted">CALL-E returned no transcript for this call.</p>}
          </div>
          <div className="panel">
            <h3>CALL-E events</h3>
            {events.length ? (
              <ol className="cr-events">
                {events.map((e, i) => at(eventAt(e)) ? (
                  <li key={i} data-reveal className={anim.trim() || undefined}>
                    <span className="mono">{signed(e.offset)}</span>
                    <span>{e.message}</span>
                  </li>
                ) : null)}
              </ol>
            ) : <p className="cr-muted">No ringing, answer or completion events were recorded.</p>}
            <p className="cr-note">{data.call.started_at ? "Seconds from when CALL-E started the call." : "Seconds into the agent run, as traced."} Setup and speech events are left out.</p>
          </div>
        </div>
      </div>

      <div className="cr-xexam">
        <div className="cr-xhead">
          <h3 className="cr-h">Cross-examination</h3>
          <span className="src">{data.checks.length} checks against the transcript, then what Rebuttal accepted, then the decision.</span>
        </div>
        <div className="cr-x">
          <div>
            {playing && nChecks === 0 ? <p className="cr-pending">Waiting for the call to end.</p> : null}
            <ol className="cr-checks">
              {data.checks.map((c, i) => at(tl.checks[i]) ? (
                <li key={`${c.name}-${i}`} data-reveal className={`cr-check ${c.passed ? "pass" : "fail"}${anim}`}>
                  <span className="cr-mark mono">{c.passed ? "PASS" : "FAIL"}</span>
                  <div className="cr-body">
                    <div className="cr-label"><span className="cr-num mono">{i + 1}</span>{label(c.name)}</div>
                    <div className="cr-detail">{c.detail} <span className="cr-key mono">{c.name}</span></div>
                    {c.quote ? (
                      <div className="cr-quote mono">&ldquo;{c.quote}&rdquo;{c.offset !== null && c.offset !== undefined ? <span> · at {mmss(c.offset)}</span> : null}</div>
                    ) : null}
                  </div>
                </li>
              ) : null)}
            </ol>
          </div>

          <div className="cr-side">
            {showTable ? (
              <div data-reveal className={`cr-accept${anim}`}>
                <div className="tablewrap">
                  <table>
                    <thead><tr><th>field</th><th>CALL-E reported</th><th>accepted</th></tr></thead>
                    <tbody>
                      {fields.map((f) => (
                        <tr key={f}>
                          <td className="mono">{f.replace(/_/g, " ")}</td>
                          <td className="mono">{shown(reported[f])}</td>
                          <td className={`mono${dropped(f) ? " cr-dropped" : ""}`}>{shown(accepted[f])}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {fields.some(dropped) ? <p className="cr-note">An answer is accepted only when the call is usable and the customer said it.</p> : null}
              </div>
            ) : null}

            {showDecision ? (
              <div data-reveal className={`cr-decision ${tone}${anim}`}>
                <span className="eyebrow">decision</span>
                <div className="cr-dword">{data.decision}</div>
                <p className="cr-why">{why(data)}</p>
                <p className="cr-rule">{RULE}</p>
              </div>
            ) : null}

            {o && showOutcome ? (
              <div data-reveal className={`panel cr-outcome${anim}`}>
                <h3>outcome · run {o.run_id}</h3>
                <dl className="cr-facts">
                  <div><dt>verdict</dt><dd className={o.verdict === "SUBMIT" ? "cr-good" : o.verdict === "CONCEDE" ? "cr-bad" : "cr-warn"}>{o.verdict || "—"}</dd></div>
                  <div><dt>dispute status</dt><dd className={o.status === "won" ? "cr-good" : o.status === "lost" ? "cr-bad" : undefined}>{shown(o.status)}</dd></div>
                  <div><dt>recovered</dt><dd>{shown(o.recovered)}</dd></div>
                  <div><dt>human approval in Slack</dt><dd>{o.approved === true ? "approved" : o.approved === false ? "not approved" : "not recorded"}</dd></div>
                  <div className="wide"><dt>call document filed with Stripe</dt>{o.file ? <dd className="mono">{o.file}</dd> : <dd className="cr-muted">not filed</dd>}</div>
                </dl>
                <div className="report">{o.report}</div>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
