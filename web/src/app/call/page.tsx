import CallReplay from "@/components/CallReplay";

export default function CallPage() {
  return (
    <section>
      <h2>One call, placed by <span className="cr-nowrap">CALL-E,</span> <span className="cr-nowrap">cross-examined</span> before anything is filed.</h2>
      <p className="sub">
        When a disputing customer never answers the email, Rebuttal places one scripted call, then checks every answer CALL-E reports
        against the customer&apos;s own words before any of it reaches the bank.
      </p>
      <CallReplay />
    </section>
  );
}
