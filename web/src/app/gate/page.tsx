const RULES: [string, string][] = [
  ["SUBMIT_WITHOUT_HUMAN_APPROVAL", "no Stripe submission without the Slack click"],
  ["DUPLICATE_FILING_SAME_DISPUTE", "a dispute is filed once, ever"],
  ["UNCITED_CLAIMS_IN_PACKET", "the writer produced a claim with no source record"],
  ["EDITED_CE3_PREFILLED_FIELD", "Stripe pre-fills IP and product description; editing them breaks eligibility"],
  ["SECOND_NOTICE_TO_CUSTOMER", "one notice per dispute, text or email, never both"],
  ["SECOND_CALL_TO_CUSTOMER", "one call per dispute, ever"],
  ["REFUND_OUTSIDE_SCOPE", "the agent may never refund"],
];

const POLICY: [string, string, string][] = [
  ["product_not_received / physical", "order record · tracking delivered · (signature image or address match)", "already refunded"],
  ["product_not_received / digital", "order record · access log", "already refunded"],
  ["fraudulent / physical", "order record · CE3.0 prior transactions · CE3.0 elements match · (delivered or address match)", "already refunded · no CE3.0 path"],
  ["duplicate", "order record · distinct orders", "already refunded"],
  ["product_unacceptable", "order record · customer communication · (refund policy shown or delivered)", "already refunded"],
  ["credit_not_processed", "order record · refund policy shown · customer communication", "already refunded"],
  ["subscription_canceled / digital", "order record · access log · refund policy shown", "already refunded"],
  ["unrecognized", "order record · (delivered or customer communication)", "already refunded"],
  ["anything else", "—", "HOLD to a human"],
];

export default function GatePage() {
  return (
    <>
      <section>
        <h2>Seven forbidden effects</h2>
        <p className="sub">
          Every side effect on an external app passes through one gate. The rules are declared before the run, enforced in code, and counted.
          A blocked attempt is traced as attempted → BLOCKED → reason, never silently dropped. The Stripe disputes API submits by default; the
          agent always stages first and reads the validator before it ever sends submit=true.
        </p>
        <div className="rules">
          {RULES.map(([c, d]) => <div className="rule" key={c}><code>{c}</code><span>{d}</span></div>)}
        </div>
      </section>
      <section>
        <h2>The policy table</h2>
        <p className="sub">Reason code × evidence → verdict. Deterministic, unit-tested, and tightened only in one direction by the harness: a lost filing adds the evidence that was absent to the requirement, and nothing is ever removed without a human edit.</p>
        <div className="tablewrap">
          <table>
            <thead><tr><th>reason</th><th>required to SUBMIT</th><th>CONCEDE if</th></tr></thead>
            <tbody>
              {POLICY.map(([r, m, c]) => <tr key={r}><td className="mono">{r}</td><td style={{ fontSize: 14 }}>{m}</td><td style={{ fontSize: 14, color: "var(--muted)" }}>{c}</td></tr>)}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
