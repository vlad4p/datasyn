import { useEffect, useMemo, useRef, useState } from "react";

type PlotlySpec = {
  data: unknown[];
  layout?: Record<string, unknown>;
  config?: Record<string, unknown>;
};

type PlotlyModule = {
  newPlot: (
    root: HTMLElement,
    data: unknown[],
    layout?: Record<string, unknown>,
    config?: Record<string, unknown>,
  ) => Promise<unknown>;
  purge: (root: HTMLElement) => void;
  Plots: { resize: (root: HTMLElement) => void };
  downloadImage: (
    root: HTMLElement,
    opts: { format?: "png" | "jpeg" | "webp" | "svg"; filename?: string; width?: number; height?: number },
  ) => Promise<void>;
};

const BASE_CONFIG = {
  responsive: true,
  displaylogo: false,
  toImageButtonOptions: { format: "png", filename: "plot", scale: 2 },
};

function withDarkDefaults(input: PlotlySpec): PlotlySpec {
  const layout = (input.layout ?? {}) as Record<string, unknown>;
  return {
    ...input,
    layout: {
      paper_bgcolor: "#0a0d12",
      plot_bgcolor: "#0a0d12",
      font: { color: "#e8eaef" },
      ...layout,
    },
    config: {
      ...BASE_CONFIG,
      ...(input.config ?? {}),
    },
  };
}

function downloadTextFile(filename: string, content: string): void {
  const blob = new Blob([content], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

type Props = { spec: PlotlySpec };

/** Interactive Plotly renderer for fenced `plotly` code blocks. */
export function PlotlyChart({ spec }: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const plotlyRef = useRef<PlotlyModule | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const specKey = useMemo(() => JSON.stringify(spec), [spec]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    let cancelled = false;
    setError(null);

    const run = async () => {
      try {
        const Plotly = (await import("plotly.js-dist-min")).default as PlotlyModule;
        plotlyRef.current = Plotly;
        const parsed = JSON.parse(specKey) as PlotlySpec;
        const themed = withDarkDefaults(parsed);
        if (!Array.isArray(themed.data)) {
          throw new Error("Plotly spec must include a data array.");
        }
        await Plotly.newPlot(root, themed.data, themed.layout, themed.config);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    };

    void run();

    const onResize = () => {
      const Plotly = plotlyRef.current;
      const el = rootRef.current;
      if (!Plotly || !el) return;
      Plotly.Plots.resize(el);
    };
    window.addEventListener("resize", onResize);
    return () => {
      cancelled = true;
      window.removeEventListener("resize", onResize);
      const Plotly = plotlyRef.current;
      if (Plotly && root) Plotly.purge(root);
    };
  }, [specKey]);

  const exportPng = async () => {
    const Plotly = plotlyRef.current;
    const root = rootRef.current;
    if (!Plotly || !root) return;
    try {
      setBusy(true);
      await Plotly.downloadImage(root, { format: "png", filename: "chat-plot" });
    } finally {
      setBusy(false);
    }
  };

  const exportJson = () => {
    downloadTextFile("chat-plot.json", JSON.stringify(spec, null, 2));
  };

  return (
    <div className="plotly-chart-wrap">
      {error ? (
        <div className="chart-error" role="alert">
          <strong>Plot</strong> could not render: {error}
        </div>
      ) : null}
      <div className="plotly-toolbar">
        <button type="button" className="btn ghost mini" onClick={() => void exportPng()} disabled={Boolean(error) || busy}>
          Export PNG
        </button>
        <button type="button" className="btn ghost mini" onClick={exportJson}>
          Export JSON
        </button>
      </div>
      <div className="plotly-chart-root" ref={rootRef} aria-hidden={Boolean(error)} />
    </div>
  );
}
