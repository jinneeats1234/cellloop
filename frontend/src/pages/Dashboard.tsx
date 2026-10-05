import { useMemo, useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { Dashboard } from "../api/types";
import Plot, { barMarker, plotText, token } from "../components/charts/Plot";
import { Card, ErrorBanner, PageHeader, Spinner, Stat, fmt, orgLabel } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

const SERIES = ["series-1", "series-2", "series-3"];

export default function DashboardPage() {
  const { data, error, loading, reload } = useAsync(api.dashboard, []);
  if (loading) return <Spinner />;
  if (!data) return <ErrorBanner error={error} onRetry={reload} />;
  return <DashboardView d={data} />;
}

function DashboardView({ d }: { d: Dashboard }) {
  const [showTable, setShowTable] = useState(false);
  const t = d.targets;
  const prog = d.progress;
  const orgs = useMemo(() => [...new Set(d.asr_vs_temp.map((p) => p.organization))].sort(), [d]);

  const progressData = useMemo(
    () => [
      {
        type: "scatter" as const,
        mode: "markers" as const,
        name: "Each test",
        x: prog.series.map((p) => p.cycle),
        y: prog.series.map((p) => p.asr),
        text: prog.series.map((p) => plotText(`${p.code} · ${orgLabel(p.organization)} · ${p.date}`)),
        marker: { color: token("text-muted"), size: 7, opacity: 0.75, line: { color: token("surface-1"), width: 1.5 } },
        hovertemplate: "%{text}<br>ASR %{y:.3f} Ω·cm²<extra></extra>",
      },
      {
        type: "scatter" as const,
        mode: "lines" as const,
        name: "Best so far",
        x: prog.series.map((p) => p.cycle),
        y: prog.series.map((p) => p.best),
        line: { color: token("series-1"), width: 2, shape: "hv" as const },
        hovertemplate: "Best so far %{y:.3f} Ω·cm²<extra></extra>",
      },
    ],
    [prog],
  );
  const progressLayout = useMemo(
    () => ({
      xaxis: { title: { text: `Experiment cycle at ${t.operating_temp_c} °C` } },
      yaxis: { title: { text: "Total ASR (Ω·cm²)" }, type: "log" as const, tickvals: [0.2, 0.3, 0.4, 0.5, 0.7, 1, 1.5, 2] },
      shapes: [
        {
          type: "line" as const,
          xref: "paper" as const,
          x0: 0,
          x1: 1,
          y0: t.asr_ohm_cm2,
          y1: t.asr_ohm_cm2,
          line: { color: token("reference"), width: 1.5, dash: "dash" as const },
        },
      ],
      annotations: [
        {
          xref: "paper" as const,
          x: 1,
          y: Math.log10(t.asr_ohm_cm2),
          xanchor: "right" as const,
          yanchor: "bottom" as const,
          text: `Target ${t.asr_ohm_cm2} Ω·cm²`,
          showarrow: false,
          font: { color: token("text-secondary"), size: 11 },
        },
      ],
    }),
    [t],
  );

  const scatterData = useMemo(
    () =>
      orgs.map((org, i) => {
        const pts = d.asr_vs_temp.filter((p) => p.organization === org);
        return {
          type: "scatter" as const,
          mode: "markers" as const,
          name: plotText(orgLabel(org)),
          x: pts.map((p) => p.temp),
          y: pts.map((p) => p.asr),
          text: pts.map((p) => plotText(`${p.code} · ${p.cathode ?? "?"}`)),
          marker: { color: token(SERIES[i % SERIES.length]), size: 7.5, line: { color: token("surface-1"), width: 1.5 } },
          hovertemplate: "%{text}<br>%{x} °C · %{y:.3f} Ω·cm²<extra></extra>",
        };
      }),
    [d, orgs],
  );

  const missing = d.completeness.missing_by_field.filter((m) => m.missing_pct > 0).slice(0, 8).reverse();
  const completenessOk = (d.completeness.pct_complete ?? 0) >= t.completeness_pct;
  const turnaroundOk = (d.turnaround.pct_within_target ?? 0) >= 90;

  return (
    <>
      <PageHeader
        eyebrow="Program"
        title="Dashboard"
        subtitle={`Progress toward ${t.asr_ohm_cm2} Ω·cm² total ASR at ${t.operating_temp_c} °C, and health of the partner data loop.`}
      />
      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Best ASR at target temp"
          value={prog.best_asr ? fmt(prog.best_asr) : "—"}
          unit={prog.best_asr ? "Ω·cm²" : undefined}
          status={prog.best_asr !== null && prog.best_asr <= t.asr_ohm_cm2 ? "good" : "warn"}
          hint={
            prog.cycles_to_target
              ? `Target met at cycle ${prog.cycles_to_target} (${fmt(prog.cycle_reduction_pct)}% fewer than ${t.baseline_cycles_to_target}-cycle baseline)`
              : `Target ${t.asr_ohm_cm2} at ${t.operating_temp_c} °C · ${prog.series.length} cycles so far`
          }
        />
        <Stat
          label="Median time to structured record"
          value={d.turnaround.median_hours !== null ? fmt(d.turnaround.median_hours) : "—"}
          unit={d.turnaround.median_hours !== null ? "hours" : undefined}
          status={turnaroundOk ? "good" : "warn"}
          hint={`${fmt(d.turnaround.pct_within_target)}% within ${t.turnaround_hours} h (n=${d.turnaround.n})`}
        />
        <Stat
          label="Records with complete metadata"
          value={d.completeness.pct_complete !== null ? fmt(d.completeness.pct_complete) : "—"}
          unit={d.completeness.pct_complete !== null ? "%" : undefined}
          status={completenessOk ? "good" : "warn"}
          hint={`Target ≥ ${t.completeness_pct}% · ${d.completeness.n} approved records`}
        />
        <Stat
          label="Awaiting review"
          value={d.counts.pending_review}
          unit="records"
          hint={
            <Link to="/review" className="link">
              Open review queue
            </Link>
          }
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card
          title="ASR progress toward target"
          className="lg:col-span-2"
          actions={
            <button className="btn btn-sm" onClick={() => setShowTable((s) => !s)}>
              {showTable ? "Show chart" : "Show table"}
            </button>
          }
        >
          {showTable ? (
            <div className="max-h-80 overflow-auto">
              <table className="table min-w-[420px]">
                <thead>
                  <tr>
                    <th>Cycle</th>
                    <th>Experiment</th>
                    <th>Date</th>
                    <th>ASR</th>
                    <th>Best so far</th>
                  </tr>
                </thead>
                <tbody>
                  {prog.series.map((p) => (
                    <tr key={p.id}>
                      <td>{p.cycle}</td>
                      <td>
                        <Link className="link" to={`/experiments/${p.id}`}>
                          {p.code}
                        </Link>
                      </td>
                      <td>{p.date}</td>
                      <td className="tabular-nums">{fmt(p.asr)}</td>
                      <td className="tabular-nums">{fmt(p.best)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Plot data={progressData} layout={progressLayout} ariaLabel="ASR per experiment cycle with best-so-far line and target" />
          )}
        </Card>

        <Card title="Missing required metadata (approved records)">
          {missing.length ? (
            <Plot
              height={Math.max(150, 70 + missing.length * 40)}
              ariaLabel="Share of approved records missing each required field"
              data={[
                {
                  type: "bar",
                  orientation: "h",
                  x: missing.map((m) => m.missing_pct),
                  y: missing.map((m) => plotText(m.label)),
                  marker: barMarker(token("series-1")),
                  hovertemplate: "%{y}: %{x}% missing<extra></extra>",
                  text: missing.map((m) => `${m.missing_pct}%`),
                  textposition: "outside",
                  cliponaxis: false,
                  textfont: { color: token("text-secondary") },
                },
              ]}
              layout={{ showlegend: false, margin: { l: 140, r: 16, t: 4, b: 40 }, xaxis: { title: { text: "% of approved records" }, range: [0, Math.max(...missing.map((m) => m.missing_pct)) * 1.35] }, bargap: 0.55 }}
            />
          ) : null}
          <div className="divider mt-4 pt-4">
            <p className="subtle text-[12px] leading-relaxed">
              {missing.length
                ? `A record is complete when all ${d.completeness.missing_by_field.length} required fields are present. Program target: at least ${t.completeness_pct}% of approved records complete.`
                : "Every approved record has all required fields."}
            </p>
            <Link to="/experiments" className="link mt-2 inline-block text-[12px]">
              Browse experiments
            </Link>
          </div>
        </Card>

        <Card title="ASR vs operating temperature, by partner" className="lg:col-span-2">
          <Plot
            data={scatterData}
            layout={{
              xaxis: { title: { text: "Operating temperature (°C)" } },
              yaxis: { title: { text: "Total ASR (Ω·cm²)" }, type: "log", tickvals: [0.2, 0.3, 0.5, 0.7, 1, 2, 3, 5] },
            }}
            ariaLabel="Scatter of total ASR against operating temperature, colored by partner lab"
          />
        </Card>

        <Card title="Submissions by partner">
          <div className="overflow-x-auto">
          <table className="table [&_td]:px-1.5 [&_th]:px-1.5">
            <thead>
              <tr>
                <th>Partner</th>
                <th>Approved</th>
                <th>Pending</th>
                <th>Rej.</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(d.by_partner).map(([org, c]) => (
                <tr key={org}>
                  <td>{orgLabel(org)}</td>
                  <td className="tabular-nums">{c.approved}</td>
                  <td className="tabular-nums">{c.pending_review}</td>
                  <td className="tabular-nums">{c.rejected}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          <h3 className="card-title mt-6 mb-2">Recent activity</h3>
          <ul className="space-y-1 text-xs">
            {d.recent_activity.slice(0, 6).map((a, i) => (
              <li key={i} className="muted">
                <span className="font-medium text-[var(--text-primary)]">{a.action.replace(/_/g, " ")}</span> by {a.actor} ·{" "}
                {new Date(a.at).toLocaleString()}
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
}
