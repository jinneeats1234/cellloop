import { useMemo } from "react";
import type { EisData, IvData } from "../../api/types";
import Plot, { token } from "./Plot";

/** Nyquist plot: Z' vs −Z'' with equal axis scaling so arcs read as semicircles. */
export function NyquistChart({ eis, area }: { eis: EisData; area: number | null }) {
  const scale = area ?? 1;
  const unit = area ? "Ω·cm²" : "Ω";
  const data = useMemo(
    () => [
      {
        type: "scatter" as const,
        mode: "lines+markers" as const,
        x: eis.z_real.map((z) => z * scale),
        y: eis.z_imag.map((z) => -z * scale),
        customdata: eis.freq_hz,
        line: { color: token("series-1"), width: 2 },
        marker: { color: token("series-1"), size: 6.5, line: { color: token("surface-1"), width: 1.5 } },
        hovertemplate: `Z′ %{x:.4f} ${unit}<br>−Z″ %{y:.4f} ${unit}<br>%{customdata:.3g} Hz<extra></extra>`,
        name: "Spectrum",
      },
    ],
    [eis, scale, unit],
  );
  const layout = useMemo(
    () => ({
      showlegend: false,
      xaxis: { title: { text: `Z′ (${unit})` } },
      yaxis: { title: { text: `−Z″ (${unit})` }, scaleanchor: "x" as const, scaleratio: 1 },
    }),
    [unit],
  );
  return <Plot data={data} layout={layout} ariaLabel="Nyquist plot of the impedance spectrum" />;
}

/** Polarization behaviour as two single-axis charts (voltage and power) rather than one dual-axis chart. */
export function IvCharts({ iv }: { iv: IvData }) {
  const j = iv.current_density_a_cm2;
  const power = j.map((x, i) => x * iv.voltage_v[i]);
  const peak = power.indexOf(Math.max(...power));
  const common = { showlegend: false, xaxis: { title: { text: "Current density (A/cm²)" } } };
  const marker = (series: string) => ({ color: token(series), size: 6.5, line: { color: token("surface-1"), width: 1.5 } });

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div>
        <h3 className="eyebrow mb-2">Cell voltage</h3>
        <Plot
          height={260}
          ariaLabel="Polarization curve: voltage versus current density"
          data={[
            {
              type: "scatter",
              mode: "lines+markers",
              x: j,
              y: iv.voltage_v,
              line: { color: token("series-1"), width: 2 },
              marker: marker("series-1"),
              hovertemplate: "%{x:.3f} A/cm²<br>%{y:.3f} V<extra></extra>",
            },
          ]}
          layout={{ ...common, yaxis: { title: { text: "Voltage (V)" } } }}
        />
      </div>
      <div>
        <h3 className="eyebrow mb-2">Power density</h3>
        <Plot
          height={260}
          ariaLabel="Power density versus current density"
          data={[
            {
              type: "scatter",
              mode: "lines+markers",
              x: j,
              y: power,
              line: { color: token("series-2"), width: 2 },
              marker: marker("series-2"),
              hovertemplate: "%{x:.3f} A/cm²<br>%{y:.3f} W/cm²<extra></extra>",
            },
          ]}
          layout={{
            ...common,
            yaxis: { title: { text: "Power density (W/cm²)" } },
            annotations: [
              {
                x: j[peak],
                y: power[peak],
                text: `Peak ${power[peak].toFixed(2)} W/cm²`,
                showarrow: true,
                arrowcolor: token("text-secondary"),
                font: { color: token("text-primary"), size: 11 },
                ay: -28,
              },
            ],
          }}
        />
      </div>
    </div>
  );
}
