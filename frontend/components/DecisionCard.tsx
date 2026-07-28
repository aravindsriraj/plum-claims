import type { ClaimDecision } from "@/lib/types";

const inr = (n: number) =>
  `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

// The decision card: decision, amounts, confidence, financial breakdown,
// line-item adjudication, fraud signals, degradation warnings.
export default function DecisionCard({ decision }: { decision: ClaimDecision }) {
  return (
    <div className="card">
      <h2>Decision</h2>

      {decision.degraded && (
        <div className="degraded-banner">
          Processing was degraded — one or more components failed and were
          skipped. Confidence was reduced accordingly.
        </div>
      )}

      <span className={`decision-chip decision-${decision.decision}`}>
        {decision.decision.replace("_", " ")}
      </span>

      <div className="kv">
        <div>
          <div className="k">Claimed</div>
          <div className="v">{inr(decision.claimed_amount)}</div>
        </div>
        <div>
          <div className="k">Approved</div>
          <div className="v">{inr(decision.approved_amount)}</div>
        </div>
        <div>
          <div className="k">Confidence</div>
          <div className="v">{decision.confidence_score.toFixed(2)}</div>
        </div>
      </div>

      {decision.reasons.length > 0 && (
        <div style={{ marginBottom: 14 }}>
          {decision.reasons.map((r, i) => (
            <div key={i} style={{ fontSize: 14, marginBottom: 3 }}>{r}</div>
          ))}
        </div>
      )}

      {decision.adjustments.length > 0 && (
        <>
          <h2 style={{ marginTop: 16 }}>Financial breakdown</h2>
          <table>
            <thead>
              <tr><th>Step</th><th className="num">Before</th><th className="num">After</th><th>Note</th></tr>
            </thead>
            <tbody>
              {decision.adjustments.map((a, i) => (
                <tr key={i}>
                  <td>{a.kind.replaceAll("_", " ")}</td>
                  <td className="num">{inr(a.amount_before)}</td>
                  <td className="num">{inr(a.amount_after)}</td>
                  <td>{a.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {decision.line_item_breakdown.length > 0 && (
        <>
          <h2 style={{ marginTop: 16 }}>Line items</h2>
          <table>
            <thead>
              <tr><th>Description</th><th className="num">Amount</th><th>Status</th><th>Reason</th></tr>
            </thead>
            <tbody>
              {decision.line_item_breakdown.map((li, i) => (
                <tr key={i}>
                  <td>{li.description}</td>
                  <td className="num">{inr(li.amount)}</td>
                  <td className={li.status === "APPROVED" ? "status-PASS" : "status-FAIL"}>
                    {li.status}
                  </td>
                  <td>{li.rejection_reason ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {decision.fraud_signals.length > 0 && (
        <>
          <h2 style={{ marginTop: 16 }}>Fraud / risk signals</h2>
          <ul className="notes" style={{ listStyle: "none", padding: 12 }}>
            {decision.fraud_signals.map((s, i) => (
              <li key={i}><strong>{s.code}</strong> — {s.description}</li>
            ))}
          </ul>
        </>
      )}

      {decision.notes.length > 0 && (
        <>
          <h2 style={{ marginTop: 16 }}>Notes</h2>
          <ul className="notes">
            {decision.notes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        </>
      )}
    </div>
  );
}
