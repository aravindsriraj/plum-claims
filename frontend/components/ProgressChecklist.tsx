import type { StageEvent, StageStatus } from "@/lib/types";

// The pipeline's stages in graph order — labels mirror the backend's STAGES.
// document_worker may run once per upload; the checklist shows it once.
const STAGE_ORDER: { id: string; label: string }[] = [
  { id: "document_worker", label: "Document perception" },
  { id: "verify_document_set", label: "Verifying document set" },
  { id: "clinical_tagging", label: "Clinical policy tagging" },
  { id: "cross_validate", label: "Consistency checks" },
  { id: "adjudicate", label: "Applying policy rules" },
  { id: "fraud_check", label: "Fraud screening" },
  { id: "synthesize_decision", label: "Finalizing decision" },
  { id: "human_review_gate", label: "Human review" },
];

export interface StageState {
  status: StageStatus;
  summary?: string;
}

/**
 * Live pipeline progress: checklist driven by real stage events streamed
 * from the backend — each done-stage shows the actual trace line produced.
 */
export default function ProgressChecklist({
  stages,
}: {
  stages: Record<string, StageState>;
}) {
  return (
    <div className="card progress-card">
      <h2>Processing your claim</h2>
      <ol className="stage-list">
        {STAGE_ORDER.map(({ id, label }) => {
          const state = stages[id] ?? { status: "pending" as StageStatus };
          return (
            <li key={id} className={`stage stage-${state.status}`}>
              <span className="stage-icon" aria-hidden>
                {state.status === "done" ? "✓" : state.status === "running" ? "◌" : "·"}
              </span>
              <div>
                <div className="stage-label">{label}</div>
                {state.summary && <div className="stage-summary">{state.summary}</div>}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function stagesFromEvent(
  prev: Record<string, StageState>,
  event: StageEvent
): Record<string, StageState> {
  return { ...prev, [event.stage]: { status: event.status, summary: event.summary } };
}
