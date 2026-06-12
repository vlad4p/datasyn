#!/usr/bin/env python3
"""Parse a Langfuse trace JSON export into a compact analysis summary.

Usage:
  uv run python skills/analyze-langfuse-trace/scripts/parse_trace.py develop/trace-*.json
  uv run python skills/analyze-langfuse-trace/scripts/parse_trace.py path/to/trace.json --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def _load_trace(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    trace = data.get("trace") or data
    observations = trace.get("observations") or data.get("observations") or []
    return {"trace": trace, "observations": observations}


def _decode_nested_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return value
    if isinstance(parsed, str):
        try:
            return json.loads(parsed)
        except json.JSONDecodeError:
            return parsed
    return parsed


def _user_message(trace: dict[str, Any]) -> str:
    raw = _decode_nested_json(trace.get("input"))
    if isinstance(raw, dict):
        return str(raw.get("user_message") or raw.get("message") or "")
    return str(raw or "")


def _assistant_reply(trace: dict[str, Any]) -> str:
    raw = _decode_nested_json(trace.get("output"))
    if isinstance(raw, dict):
        return str(raw.get("assistant_reply") or raw.get("reply") or "")
    return str(raw or "")


def _timeline(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for obs in sorted(observations, key=lambda o: o.get("startTime", "")):
        usage = obs.get("usageDetails") or obs.get("providedUsageDetails") or {}
        rows.append(
            {
                "start": obs.get("startTime"),
                "type": obs.get("type"),
                "name": obs.get("name"),
                "latency_s": obs.get("latency"),
                "model": obs.get("model"),
                "input_tokens": usage.get("input"),
                "output_tokens": usage.get("output"),
                "cache_read": usage.get("input_cache_read"),
                "ttft_s": obs.get("timeToFirstToken"),
                "level": obs.get("level"),
            }
        )
    return rows


def _generations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gens: list[dict[str, Any]] = []
    for obs in observations:
        if obs.get("type") != "GENERATION":
            continue
        usage = obs.get("usageDetails") or obs.get("providedUsageDetails") or {}
        gens.append(
            {
                "start": obs.get("startTime"),
                "latency_s": obs.get("latency"),
                "model": obs.get("model"),
                "input_tokens": usage.get("input"),
                "output_tokens": usage.get("output"),
                "cache_read": usage.get("input_cache_read"),
                "ttft_s": obs.get("timeToFirstToken"),
            }
        )
    return sorted(gens, key=lambda g: g.get("start") or "")


def _tools(observations: list[dict[str, Any]]) -> list[str]:
    return [
        o.get("name", "")
        for o in sorted(observations, key=lambda x: x.get("startTime", ""))
        if o.get("type") == "TOOL" and o.get("name")
    ]


def _datasyn_checks(trace: dict[str, Any], observations: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Heuristic flags for Datasyn brain traces."""
    checks: list[dict[str, str]] = []
    tools = _tools(observations)
    tags = trace.get("tags") or []
    gens = _generations(observations)

    if "task" not in tools and any(t.startswith(("duckdb_", "dagster_", "storage_")) for t in tools):
        checks.append(
            {
                "severity": "high",
                "code": "no_subagent_delegation",
                "detail": "MCP tools ran in the main thread; expected `task(subagent_type=\"query\")` first.",
            }
        )

    if "task" in tools:
        checks.append(
            {
                "severity": "ok",
                "code": "subagent_used",
                "detail": "`task` tool was invoked.",
            }
        )

    locale_tags = [t for t in tags if str(t).startswith("locale:")]
    user_msg = _user_message(trace)
    if locale_tags and locale_tags[0] == "locale:en" and any(
        w in user_msg.lower() for w in ("dame", "listado", "tablas", "análisis", "análisis", "qué", "cuál")
    ):
        checks.append(
            {
                "severity": "medium",
                "code": "locale_mismatch",
                "detail": f"Trace tagged {locale_tags[0]} but user message looks Spanish.",
            }
        )

    for i, g in enumerate(gens, start=1):
        lat = float(g.get("latency_s") or 0)
        out_tok = int(g.get("output_tokens") or 0)
        if lat > 15 and out_tok < 500:
            checks.append(
                {
                    "severity": "high",
                    "code": "slow_generation",
                    "detail": f"Gen {i}: {lat:.1f}s for {out_tok} output tokens (model={g.get('model')}).",
                }
            )
        inp = int(g.get("input_tokens") or 0)
        if inp > 15000:
            checks.append(
                {
                    "severity": "medium",
                    "code": "large_prompt",
                    "detail": f"Gen {i}: {inp} input tokens — review AGENTS.md / orchestrator prompt size.",
                }
            )
        if int(g.get("cache_read") or 0) == 0 and inp > 10000:
            checks.append(
                {
                    "severity": "low",
                    "code": "no_prompt_cache",
                    "detail": f"Gen {i}: input_cache_read=0 with large prompt.",
                }
            )

    if not any(o.get("name") == "SkillsMiddleware.before_agent" for o in observations):
        checks.append(
            {
                "severity": "low",
                "code": "skills_middleware_missing",
                "detail": "No SkillsMiddleware span — skills may not have loaded.",
            }
        )

    return checks


