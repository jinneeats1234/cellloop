import Plotly from "plotly.js-dist-min";
import type { Config, Data, Layout, PlotMarker } from "plotly.js";
import { useEffect, useRef, useState } from "react";

/** Read a chart role token from CSS (see index.css). */
export function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
}

/** Escape text before handing it to Plotly, which renders a subset of HTML in labels and
 *  hover text. Anything that originates from user or partner data must go through this. */
export function plotText(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Bar marker with rounded data-ends (plotly.js >= 2.29 supports cornerradius; its typings lag). */
export function barMarker(color: string): Partial<PlotMarker> {
  return { color, cornerradius: 4 } as unknown as Partial<PlotMarker>;
}

function useColorScheme(): string {
  const [scheme, setScheme] = useState(() => (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  useEffect(() => {
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const on = () => setScheme(mq.matches ? "dark" : "light");
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return scheme;
}

interface Props {
  data: Data[];
  layout?: Partial<Layout>;
  height?: number;
  ariaLabel: string;
}

/** Thin Plotly wrapper: theme-aware, responsive, recessive axes, hover on by default. */
export default function Plot({ data, layout = {}, height = 320, ariaLabel }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const scheme = useColorScheme();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const text = token("text-secondary");
    const subtle = token("text-3") || text;
    const grid = token("grid");
    const axis = {
      gridcolor: grid,
      zerolinecolor: grid,
      linecolor: token("border-strong") || grid,
      showline: true,
      ticks: "" as const,
      tickfont: { color: subtle, size: 11 },
      automargin: true,
    };
    const title = { font: { color: text, size: 11.5 }, standoff: 12 };
    const base: Partial<Layout> = {
      height,
      margin: { l: 52, r: 12, t: 12, b: 44 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: '"Inter Variable", ui-sans-serif, system-ui, sans-serif', color: token("text-primary"), size: 11.5 },
      hoverlabel: {
        bgcolor: token("surface-1"),
        bordercolor: token("border-strong") || grid,
        font: { family: '"Inter Variable", ui-sans-serif, system-ui, sans-serif', color: token("text-primary"), size: 12 },
      },
      legend: { orientation: "h", y: -0.24, x: 0, font: { color: text, size: 11.5 } },
      ...layout,
      xaxis: { ...axis, ...layout.xaxis, title: { ...title, ...(layout.xaxis?.title as object) } },
      yaxis: { ...axis, ...layout.yaxis, title: { ...title, ...(layout.yaxis?.title as object) } },
    };
    const config: Partial<Config> = { responsive: true, displaylogo: false, displayModeBar: "hover", modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"] };
    Plotly.react(el, data, base, config)
      .then(() => setFailed(false))
      .catch((err: unknown) => {
        console.error("[CellLoop] Chart failed to render:", err);
        setFailed(true);
      });
  }, [data, layout, height, scheme]);

  useEffect(() => {
    const el = ref.current;
    return () => {
      if (el) Plotly.purge(el);
    };
  }, []);

  return (
    <>
      {failed && (
        <div className="subtle flex items-center justify-center rounded-md border border-dashed border-[var(--border-strong)] text-[12.5px]" style={{ height }}>
          This chart couldn't be drawn. The underlying data is still available in the table view.
        </div>
      )}
      <div ref={ref} role="img" aria-label={ariaLabel} className={failed ? "hidden" : "w-full"} />
    </>
  );
}
