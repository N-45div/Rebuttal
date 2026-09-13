import Link from "next/link";
import Stats from "@/components/Stats";

const APPS: [string, string][] = [
  ["Stripe", "dispute in · evidence out · CE3.0 validator"],
  ["Google Sheets", "order ledger · outcome ledger"],
  ["Gmail", "customer thread (evidence)"],
  ["CALL-E", "one confirmation call"],
  ["Photon", "one text to the customer"],
  ["Slack", "human approval gate"],
];

export default function Home() {
  return (
    <>
      <header className="hero">
        <div className="eyebrow">Multi-App AI Agent Hackathon · GPT-6 Astra</div>
        <h1>Stripe files what it has.<br />Rebuttal goes and <em>finds the rest.</em></h1>
        <p className="lede">
          A chargeback is a one-shot, irreversible filing against a deadline. Rebuttal assembles the evidence Stripe cannot see, across the
          order ledger, the email thread and a phone call to the customer, qualifies it under Visa Compelling Evidence 3.0, waits for a human
          click in Slack, and refuses to file when the packet would lose.
        </p>
        <div className="apps">
          {APPS.map(([n, r]) => (
            <span className="app" key={n}><i className="dot" /><b>{n}</b><span>{r}</span></span>
          ))}
        </div>
        <div className="ctas">
          <Link className="cta" href="/runs">See a real run</Link>
          <Link className="cta quiet" href="/eval">How we know it works</Link>
        </div>
      </header>

      <section>
        <Stats />
      </section>

      <section>
        <h2>Three verdicts, one of them is refusing</h2>
        <p className="sub">The model writes prose. Everything with a consequence is a table, a rule, a counterparty&apos;s answer, or a human&apos;s click.</p>
        <div className="verdicts">
          <div className="verdict submit"><h3>SUBMIT</h3><p>The reason-code checklist is complete and every claim cites a record. Staged first, then Stripe&apos;s own CE 3.0 validator is read, then filed, once.</p></div>
          <div className="verdict hold"><h3>HOLD</h3><p>Something is missing, the customer said no on the phone, or the human did not click. The missing items are named in Slack. Nothing is filed.</p></div>
          <div className="verdict concede"><h3>CONCEDE</h3><p>Filing would lose anyway: already refunded, or a fraud claim with no CE 3.0 path. Losing also costs the fee and the dispute ratio.</p></div>
        </div>
      </section>

      <section>
        <h2>Why Compelling Evidence 3.0 is the point</h2>
        <p className="sub">
          For a fraud dispute on Visa, the only way to win and remove the fraud record is CE 3.0: two prior undisputed transactions on the same card,
          120 to 365 days old, with two of four identifiers matching across all three, one of them IP or device. That evidence is scattered across the
          processor, the checkout and the shipping record by construction. Stripe&apos;s built-in Smart Disputes cannot assemble it. Rebuttal can, and Stripe
          grades the result: eligibility moves from <span className="mono">requires_action</span> to <span className="mono">qualified</span> only when the
          submitted identifiers actually match. A real rule engine as ground truth, not our own scorer marking its own homework.
        </p>
      </section>

      <section>
        <h2>The run</h2>
        <pre className="flow">{`Stripe dispute
  ├── gather · 3 sub-agents, concurrent      Stripe · Sheets · Gmail
  ├── CALL-E · if the thread is silent        one call: received? recognises charge?  → cited evidence
  ├── assess · deterministic                  delivered · signed · refunded · CE3.0 priors · identifiers match
  ├── decide · policy table                   SUBMIT / HOLD / CONCEDE
  ├── write · GPT-6 Astra                     cited claims; uncited ones dropped and counted
  ├── review · detector                       Instruction Violation · Hallucination
  ├── Slack · Approve & file / Hold           nothing is filed without the click
  ├── Stripe · stage (submit=false)           read Stripe's CE3.0 validator → submit only if qualified
  ├── Photon · one text to the customer       Gmail only if no phone or no thread
  ├── Sheets · outcome row                    amount · recovered · fee · CE3.0 · run id
  └── Slack · summary → detector post-run     Skipped Work · Out of Scope · Communication Failure`}</pre>
      </section>
    </>
  );
}
