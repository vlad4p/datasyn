import type { UiLocale } from "./locale";

const ARGS_MAX = 140;

function truncate(s: string, max: number): string {
  const t = s.trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max - 1)}…`;
}

function scopePrefix(source: "main" | "subagent" | undefined, locale: UiLocale): string {
  if (source !== "subagent") return "";
  return locale === "es" ? "Especialista · " : "Specialist · ";
}

/** Map LangGraph / Deep Agents node ids to short, readable status lines. */
export function formatStreamStep(
  node: string | undefined,
  source: "main" | "subagent" | undefined,
  locale: UiLocale,
): string {
  const es = locale === "es";
  const pre = scopePrefix(source, locale);
  const n = (node ?? "").trim().toLowerCase();
  if (!n) return pre + (es ? "En curso…" : "Working…");

  const mapEn: Record<string, string> = {
    model_request: "Thinking…",
    tools: "Using tools…",
    "__interrupt__": "Waiting for input…",
  };
  const mapEs: Record<string, string> = {
    model_request: "Pensando…",
    tools: "Usando herramientas…",
    "__interrupt__": "Esperando entrada…",
  };
  const map = es ? mapEs : mapEn;
  const human = map[n] ?? (es ? `Paso: ${node}` : `Step: ${node}`);
  return pre + human;
}

export function formatStreamToolDelta(
  toolName: string | undefined,
  argsFragment: string | undefined,
  source: "main" | "subagent" | undefined,
  locale: UiLocale,
): string {
  const es = locale === "es";
  const pre = scopePrefix(source, locale);
  const name = (toolName ?? "").trim();
  const frag = truncate(argsFragment ?? "", ARGS_MAX);
  const lower = name.toLowerCase();

  if (lower === "task") {
    const base = es ? "Delegando al especialista…" : "Delegating to specialist…";
    return pre + base;
  }
  if (name) {
    const call = es ? `Llamando a «${name}»` : `Calling ${name}`;
    if (frag) return `${pre}${call} — ${frag}`;
    return `${pre}${call}…`;
  }
  if (frag) return pre + (es ? `Argumentos: ${frag}` : `Args: ${frag}`);
  return pre + (es ? "Herramienta…" : "Tool…");
}
