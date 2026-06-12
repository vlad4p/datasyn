import { useEffect, useId, useRef, useState } from "react";

type MermaidApi = typeof import("mermaid")["default"];

let mermaidPromise: Promise<MermaidApi> | null = null;

function loadMermaid(): Promise<MermaidApi> {
  if (!mermaidPromise) {
    mermaidPromise = import("mermaid").then(({ default: mermaid }) => {
      mermaid.initialize({
        startOnLoad: false,
        theme: "dark",
        securityLevel: "strict",
        fontFamily: "DM Sans, system-ui, sans-serif",
      });
      return mermaid;
    });
  }
  return mermaidPromise;
}

type Props = { chart: string };

export function MermaidDiagram({ chart }: Props) {
  const id = useId().replace(/:/g, "");
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let cancelled = false;
    setError(null);
    const rid = `mmd-${id}-${Math.random().toString(36).slice(2, 9)}`;
    (async () => {
      try {
        const mermaid = await loadMermaid();
        const { svg } = await mermaid.render(rid, chart);
        if (!cancelled && ref.current) ref.current.innerHTML = svg;
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [chart, id]);

  if (error) {
    return (
      <pre className="code-block diagram-error">
        Mermaid: {error}
        {"\n\n"}
        {chart}
      </pre>
    );
  }

  return <div className="mermaid-diagram" ref={ref} />;
}
