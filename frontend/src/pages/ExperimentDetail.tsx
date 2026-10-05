import { Link, useParams } from "react-router";
import { api } from "../api/client";
import type { FieldSpec } from "../api/types";
import { useAuth, useConfig } from "../auth/AuthContext";
import { IvCharts, NyquistChart } from "../components/charts/CurveCharts";
import { Card, ErrorBanner, PageHeader, Spinner, StatusBadge, fmt, orgLabel } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

export function groupFields(fields: FieldSpec[]): [string, FieldSpec[]][] {
  const groups = new Map<string, FieldSpec[]>();
  fields.forEach((f) => groups.set(f.group, [...(groups.get(f.group) ?? []), f]));
  return [...groups.entries()];
}

export default function ExperimentDetailPage() {
  const { id = "" } = useParams();
  const { user } = useAuth();
  const config = useConfig();
  const { data: e, error, loading, reload } = useAsync(() => api.experiment(id), [id]);
  if (loading) return <Spinner />;
  if (!e)
    return (
      <>
        <ErrorBanner error={error} onRetry={reload} />
        <Link className="link text-[13px]" to="/experiments">
          Back to experiments
        </Link>
      </>
    );

  const canReview = e.status === "pending_review" && (user?.role === "scientist" || user?.role === "admin");
  const area = typeof e.fields.active_area_cm2 === "number" ? e.fields.active_area_cm2 : null;

  return (
    <>
      <PageHeader
        eyebrow="Experiment"
        title={`${e.code} · ${fmt(e.fields.cell_id)}`}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge status={e.status} />
            {orgLabel(e.organization)} · metadata {Math.round(e.completeness * 100)}% complete
            {e.reviewed_by && ` · reviewed by ${e.reviewed_by}`}
          </span>
        }
        actions={
          canReview && (
            <Link className="btn btn-primary" to={`/review/${e.id}`}>
              Review this record
            </Link>
          )
        }
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {e.eis_data && (
            <Card title="Impedance spectrum (Nyquist)">
              <NyquistChart eis={e.eis_data} area={area} />
              {e.analysis.eis && (
                <p className="muted mt-2 text-xs">
                  {String(e.analysis.eis.method).replace(/^./, (c) => c.toUpperCase())}: ohmic {fmt(e.analysis.eis.ohmic_asr_ohm_cm2 ?? e.analysis.eis.r_ohmic_ohm)}, polarization{" "}
                  {fmt(e.analysis.eis.polarization_asr_ohm_cm2 ?? e.analysis.eis.r_polarization_ohm)}, total{" "}
                  {fmt(e.analysis.eis.asr_ohm_cm2 ?? e.analysis.eis.r_total_ohm)} {area ? "Ω·cm²" : "Ω"}
                </p>
              )}
            </Card>
          )}
          {e.iv_data && (
            <Card title="Polarization curve">
              <IvCharts iv={e.iv_data} />
            </Card>
          )}
          {!e.eis_data && !e.iv_data && (
            <Card>
              <p className="muted text-sm">No raw impedance or polarization data was attached to this record.</p>
            </Card>
          )}
          {e.review_comment && (
            <Card title="Reviewer comment">
              <p className="text-sm">{e.review_comment}</p>
            </Card>
          )}
        </div>
        <div className="space-y-4">
          {groupFields(config.fields).map(([group, specs]) => (
            <Card key={group} title={group}>
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-sm">
                {specs.map((f) => (
                  <div key={f.key} className="contents">
                    <dt className="muted">{f.label}</dt>
                    <dd className={`${typeof e.fields[f.key] === "number" ? "tabular-nums" : ""} ${e.fields[f.key] === null && f.required ? "text-[var(--warn)]" : ""}`}>
                      {e.fields[f.key] === null && f.required ? "missing" : fmt(e.fields[f.key], 4)}
                      {e.fields[f.key] !== null && f.unit ? ` ${f.unit}` : ""}
                    </dd>
                  </div>
                ))}
              </dl>
            </Card>
          ))}
          {e.document_id && (
            <Card title="Source">
              <p className="text-sm">{e.document_title}</p>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
