import RunViewer from "@/components/RunViewer";

export default function RunsPage() {
  return (
    <section>
      <h2>Runs, as they happened</h2>
      <p className="sub">
        One agent execution is one trace. Every external write shows OK, BLOCKED or ERROR. The first live run of the night reported
        success, and the post-run detector said the Gmail sub-agent never ran. That trace is the first one in the list.
      </p>
      <RunViewer />
    </section>
  );
}
