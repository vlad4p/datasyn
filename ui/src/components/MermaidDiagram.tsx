import { useEffect, useId, useRef, useState } from "react";
import mermaid from "mermaid";

let mermaidInit = false;

function ensureMermaidTheme() {
  if (mermaidInit) return;
  mermaid.initialize({
    startOnLoad: false,
    theme: "dark",
    securityLevel: "strict",
    fontFamily: "DM Sans, system-ui, sans-serif",
  });
  mermaidInit = true;
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
    ensureMermaidTheme();
    const rid = `mmd-${id}-${Math.random().toString(36).slice(2, 9)}`;
    (async () => {
      try {
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