def analyze(path: Path) -> dict[str, Any]:
    loaded = _load_trace(path)
    trace = loaded["trace"]
    observations = loaded["observations"]
    gens = _generations(observations)

    total_in = sum(int(g.get("input_tokens") or 0) for g in gens)
    total_out = sum(int(g.get("output_tokens") or 0) for g in gens)

    by_type: dict[str, int] = defaultdict(int)
    for o in observations:
        by_type[str(o.get("type") or "unknown")] += 1

    return {
        "file": str(path),
        "trace_id": trace.get("id"),
        "name": trace.get("name"),
        "latency_s": trace.get("latency"),
        "environment": trace.get("environment"),
        "tags": trace.get("tags") or [],
        "user_message": _user_message(trace),
        "assistant_reply_preview": (_assistant_reply(trace) or "")[:500],
        "generation_count": len(gens),
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "tools_called": _tools(observations),
        "observation_counts": dict(sorted(by_type.items())),
        "generations": gens,
        "timeline": _timeline(observations),
        "datasyn_checks": _datasyn_checks(trace, observations),
    }


def _format_text(report: dict[str, Any]) -> str:
    lines = [
        f"Trace: {report.get('trace_id')} ({report.get('name')})",
        f"File: {report.get('file')}",
        f"Latency: {report.get('latency_s')}s | Env: {report.get('environment')}",
        f"Tags: {', '.join(report.get('tags') or [])}",
        "",
        f"User: {report.get('user_message')}",
        "",
        "Generations:",
    ]
    for i, g in enumerate(report.get("generations") or [], start=1):
        lines.append(
            f"  {i}. {g.get('latency_s')}s | in={g.get('input_tokens')} out={g.get('output_tokens')} "
            f"cache={g.get('cache_read')} ttft={g.get('ttft_s')}s | {g.get('model')}"
        )
    lines.extend(
        [
            "",
            f"Tools: {', '.join(report.get('tools_called') or []) or '(none)'}",
            f"Token totals: in={report.get('total_input_tokens')} out={report.get('total_output_tokens')}",
            "",
            "Datasyn checks:",
        ]
    )
    for check in report.get("datasyn_checks") or []:
        lines.append(f"  [{check.get('severity')}] {check.get('code')}: {check.get('detail')}")
    lines.extend(["", "Timeline:"])
    for row in report.get("timeline") or []:
        extra = ""
        if row.get("input_tokens"):
            extra = f" in={row['input_tokens']} out={row.get('output_tokens')}"
        if row.get("model"):
            extra += f" model={row['model']}"
        lat = row.get("latency_s")
        lat_s = f"{lat:>7}" if lat is not None else "    n/a"
        lines.append(
            f"  {row.get('start')} | {row.get('type'):10} | {lat_s}s | "
            f"{row.get('name')}{extra}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse Langfuse trace JSON for Datasyn analysis.")
    parser.add_argument("trace_file", type=Path, help="Path to trace JSON export")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = parser.parse_args(argv)

    if not args.trace_file.is_file():
        print(f"Error: file not found: {args.trace_file}", file=sys.stderr)
        return 1

    report = analyze(args.trace_file)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(_format_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
