import { useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Card, Empty, ErrorBanner, FieldMessage, PageHeader, Spinner, StatusBadge, fmt, issueClass, orgLabel } from "../components/ui";
import { checkNumber, checkText } from "../lib/validation";
import { useAsync } from "../hooks/useAsync";

export default function ExperimentsPage() {
  const { user } = useAuth();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("approved");
  const [temp, setTemp] = useState("");
  const [applied, setApplied] = useState({ q: "", status: "approved", temp: "" });
  const qIssue = checkText(q, { label: "Search", max: 200 });
  const tempIssue = checkNumber(temp, { label: "Temperature", min: 400, max: 1000, unit: "°C" });
  const valid = !qIssue && !tempIssue;

  const { data, error, loading, reload } = useAsync(() => {
    const t = Number(applied.temp);
    return api.experiments({
      q: applied.q,
      status: applied.status,
      min_temp: applied.temp ? t - 25 : undefined,
      max_temp: applied.temp ? t + 25 : undefined,
    });
  }, [applied]);

  return (
    <>
      <PageHeader
        eyebrow="Data"
        title="Experiments"
        subtitle={
          user?.is_internal
            ? "Have we tried this before? Search every structured experiment across partner labs."
            : "Your organization's experiment records. Other labs' data is never visible to you."
        }
      />
      <Card>
        <form
          className="mb-4 grid grid-cols-2 items-start gap-3 sm:flex sm:flex-wrap"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) setApplied({ q: q.trim(), status, temp: temp.trim() });
          }}
        >
          <div className="col-span-2 sm:min-w-56 sm:flex-1">
            <label className="label" htmlFor="q">
              Search (code, cell ID, composition, coating, notes)
            </label>
            <input
              id="q"
              className={`input ${issueClass(qIssue)}`}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="e.g. LSCF-GDC, spinel, CL-0012"
              aria-describedby="q-msg"
              aria-invalid={!!qIssue || undefined}
            />
            <FieldMessage id="q-msg" issue={qIssue} />
          </div>
          <div>
            <label className="label" htmlFor="status">
              Status
            </label>
            <select id="status" className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All</option>
              <option value="approved">Approved</option>
              <option value="pending_review">Pending review</option>
              <option value="rejected">Rejected</option>
            </select>
          </div>
          <div className="sm:w-40">
            <label className="label" htmlFor="temp">
              Operating temp ±25 °C
            </label>
            <input
              id="temp"
              className={`input ${issueClass(tempIssue)}`}
              inputMode="decimal"
              value={temp}
              onChange={(e) => setTemp(e.target.value)}
              placeholder="650"
              aria-describedby="temp-msg"
              aria-invalid={!!tempIssue || undefined}
            />
            <FieldMessage id="temp-msg" issue={tempIssue} />
          </div>
          <button className="btn btn-primary col-span-2 sm:mt-6 sm:h-[34px] sm:self-start" type="submit" disabled={!valid}>
            Search
          </button>
        </form>
        <ErrorBanner error={error} onRetry={reload} />
        {loading ? (
          <Spinner />
        ) : !data?.items.length ? (
          <Empty>No experiments match these filters.</Empty>
        ) : (
          <>
            <p className="muted mb-2 text-xs">{data.total} records</p>
            {/* Phones: one card per experiment */}
            <ul className="space-y-2 sm:hidden">
              {data.items.map((e) => (
                <li key={e.id}>
                  <Link
                    to={`/experiments/${e.id}`}
                    className="block rounded-lg border border-[var(--border)] p-3.5 transition-colors hover:bg-[var(--surface-2)]"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="font-semibold">{e.code}</div>
                        <div className="muted text-xs">
                          {fmt(e.fields.cell_id)}
                          {user?.is_internal && ` · ${orgLabel(e.organization)}`}
                        </div>
                      </div>
                      <StatusBadge status={e.status} />
                    </div>
                    <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
                      <dt className="muted">ASR</dt>
                      <dd className="font-semibold tabular-nums">{fmt(e.fields.asr_ohm_cm2)} Ω·cm²</dd>
                      <dt className="muted">Temperature</dt>
                      <dd className="tabular-nums">{fmt(e.fields.operating_temp_c)} °C</dd>
                      <dt className="muted">Cathode</dt>
                      <dd>{fmt(e.fields.cathode_composition)}</dd>
                      <dt className="muted">Electrolyte</dt>
                      <dd className="tabular-nums">{fmt(e.fields.electrolyte_thickness_um)} µm</dd>
                      <dt className="muted">Sintering</dt>
                      <dd className="tabular-nums">{fmt(e.fields.sintering_temp_c)} °C</dd>
                      <dt className="muted">Metadata</dt>
                      <dd className="tabular-nums">{Math.round(e.completeness * 100)}% complete</dd>
                    </dl>
                  </Link>
                </li>
              ))}
            </ul>
            <div className="hidden overflow-x-auto sm:block">
            <table className="table min-w-[760px]">
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Status</th>
                  {user?.is_internal && <th>Partner</th>}
                  <th>Cathode</th>
                  <th>Electrolyte (µm)</th>
                  <th>Sinter (°C)</th>
                  <th>Coating</th>
                  <th>T (°C)</th>
                  <th>ASR (Ω·cm²)</th>
                  <th>Metadata</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((e) => (
                  <tr key={e.id}>
                    <td>
                      <Link className="link font-medium whitespace-nowrap" to={`/experiments/${e.id}`}>
                        {e.code}
                      </Link>
                      <div className="muted text-xs">{fmt(e.fields.cell_id)}</div>
                    </td>
                    <td>
                      <StatusBadge status={e.status} />
                    </td>
                    {user?.is_internal && <td>{orgLabel(e.organization)}</td>}
                    <td>{fmt(e.fields.cathode_composition)}</td>
                    <td className="tabular-nums">{fmt(e.fields.electrolyte_thickness_um)}</td>
                    <td className="tabular-nums">{fmt(e.fields.sintering_temp_c)}</td>
                    <td>
                      {fmt(e.fields.coating_material)}
                      {e.fields.coating_thickness_um ? ` · ${fmt(e.fields.coating_thickness_um)} µm` : ""}
                    </td>
                    <td className="tabular-nums">{fmt(e.fields.operating_temp_c)}</td>
                    <td className="font-medium tabular-nums">{fmt(e.fields.asr_ohm_cm2)}</td>
                    <td className="tabular-nums">{Math.round(e.completeness * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </>
        )}
      </Card>
    </>
  );
}
