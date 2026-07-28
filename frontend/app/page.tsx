"use client";

import { useState } from "react";
import { fileToBase64, submitClaimStream } from "@/lib/api";
import type { ClaimPayload, ClaimResponse } from "@/lib/types";
import DecisionCard from "@/components/DecisionCard";
import DocumentIssues from "@/components/DocumentIssues";
import ProgressChecklist, { stagesFromEvent, type StageState } from "@/components/ProgressChecklist";
import TraceViewer from "@/components/TraceViewer";

const CATEGORIES = [
  "CONSULTATION",
  "DIAGNOSTIC",
  "PHARMACY",
  "DENTAL",
  "VISION",
  "ALTERNATIVE_MEDICINE",
];

// Member roster from policy_terms.json — surfaced so the demo is self-service.
const MEMBERS = [
  ["EMP001", "Rajesh Kumar"], ["EMP002", "Priya Singh"], ["EMP003", "Amit Verma"],
  ["EMP004", "Sneha Reddy"], ["EMP005", "Vikram Joshi"], ["EMP006", "Kavita Nair"],
  ["EMP007", "Suresh Patil"], ["EMP008", "Ravi Menon"], ["EMP009", "Anita Desai"],
  ["EMP010", "Deepak Shah"],
];

export default function Home() {
  const [memberId, setMemberId] = useState("EMP001");
  const [category, setCategory] = useState("CONSULTATION");
  const [treatmentDate, setTreatmentDate] = useState("2024-11-01");
  const [amount, setAmount] = useState("1500");
  const [hospital, setHospital] = useState("");
  const [preAuth, setPreAuth] = useState("");
  const [simulateFailure, setSimulateFailure] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [stages, setStages] = useState<Record<string, StageState>>({});
  const [response, setResponse] = useState<ClaimResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResponse(null);
    setStages({});
    try {
      const documents = await Promise.all(
        files.map(async (f, i) => ({
          file_id: `UP${String(i + 1).padStart(3, "0")}`,
          file_name: f.name,
          file_content_base64: await fileToBase64(f),
          mime_type: f.type || "image/jpeg",
        }))
      );
      const payload: ClaimPayload = {
        member_id: memberId,
        policy_id: "PLUM_GHI_2024",
        claim_category: category,
        treatment_date: treatmentDate,
        claimed_amount: parseFloat(amount),
        hospital_name: hospital || undefined,
        pre_auth_reference: preAuth || undefined,
        simulate_component_failure: simulateFailure,
        documents,
      };
      setResponse(
        await submitClaimStream(payload, (event) =>
          setStages((prev) => stagesFromEvent(prev, event))
        )
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submission failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="container">
      <h1>Plum — Claims Processing</h1>
      <p className="subtitle">
        Submit a claim with medical documents. The pipeline verifies documents,
        extracts data with a vision model, and adjudicates deterministically
        against policy PLUM_GHI_2024.
      </p>

      <form className="card" onSubmit={onSubmit}>
        <h2>New Claim</h2>
        <div className="grid2">
          <div className="field">
            <label>Member</label>
            <select value={memberId} onChange={(e) => setMemberId(e.target.value)}>
              {MEMBERS.map(([id, name]) => (
                <option key={id} value={id}>{id} — {name}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Claim category</label>
            <select value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
            </select>
          </div>
          <div className="field">
            <label>Treatment date</label>
            <input type="date" value={treatmentDate}
              onChange={(e) => setTreatmentDate(e.target.value)} required />
          </div>
          <div className="field">
            <label>Claimed amount (₹)</label>
            <input type="number" min="1" step="0.01" value={amount}
              onChange={(e) => setAmount(e.target.value)} required />
          </div>
          <div className="field">
            <label>Hospital / provider (optional)</label>
            <input value={hospital} onChange={(e) => setHospital(e.target.value)}
              placeholder="e.g. Apollo Hospitals" />
          </div>
          <div className="field">
            <label>Pre-auth reference (optional)</label>
            <input value={preAuth} onChange={(e) => setPreAuth(e.target.value)}
              placeholder="If pre-authorization was obtained" />
          </div>
        </div>
        <div className="field">
          <label>Documents (images or PDFs)</label>
          <input type="file" multiple accept="image/*,application/pdf"
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))} required />
          <ul className="file-list">
            {files.map((f) => <li key={f.name}>{f.name} ({Math.round(f.size / 1024)} KB)</li>)}
          </ul>
        </div>
        <div className="field">
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" style={{ width: "auto" }} checked={simulateFailure}
              onChange={(e) => setSimulateFailure(e.target.checked)} />
            Simulate a component failure (tests graceful degradation)
          </label>
        </div>
        <button className="primary" type="submit" disabled={loading || files.length === 0}>
          {loading ? "Processing…" : "Submit claim"}
        </button>
      </form>

      {error && <div className="banner error">{error}</div>}

      {loading && <ProgressChecklist stages={stages} />}

      {response && (
        <>
          <div className={`banner ${response.status === "DECIDED" ? "decided" : "doc-rejected"}`}>
            <strong>{response.claim_id}</strong> — {response.member_message}
          </div>

          {response.status === "DOCUMENT_REJECTED" && (
            <DocumentIssues issues={response.document_issues} />
          )}

          {response.decision && <DecisionCard decision={response.decision} />}

          <TraceViewer
            trace={response.trace}
            explanation={response.explanation}
            processing={response.processing}
          />
        </>
      )}
    </main>
  );
}
