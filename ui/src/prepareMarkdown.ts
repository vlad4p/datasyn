import { artifactFileUrl } from "./api";

/** Lines like "Santa Fe: 9,962 cases" (used to infer a bar chart when the model only pastes text). */
const CASES_LINE = /^([^:\n]+):\s*([\d,]+)\s*cases\s*\.?\s*$/i;

function maybeAppendInferredBarChart(content: string): string {
  if (content.includes("```vega-lite") || content.includes("```vega")) {
    return content;
  }
  if (/\bChart Image:\s*\/project\//i.test(content)) {
    return content;
  }

  const lines = content.split("\n");
  const rows: { category: string; value: number }[] = [];
  for (const line of lines) {
    const m = line.trim().match(CASES_LINE);
    if (!m) continue;
    const category = m[1].trim();
    const value = parseInt(m[2].replace(/,/g, ""), 10);
    if (!Number.isFinite(value) || value < 0) continue;
    rows.push({ category, value });
  }
  if (rows.length < 3) return content;

  const spec = {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    title: "Cases (from text)",
    data: { values: rows },
    width: 420,
    height: 260,
    mark: "bar",
    encoding: {
      x: { field: "category", type: "nominal", sort: "-y", title: "Category" },
      y: { field: "value", type: "quantitative", title: "Cases" },
    },
  };

  return (
    content.trimEnd() +
    "\n\n---\n\n*Interactive chart from the case list above:*\n\n```vega-lite\n" +
    JSON.stringify(spec, null, 2) +
    "\n```\n"
  );
}

function rewriteBrainFilesystemPaths(content: string): string {
  const toUrl = (rel: string) => artifactFileUrl(rel);

  let out = content;

  out = out.replace(
    /Chart Image:\s*\/project\/([^\s)]+\.(?:png|jpg|jpeg|gif|webp|svg))/gi,
    (_, rel: string) => `**Chart** (saved file)\n\n![Generated chart](${toUrl(rel)})`,
  );

  out = out.replace(
    /Report:\s*\/project\/([^\s)]+\.(?:md|csv))/gi,
    (_, rel: string) => {
      const name = rel.split("/").pop() ?? rel;
      return `**Report:** [${name}](${toUrl(rel)})`;
    },
  );

  out = out.replace(
    /\/project\/([^\s)]+\.(?:png|jpg|jpeg|gif|webp|svg|md|csv))/gi,
    (full, rel: string) => {
      if (full.includes("://")) return full;
      return toUrl(rel);
    },
  );

  return out;
}

/** Rewrites `/project/...` brain paths to API artifact URLs and may append a Vega-Lite bar chart from "X: N cases" lines. */
export function prepareMarkdownContent(content: string): string {
  let out = maybeAppendInferredBarChart(content);
  out = rewriteBrainFilesystemPaths(out);
  return out;
}
