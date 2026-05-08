import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";
import type { VisualizationSpec } from "vega-embed";

import { prepareMarkdownContent } from "../prepareMarkdown";
import { ChatChart } from "./ChatChart";
import { MermaidDiagram } from "./MermaidDiagram";
import { PlotlyChart } from "./PlotlyChart";

function parseLanguage(className?: string): string | undefined {
  const m = /language-([\w+-]+)/.exec(className ?? "");
  return m?.[1]?.toLowerCase();
}

/** Map common aliases so fenced blocks still render as charts. */
function chartLanguage(lang: string | undefined): string | undefined {
  if (!lang) return lang;
  if (lang === "chart" || lang === "vl" || lang === "vegalite") return "vega-lite";
  return lang;
}

function JsonArrayTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows.length) return <pre className="code-block">[]</pre>;
  const keys = Object.keys(rows[0]!);
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {keys.map((k) => (
              <th key={k}>{k}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {keys.map((k) => (
                <td key={k}>{formatCell(row[k])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function JsonObjectTable({ obj }: { obj: Record<string, unknown> }) {
  const entries = Object.entries(obj);
  return (
    <div className="table-wrap">
      <table className="data-table kv">
        <tbody>
          {entries.map(([k, v]) => (
            <tr key={k}>
              <th>{k}</th>
              <td>{formatCell(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function isPlainObject(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}

/** Heuristic: Vega-Lite / Vega JSON embedded in ```json blocks. */
function tryVegaSpec(data: unknown): VisualizationSpec | null {
  if (!isPlainObject(data)) return null;
  const o = data;
  const schema = typeof o.$schema === "string" ? o.$schema : "";
  if (schema.includes("vega-lite") || schema.includes("vega.github.io/schema/vega/")) {
    return o as VisualizationSpec;
  }
  if (o.mark != null && o.encoding != null) return o as VisualizationSpec;
  if (o.layer != null || o.vconcat != null || o.hconcat != null || o.concat != null) {
    return o as VisualizationSpec;
  }
  return null;
}

type PlotlySpec = {
  data: unknown[];
  layout?: Record<string, unknown>;
  config?: Record<string, unknown>;
};

function tryPlotlySpec(data: unknown): PlotlySpec | null {
  if (!isPlainObject(data)) return null;
  const o = data as Record<string, unknown>;
  if (!Array.isArray(o.data)) return null;
  const layout = isPlainObject(o.layout) ? o.layout : undefined;
  const config = isPlainObject(o.config) ? o.config : undefined;
  return { data: o.data, layout, config };
}

function CodeBlock({ className, children }: { className?: string; children?: ReactNode }) {
  const text = String(children).replace(/\n$/, "");
  const lang = chartLanguage(parseLanguage(className));

  if (lang === "mermaid") {
    return <MermaidDiagram chart={text} />;
  }

  if (lang === "vega-lite" || lang === "vega") {
    try {
      const spec = JSON.parse(text) as unknown;
      const vega = tryVegaSpec(spec) ?? (isPlainObject(spec) ? (spec as VisualizationSpec) : null);
      if (vega) return <ChatChart spec={vega} />;
    } catch {
      /* fall through */
    }
    return (
      <pre className="code-block">
        <code className={className}>{children}</code>
      </pre>
    );
  }

  if (lang === "plotly" || lang === "plotly-json" || lang === "plot") {
    try {
      const parsed = JSON.parse(text) as unknown;
      const plotSpec = tryPlotlySpec(parsed);
      if (plotSpec) return <PlotlyChart spec={plotSpec} />;
    } catch {
      /* fall through */
    }
    return (
      <pre className="code-block">
        <code className={className}>{children}</code>
      </pre>
    );
  }

  if (lang === "json") {
    try {
      const data = JSON.parse(text) as unknown;
      const vega = tryVegaSpec(data);
      if (vega) return <ChatChart spec={vega} />;
      const plotSpec = tryPlotlySpec(data);
      if (plotSpec) return <PlotlyChart spec={plotSpec} />;
      if (Array.isArray(data) && data.length > 0 && isPlainObject(data[0])) {
        return <JsonArrayTable rows={data as Record<string, unknown>[]} />;
      }
      if (isPlainObject(data)) {
        return <JsonObjectTable obj={data} />;
      }
    } catch {
      /* fall through */
    }
  }

  return (
    <pre className="code-block">
      <code className={className}>{children}</code>
    </pre>
  );
}

function isSafeImageUrl(url: string): boolean {
  const u = url.trim();
  if (u.startsWith("data:image/")) return u.length < 3_000_000;
  if (typeof window === "undefined") return true;
  try {
    const parsed = new URL(u, window.location.origin);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return u.startsWith("/") && !u.startsWith("//");
  }
}

const mdComponents: Components = {
  pre({ children }) {
    return <>{children}</>;
  },
  code(props) {
    const { className, children, ...rest } = props;
    const isFenced = Boolean(className && String(className).includes("language-"));
    if (isFenced) {
      return <CodeBlock className={className}>{children}</CodeBlock>;
    }
    return (
      <code className="inline-code" {...rest}>
        {children}
      </code>
    );
  },
  table({ children }) {
    return (
      <div className="table-wrap md-table-wrap">
        <table className="md-table">{children}</table>
      </div>
    );
  },
  img({ src, alt, title }) {
    const s = src ?? "";
    if (typeof s === "string" && !isSafeImageUrl(s)) {
      return (
        <span className="img-blocked muted small" title="URL not allowed">
          [image omitted: unsupported URL]
        </span>
      );
    }
    return <img className="md-img" src={s} alt={alt ?? ""} title={title ?? undefined} loading="lazy" />;
  },
};

type Props = {
  content: string;
  role: "user" | "assistant";
  /** Nests under assistant for delegated subagent text (Deep Agents `task` stream). */
  variant?: "default" | "subagent";
};

export function MarkdownMessage({ content, role, variant = "default" }: Props) {
  const prepared = prepareMarkdownContent(content);
  const sub = role === "assistant" && variant === "subagent" ? " subagent" : "";
  return (
    <div className={`bubble ${role}${sub}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={mdComponents}
        urlTransform={(url) => {
          const u = url.trim();
          if (u.startsWith("data:image/")) return u;
          return url;
        }}
      >
        {prepared}
      </ReactMarkdown>
    </div>
  );
}
