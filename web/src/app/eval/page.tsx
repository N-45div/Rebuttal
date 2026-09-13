import EvalTable from "@/components/EvalTable";

const MODES: [string, string][] = [
  ["Skipped Work", "a gather sub-agent never issued its query, returned nothing, raised nothing"],
  ["Out of Scope Work", "an effect outside the allowed list succeeded"],
  ["Instruction Violation", "a claim without a citation"],
  ["Hallucination", "a claim citing a record not in the bundle; a tracking number that appears in no source"],
  ["Communication Failure", "the Slack report omits the verdict or the money"],
];

export default function EvalPage() {
  return (
    <>
      <section>
        <h2>How we know it works</h2>
        <p className="sub">
          A filing agent&apos;s failures are silent. So the suite does not ask &quot;did it return 200&quot;; it asks whether the complete outcome
          matched and whether anything forbidden happened. Twenty-two seeded starting states for local twins of all six apps, three attempts each,
          reset between runs. Nine inject faults. No model, no network; the button below runs it on the Render backend in a few seconds.
        </p>
        <EvalTable />
      </section>
      <section>
        <h2>Silent-failure detector</h2>
        <p className="sub">Runs twice per execution: before filing on the packet, and after the report on the finished trace. It compares what happened with what was supposed to happen, and names the mode.</p>
        <div className="rules">
          {MODES.map(([m, d]) => <div className="rule" key={m}><code style={{ color: "var(--hold)" }}>{m}</code><span>{d}</span></div>)}
        </div>
      </section>
      <section>
        <h2>Ground truth we did not write</h2>
        <p className="sub">
          Stripe&apos;s CE 3.0 validator grades the evidence in test mode: eligibility moves from <span className="mono">requires_action</span> to
          <span className="mono"> qualified</span> only when the identifiers match. It rejected a packet on the night for a device fingerprint under 20
          characters, which the agent now treats as a HOLD with the error in the trace. The customer on the phone is the other counterparty: a real
          CALL-E call returned <span className="mono">received=yes, recognises_charge=yes, confidence 0.95</span>. The honest caveat: Stripe&apos;s
          won/lost in test mode is a marker, so the suite grades the twin&apos;s outcome and the validator grades eligibility.
        </p>
      </section>
    </>
  );
}
