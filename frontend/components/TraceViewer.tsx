import type { ClaimResponse } from "@/lib/types";

// Trace viewer: the full audit trail — every check, extraction, decision and
// error, in order, with PASS/FAIL/WARN/SKIP status. This is what lets ops
// reconstruct exactly why any claim got its decision.
export default function TraceViewer({
  trace,
  explanation,
  processing,
}: {
  trace: ClaimResponse["trace"];
  explanation: string;
  processing: ClaimResponse["processing"];
}) {
  return (
    <div className="card">
      <h2>
        Processing trace{" "}
        <span style={{ fontSize: 13, color: "var(--muted)", fontWeight: 400 }}>
          {trace.length} events · {processing.duration_ms} ms ·{" "}
          {processing.llm_calls} LLM call(s)
          {processing.degraded ? " · DEGRADED" : ""}
        </span>
      </h2>
      <table>
        <thead>
          <tr><th>#</th><th>Component</th><th>Status</th><th>What happened</th></tr>
        </thead>
        <tbody>
          {trace.map((e) => (
            <tr className="trace-row" key={e.sequence}>
              <td>{e.sequence}</td>
              <td><span className="component-tag">{e.component}</span></td>
              <td className={`status-${e.status}`}>{e.status}</td>
              <td>{e.summary}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <details>
        <summary>Full explanation (ops narrative)</summary>
        <div className="explanation" style={{ marginTop: 10 }}>{explanation}</div>
      </details>
    </div>
  );
}
