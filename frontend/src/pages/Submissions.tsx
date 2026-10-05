import { Link } from "react-router";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Card, Empty, ErrorBanner, PageHeader, Spinner, StatusBadge, orgLabel } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

export default function SubmissionsPage() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useAsync(api.documents, []);

  return (
    <>
      <PageHeader
        eyebrow="Data"
        title="Submissions"
        subtitle={user?.is_internal ? "All uploaded partner reports and internal documents." : `Reports submitted by ${orgLabel(user?.organization ?? "")}.`}
        actions={
          <>
            <button className="btn" onClick={reload}>
              Refresh
            </button>
            {user?.role !== "leadership" && (
              <Link className="btn btn-primary" to="/upload">
                Upload report
              </Link>
            )}
          </>
        }
      />
      <ErrorBanner error={error} onRetry={reload} />
      <Card>
        {loading ? (
          <Spinner />
        ) : !data?.length ? (
          <Empty>No submissions yet.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="table min-w-[700px]">
              <thead>
                <tr>
                  <th>Document</th>
                  {user?.is_internal && <th>Organization</th>}
                  <th>Uploaded</th>
                  <th>Status</th>
                  <th>Records</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {data.map((d) => (
                  <tr key={d.id}>
                    <td>
                      <div className="font-medium">{d.title}</div>
                      <div className="muted text-xs">
                        {d.filename} · {(d.size_bytes / 1024).toFixed(1)} KB
                      </div>
                    </td>
                    {user?.is_internal && <td>{orgLabel(d.organization)}</td>}
                    <td className="text-xs">
                      {new Date(d.uploaded_at).toLocaleString()}
                      <div className="muted">{d.uploaded_by}</div>
                    </td>
                    <td>
                      <StatusBadge status={d.status} />
                    </td>
                    <td className="space-x-2">
                      {d.experiment_ids.map((id, i) => (
                        <Link key={id} className="link" to={`/experiments/${id}`}>
                          #{i + 1}
                        </Link>
                      ))}
                    </td>
                    <td className="muted max-w-sm text-xs whitespace-pre-line">{d.error ?? d.extraction_notes}</td>
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
