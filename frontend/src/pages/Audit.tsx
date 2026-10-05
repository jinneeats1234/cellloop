import { useState } from "react";
import { api } from "../api/client";
import { Card, Empty, ErrorBanner, PageHeader, Spinner, orgLabel } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

const ACTIONS = ["", "upload", "ai_extraction", "ai_extraction_failed", "edit_draft", "approve", "reject", "qa_query", "recommend", "download", "reextract"];

export default function AuditPage() {
  const [action, setAction] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const { data, error, loading, reload } = useAsync(() => api.audit({ action }), [action]);

  return (
    <>
      <PageHeader
        eyebrow="Data"
        title="Audit log"
        subtitle="Append-only record of uploads, AI extractions, human edits and approvals (with AI-versus-final differences), questions and recommendation runs."
        actions={
          <select className="input" value={action} onChange={(e) => setAction(e.target.value)} aria-label="Filter by action">
            {ACTIONS.map((a) => (
              <option key={a} value={a}>
                {a ? a.replace(/_/g, " ") : "All actions"}
              </option>
            ))}
          </select>
        }
      />
      <ErrorBanner error={error} onRetry={reload} />
      <Card>
        {loading ? (
          <Spinner />
        ) : !data?.length ? (
          <Empty>No audit entries.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="table min-w-[720px]">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Actor</th>
                  <th>Action</th>
                  <th>Entity</th>
                  <th>Org</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {data.map((a) => (
                  <tr key={a.id}>
                    <td className="text-xs whitespace-nowrap">{new Date(a.at).toLocaleString()}</td>
                    <td className="text-xs">{a.actor}</td>
                    <td className="font-medium">{a.action.replace(/_/g, " ")}</td>
                    <td className="muted text-xs">
                      {a.entity_type}
                      {a.entity_id && ` · ${a.entity_id.slice(0, 8)}`}
                    </td>
                    <td className="text-xs">{a.organization ? orgLabel(a.organization) : "—"}</td>
                    <td className="max-w-md">
                      {a.details && (
                        <button className="link text-xs" onClick={() => setOpen(open === a.id ? null : a.id)}>
                          {open === a.id ? "Hide" : "Show"}
                        </button>
                      )}
                      {open === a.id && <pre className="mt-1 max-h-64 overflow-auto rounded bg-[var(--surface-3)] p-2.5 text-[11px]">{JSON.stringify(a.details, null, 2)}</pre>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
