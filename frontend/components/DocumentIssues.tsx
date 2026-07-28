import type { DocumentIssue } from "@/lib/types";

// Early-stop view: each issue tells the member exactly what to fix.
export default function DocumentIssues({ issues }: { issues: DocumentIssue[] }) {
  return (
    <div className="card">
      <h2>Document problems — please fix and resubmit</h2>
      {issues.map((issue, i) => (
        <div className="issue" key={i}>
          <div className="code">{issue.code.replaceAll("_", " ")}</div>
          <div>{issue.message}</div>
          {(issue.found || issue.expected) && (
            <div style={{ marginTop: 6, fontSize: 13, color: "var(--muted)" }}>
              {issue.found && <div>Found: {issue.found}</div>}
              {issue.expected && <div>Needed: {issue.expected}</div>}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
