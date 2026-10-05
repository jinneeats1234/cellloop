import { useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { Candidate, RecommendationResult } from "../api/types";
import { useConfig } from "../auth/AuthContext";
import Plot, { barMarker, plotText, token } from "../components/charts/Plot";
import { Card, ErrorBanner, FieldMessage, PageHeader, Spinner, fmt, issueClass } from "../components/ui";
import { checkNumber, checkText } from "../lib/validation";

const UNCERTAINTY: Record<Candidate["uncertainty"], string> = {
  low: "Low uncertainty",
  medium: "Moderate uncertainty",
  high: "High uncertainty: exploratory",
  unknown: "No prediction",
};

export default function RecommendPage() {
  const config = useConfig();
  const [n, setN] = useState("5");
  const [temp, setTemp] = useState(String(config.targets.operating_temp_c));
  const [target, setTarget] = useState(String(config.targets.asr_ohm_cm2));
  const [cathode, setCathode] = useState("");
  const [result, setResult] = useState<RecommendationResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const issues = {
    n: checkNumber(n, { label: "Suggestions", min: 1, max: 12, integer: true, required: true }),
    temp: checkNumber(temp, { label: "Temperature", min: 400, max: 1000, required: true, unit: "°C" }),
    target: checkNumber(target, { label: "Target ASR", min: 0.01, max: 50, required: true, unit: "Ω·cm²" }),
    cathode: checkText(cathode, { label: "Cathode filter", max: 100 }),
  };
  const valid = Object.values(issues).every((i) => !i);

  const run = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError(null);
    try {
      setResult(
        await api.recommend({
          n: Number(n),
          target_temp_c: Number(temp),
          target_asr: Number(target),
          filters: cathode.trim() ? { cathode_composition: cathode.trim() } : {},
        }),
      );
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const specs = config.design_space;
  const cands = result?.candidates.filter((c) => c.predicted_asr !== null && c.ci95) ?? [];

  return (
    <>
      <PageHeader
        eyebrow="Program"
        title="Next experiment"
        subtitle="Candidate cell designs ranked by expected improvement from a Gaussian-process model of approved results: the most learning per test. Each suggestion carries its uncertainty; treat it as input to your judgment."
      />
      <Card className="mb-4">
        <form onSubmit={run} noValidate className="grid grid-cols-2 items-start gap-3 sm:flex sm:flex-wrap">
          {(
            [
              ["n", "Suggestions", n, setN, "numeric", "sm:w-28"],
              ["temp", "Operating temp (°C)", temp, setTemp, "decimal", "sm:w-40"],
              ["target", "Target ASR (Ω·cm²)", target, setTarget, "decimal", "sm:w-40"],
              ["cathode", "Restrict to cathode (optional)", cathode, setCathode, "text", "col-span-2 sm:w-52"],
            ] as const
          ).map(([key, label, value, set, mode, width]) => (
            <div key={key} className={width}>
              <label className="label" htmlFor={key}>
                {label}
              </label>
              <input
                id={key}
                className={`input ${issueClass(issues[key])}`}
                inputMode={mode === "text" ? undefined : mode}
                value={value}
                placeholder={key === "cathode" ? "e.g. LSCF" : undefined}
                aria-invalid={!!issues[key] || undefined}
                aria-describedby={`${key}-msg`}
                onChange={(e) => set(e.target.value)}
              />
              <FieldMessage id={`${key}-msg`} issue={issues[key]} />
            </div>
          ))}
          <button className="btn btn-primary col-span-2 sm:mt-6 sm:h-[34px] sm:self-start" disabled={busy || !valid}>
            {busy ? "Fitting model…" : "Recommend experiments"}
          </button>
        </form>
      </Card>
      <ErrorBanner error={error} />
      {busy && <Spinner label="Fitting Gaussian process and scoring candidates…" />}

      {result && !busy && (
        <>
          <div className="mb-4 grid gap-4 lg:grid-cols-3">
            <Card title="Model" className="lg:col-span-1">
              <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-[13px]">
                <dt className="muted">Engine</dt>
                <dd>{result.engine}</dd>
                <dt className="muted">Training records</dt>
                <dd>{result.n_training}</dd>
                <dt className="muted">Excluded</dt>
                <dd title="Approved records missing a design variable or ASR, or tested at a different temperature">{result.n_excluded}</dd>
                {result.best_observed && (
                  <>
                    <dt className="muted">Best so far</dt>
                    <dd>
                      <Link className="link" to={`/experiments/${result.best_observed.id}`}>
                        {result.best_observed.code}
                      </Link>{" "}
                      · {fmt(result.best_observed.asr)} Ω·cm²
                    </dd>
                  </>
                )}
              </dl>
              {result.message && <p className="note note-warn mt-3">{result.message}</p>}
            </Card>
            {result.feature_relevance.length > 0 && (
              <Card title="Which design variables matter most (model sensitivity)" className="lg:col-span-2">
                <Plot
                  height={220}
                  ariaLabel="Relative influence of each design variable in the fitted model"
                  data={[
                    {
                      type: "bar",
                      orientation: "h",
                      x: [...result.feature_relevance].reverse().map((f) => f.relevance * 100),
                      y: [...result.feature_relevance].reverse().map((f) => plotText(f.label)),
                      marker: barMarker(token("series-1")),
                      hovertemplate: "%{y}: %{x:.0f}%<extra></extra>",
                    },
                  ]}
                  layout={{ showlegend: false, margin: { l: 150, r: 16, t: 4, b: 40 }, xaxis: { title: { text: "Relative influence (%)" } }, bargap: 0.5 }}
                />
              </Card>
            )}
          </div>

          {cands.length > 0 && (
            <Card title="Predicted ASR with 95% intervals" className="mb-4">
              <Plot
                height={240}
                ariaLabel="Predicted ASR for each suggestion with 95% interval and the target line"
                data={[
                  {
                    type: "scatter",
                    mode: "markers",
                    x: cands.map((c) => c.predicted_asr as number),
                    y: cands.map((c) => `#${c.rank}`),
                    error_x: {
                      type: "data",
                      symmetric: false,
                      array: cands.map((c) => (c.ci95 as [number, number])[1] - (c.predicted_asr as number)),
                      arrayminus: cands.map((c) => (c.predicted_asr as number) - (c.ci95 as [number, number])[0]),
                      color: token("series-1"),
                      thickness: 2,
                      width: 4,
                    },
                    marker: { color: token("series-1"), size: 8, line: { color: token("surface-1"), width: 1.5 } },
                    hovertemplate: "Suggestion %{y}<br>Expected %{x:.3f} Ω·cm²<extra></extra>",
                  },
                ]}
                layout={{
                  showlegend: false,
                  margin: { l: 40, r: 16, t: 28, b: 44 },
                  xaxis: { title: { text: "Total ASR (Ω·cm²)" } },
                  yaxis: { autorange: "reversed" },
                  shapes: [
                    {
                      type: "line",
                      yref: "paper",
                      y0: 0,
                      y1: 1,
                      x0: Number(target),
                      x1: Number(target),
                      line: { color: token("reference"), dash: "dash", width: 1.5 },
                    },
                  ],
                  annotations: [
                    { yref: "paper", y: 1, x: Number(target), text: `Target ${target}`, showarrow: false, yanchor: "bottom", yshift: 4, font: { color: token("text-secondary"), size: 11 } },
                  ],
                }}
              />
            </Card>
          )}

          <div className="grid gap-4 md:grid-cols-2">
            {result.candidates.map((c) => (
              <Card key={c.rank} title={`Suggestion #${c.rank}`} actions={<span className="muted text-xs">{UNCERTAINTY[c.uncertainty]}</span>}>
                {c.predicted_asr !== null && c.ci95 && (
                  <div className="mb-3 flex flex-wrap items-baseline gap-x-4 gap-y-1">
                    <span className="text-2xl font-semibold tabular-nums">{fmt(c.predicted_asr)}</span>
                    <span className="muted text-sm">
                      Ω·cm² expected · 95% interval {fmt(c.ci95[0])}–{fmt(c.ci95[1])}
                    </span>
                    <span className="text-sm">
                      {Math.round((c.p_beats_target ?? 0) * 100)}% chance of beating {target}
                    </span>
                  </div>
                )}
                <table className="table mb-3">
                  <tbody>
                    {specs.map((s) => (
                      <tr key={s.key}>
                        <td className="muted">{s.label}</td>
                        <td className="text-right font-medium tabular-nums">
                          {fmt(c.params[s.key], 4)} {s.unit}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="text-sm leading-relaxed">{c.rationale}</p>
                {c.nearest_experiment && (
                  <p className="muted mt-2 text-xs">
                    Closest prior test:{" "}
                    <Link className="link" to={`/experiments/${c.nearest_experiment.id}`}>
                      {c.nearest_experiment.code}
                    </Link>{" "}
                    ({fmt(c.nearest_experiment.asr)} Ω·cm², {c.nearest_experiment.distance_pct}% of design range away)
                  </p>
                )}
              </Card>
            ))}
          </div>
        </>
      )}
    </>
  );
}
