---
name: analyze-langfuse-trace
description: >-
  Analyze Langfuse trace JSON exports from datasyn-brain agent runs: latency,
  token usage, tool calls, subagent delegation, locale tags, and improvement
  recommendations. Use when the user asks to analyze, review, or debug a trace,
  Langfuse export, agent latency, or model/tool behavior from develop/trace-*.json.
---

# Analyze Langfuse traces (Datasyn brain)

Post-mortem **Langfuse trace JSON** exports from `datasyn-brain` (`datasyn-agent-chat` / `datasyn-agent-chat-stream`). Produce a **structured improvement report** — not a raw dump of observations.

## When to use

- User names a trace file (e.g. `develop/trace-<id>.json`) or asks *"where is the improvement?"* / *"why was this slow?"*
- Debugging agent latency, missing subagent delegation, token bloat, or locale mismatches
- Comparing before/after prompt or model changes

## Inputs

| Source | Typical path |
|--------|----------------|
| Local export | `develop/trace-<traceId>.json` |
| Langfuse UI | Export trace JSON and save under `develop/` |

Trace shape: top-level `trace` object with `input`, `output`, `latency`, `tags`, and `observations[]` (types: `GENERATION`, `TOOL`, `CHAIN`, `SPAN`, `AGENT`).

## Workflow

1. **Locate the file** — `read_file` or `glob` under `develop/trace-*.json` if the user did not give a path.
2. **Run the parser** (mandatory first step):

```bash
uv run python skills/analyze-langfuse-trace/scripts/parse_trace.py <path-to-trace.json>
```

For machine-readable output:

```bash
uv run python skills/analyze-langfuse-trace/scripts/parse_trace.py <path> --json
```

3. **Decode user intent** — parser extracts `user_message` from nested JSON in `trace.input`.
4. **Build the timeline** — sort observations by `startTime`; identify the slowest `GENERATION` spans.
5. **Apply Datasyn-specific checks** (see checklist below).
6. **Write the report** using the template in the next section.
7. **Save artifact** (optional) under `reports/trace-analysis/<traceId>_<YYYYMMDD>.md` when the user wants a persistent deliverable.

Do **not** return raw `SKILL.md` or full trace JSON unless explicitly asked.

## Datasyn checklist (heuristics)

| Check | Severity | Signal |
|-------|----------|--------|
| **No subagent delegation** | High | `duckdb_*` / `dagster_*` / `storage_*` in main thread without prior `task` call |
| **Slow generation** | High | `GENERATION` latency > 15s with < 500 output tokens |
| **Large prompt** | Medium | `input` tokens > 15k per generation (~40k-char `AGENTS.md` + orchestrator) |
| **No prompt cache** | Low | `input_cache_read: 0` on large prompts |
| **Locale mismatch** | Medium | Tag `locale:en` but Spanish user message / reply |
| **Thin observability** | Low | `TOOL` spans lack input/output; `toolCalls: null` on generations |
| **Skills middleware** | Info | `SkillsMiddleware.before_agent` present (~ms) |

### Architecture expectation

Per `agent/prompts/supervisor_orchestrator.txt`, substantive turns should:

1. **Not** call MCP tools in the orchestrator thread
2. Spawn **`task(subagent_type="query")`** with the full user goal
3. Synthesize the user reply from the subagent brief

Flag violations explicitly in **Findings**.

### Model / latency

- Default model often routes via LiteLLM (`nvidia/nemotron-3-super-120b-a12b:free` or similar).
- Simple introspection (`get_schema`, list tables) should use a **fast model**; 120B free tier can spend 50s+ on small replies.
- Compare **TTFT** vs total latency: high total with low output tokens → generation speed, not queue time.

## Report template (mandatory output)

```markdown
# Trace analysis: `<traceId>`

## Executive summary
[1–2 sentences: user ask, outcome quality, main bottleneck]

## Metrics

| Metric | Value |
|--------|-------|
| Total latency | …s |
| Generations | n |
| Input / output tokens | … / … |
| Tools called | … |
| Trace tags | … |

## Timeline (high signal)
[Chronological table or bullets: GENERATION + TOOL only]

## What worked
- …

## Findings
- **[severity]** …

## Recommended improvements (prioritized)
| Priority | Change | Expected impact |
|----------|--------|-----------------|
| P0 | … | … |

## Limitations
[What the export cannot show: tool I/O redaction, missing subagent subgraph detail, etc.]
```

Match the user's language in prose (Spanish if they asked in Spanish).

## Parser script reference

`skills/analyze-langfuse-trace/scripts/parse_trace.py` returns:

- `timeline`, `generations`, `tools_called`, `datasyn_checks`
- Token totals and `assistant_reply_preview`

Extend checks in the script when new recurring patterns appear (e.g. Dagster sequence violations, duplicate observations).

## Examples

**User:** `analyze develop/trace-feb34e3f8aa15990d6d09223fbed938b.json`

1. Run parser on that path
2. Note: 56.8s total, 52.6s on second generation, `duckdb_get_schema` only, no `task`
3. Report P0: enforce query subagent; P0: fast model for schema listing; P1: slim orchestrator prompt

**User:** `why was this trace slow?`

Same workflow — always cite **evidence** (latency seconds, token counts, tool names from parser output).

## Anti-patterns

- Guessing tool arguments or model decisions when the export has `toolCalls: null` — say "not recorded in export"
- Treating duplicate top-level `observations` arrays as two runs (dedupe by `id`)
- Proposing fixes without tying them to a trace metric
