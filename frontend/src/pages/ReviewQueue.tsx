import { Link } from "react-router";
import { api } from "../api/client";
import { Card, Empty, ErrorBanner, PageHeader, Spinner, orgLabel } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

function age(iso: string): string {
  const h = (Date.now() - new Date(iso).getTime()) / 36e5;
  return h < 1 ? "< 1 h" : h < 48 ? `${Math.round(h)} h` : `${Math.round(h / 24)} d`;
}

export default function ReviewQueuePage() {
  const { data, error, loading, reload } = useAsync(() => api.experiments({ status: "pending_review" }), []);
  const items = [...(data?.items ?? [])].sort((a, b) => a.submitted_at.localeCompare(b.submitted_at));

  return (
    <>
      <PageHeader
        eyebrow="Data"
        title="Review queue"
        subtitle="AI-extracted records awaiting scientist sign-off, oldest first. Target: structured and searchable within 48 hours of submission."
      />
      <ErrorBanner error={error} onRetry={reload} />
      <Card>
        {loading ? (
          <Spinner />
        ) : !items.length ? (
          <Empty>Nothing to review. New partner uploads will appear here.</Empty>
        ) : (
          <>
            {/* Phones: one card per record */}
            <ul className="space-y-2 sm:hidden">
              {items.map((e) => {
                const waitingH = (Date.now() - new Date(e.submitted_at).getTime()) / 36e5;
                return (
                  <li key={e.id} className="rounded-lg border border-[var(--border)] p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="font-semibold">{e.code}</div>
                        <div className="muted text-xs">
                          {e.fields.cell_id ?? "no cell ID"} · {orgLabel(e.organization)}
                        </div>
                      </div>
                      <span className={`text-xs tabular-nums ${waitingH > 36 ? "font-medium text-[var(--warn)]" : "muted"}`}>
                        {waitingH > 36 && <span aria-label="approaching 48 h target">▲ </span>}
                        waiting {age(e.submitted_at)}
                      </span>
                    </div>
                    <p className="muted mt-1 text-xs break-all">{e.document_title ?? "—"}</p>
                    <div className="mt-2 flex items-center justify-between">
                      <span className="text-xs">Metadata {Math.round(e.completeness * 100)}%</span>
                      <Link className="btn btn-primary" to={`/review/${e.id}`}>
                        Review
                      </Link>
                    </div>
                  </li>
                );
              })}
            </ul>
            <div className="hidden overflow-x-auto sm:block">
          <table className="table min-w-[640px]">
            <thead>
              <tr>
                <th>Record</th>
                <th>Partner</th>
                <th>Source document</th>
                <th>Waiting</th>
                <th>Metadata</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((e) => {
                const waitingH = (Date.now() - new Date(e.submitted_at).getTime()) / 36e5;
                return (
                  <tr key={e.id}>
                    <td>
                      <div className="font-medium">{e.code}</div>
                      <div className="muted text-xs">{e.fields.cell_id ?? "no cell ID"}</div>
                    </td>
                    <td>{orgLabel(e.organization)}</td>
                    <td className="text-xs">{e.document_title ?? "—"}</td>
                    <td className={`tabular-nums ${waitingH > 36 ? "font-medium text-[var(--warn)]" : ""}`}>
                      {waitingH > 36 && <span aria-label="approaching 48 h target">▲ </span>}
                      {age(e.submitted_at)}
                    </td>
                    <td className="tabular-nums">{Math.round(e.completeness * 100)}%</td>
                    <td className="text-right">
                      <Link className="btn btn-primary" to={`/review/${e.id}`}>
                        Review
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
            </div>
          </>
        )}
      </Card>
    </>
  );
}
