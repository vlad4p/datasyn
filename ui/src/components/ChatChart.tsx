import embed from "vega-embed";
import type { Result } from "vega-embed";
import type { VisualizationSpec } from "vega-embed";
import { useEffect, useRef, useState } from "react";

/** Stable options: a new object each render broke react-vega's useEffect dependency tracking. */
const EMBED_OPTIONS = {
  actions: { export: true, source: false, compiled: false, editor: false },
  renderer: "svg" as const,
};

function mergeDarkTheme(spec: VisualizationSpec): VisualizationSpec {
  const s = spec as Record<string, unknown>;
  const existing =
    s.config && typeof s.config === "object" && s.config !== null
      ? (s.config as Record<string, unknown>)
      : {};
  const axisExisting =
    existing.axis && typeof existing.axis === "object" && existing.axis !== null
      ? (existing.axis as Record<string, unknown>)
      : {};
  const legendExisting =
    existing.legend && typeof existing.legend === "object" && existing.legend !== null
      ? (existing.legend as Record<string, unknown>)
      : {};
  const titleExisting =
    existing.title && typeof existing.title === "object" && existing.title !== null
      ? (existing.title as Record<string, unknown>)
      : {};

  return {
    ...spec,
    config: {
      ...existing,
      background: existing.background ?? "#0a0d12",
      axis: {
        labelColor: "#c4c9d1",
        titleColor: "#e8eaef",
        gridColor: "#2a3140",
        domainColor: "#3d4555",
        ...axisExisting,
      },
      legend: {
        labelColor: "#c4c9d1",
        titleColor: "#e8eaef",
        ...legendExisting,
      },
      title: {
        color: "#e8eaef",
        ...titleExisting,
      },
    },
  } as VisualizationSpec;
}

type Props = { spec: VisualizationSpec };

/**
 * Renders Vega-Lite / Vega JSON in chat using imperative `vega-embed` (reliable sizing vs react-vega).
 */
export function ChatChart({ spec }: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const resultRef = useRef<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const specKey = JSON.stringify(spec);

  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;

    setError(null);
    let cancelled = false;
    resultRef.current = null;

    let parsed: VisualizationSpec;
    try {
      parsed = JSON.parse(specKey) as VisualizationSpec;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Invalid chart JSON");
      return;
    }

    const merged = mergeDarkTheme(parsed);
    el.innerHTML = "";

    void embed(el, merged, EMBED_OPTIONS).then(
      (r) => {
        if (cancelled) {
          r.finalize();
          return;
        }
        resultRef.current = r;
      },
      (e: unknown) => {
        el.innerHTML = "";
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
        }
      },
    );

    return () => {
      cancelled = true;
      resultRef.current?.finalize();
      resultRef.current = null;
      el.innerHTML = "";
    };
  }, [specKey]);

  return (
    <div className="vega-chart-wrap chat-chart-outer">
      {error ? (
        <div className="chart-error" role="alert">
          <strong>Chart</strong> could not render: {error}
        </div>
      ) : null}
      <div className="chat-chart-root" ref={rootRef} aria-hidden={Boolean(error)} />
    </div>
  );
}
