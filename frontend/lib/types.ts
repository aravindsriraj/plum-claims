// Shared types mirroring the backend contracts (see docs/CONTRACTS.md).
// The backend is the source of truth; these stay structurally compatible.

export type Decision = "APPROVED" | "PARTIAL" | "REJECTED" | "MANUAL_REVIEW";
export type ClaimStatus = "DECIDED" | "DOCUMENT_REJECTED";

export interface DocumentIssue {
  code: string;
  file_id: string | null;
  message: string;
  found: string | null;
  expected: string | null;
}

export interface LineItem {
  description: string;
  amount: number;
  status: string;
  rejection_reason: string | null;
  approved_amount: number | null;
}

export interface Adjustment {
  kind: string;
  amount_before: number;
  amount_after: number;
  note: string;
}

export interface TraceEvent {
  sequence: number;
  component: string;
  event_type: string;
  status: "PASS" | "FAIL" | "WARN" | "SKIPPED";
  summary: string;
  detail: Record<string, unknown>;
}

export interface ComponentFailure {
  component: string;
  error: string;
  fallback_used: string;
  confidence_penalty: number;
}

export interface ClaimDecision {
  decision: Decision;
  claimed_amount: number;
  approved_amount: number;
  confidence_score: number;
  reasons: string[];
  rejection_reasons: string[];
  line_item_breakdown: LineItem[];
  adjustments: Adjustment[];
  fraud_signals: { code: string; description: string; severity: number }[];
  degraded: boolean;
  component_failures: ComponentFailure[];
  notes: string[];
}

export interface ClaimResponse {
  claim_id: string;
  status: ClaimStatus;
  member_message: string;
  document_issues: DocumentIssue[];
  decision: ClaimDecision | null;
  explanation: string;
  trace: TraceEvent[];
  processing: { duration_ms: number; degraded: boolean; llm_calls: number };
}

export interface ClaimDocumentPayload {
  file_id: string;
  file_name?: string;
  file_content_base64?: string;
  mime_type?: string;
}

export interface ClaimPayload {
  member_id: string;
  policy_id: string;
  claim_category: string;
  treatment_date: string;
  claimed_amount: number;
  hospital_name?: string;
  ytd_claims_amount?: number;
  pre_auth_reference?: string;
  simulate_component_failure?: boolean;
  documents: ClaimDocumentPayload[];
}
