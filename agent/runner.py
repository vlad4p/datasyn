"""CLI runner for the Deep Agent (remote HTTP tool servers → LangChain tools)."""

from __future__ import annotations

import argparse
import asyncio
import sys

from agent.utils.agent_chat import run_agent_chat_turn


async def _arun(message: str) -> str:
    return (await run_agent_chat_turn(message)).reply


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Data & AI Deep Agent once.")
    parser.add_argument("message", nargs="?", help="User message / task description")
    args = parser.parse_args(argv)
    text = args.message or sys.stdin.read().strip()
    if not text:
        print("Provide a message argument or stdin.", file=sys.stderr)
        return 2

    out = asyncio.run(_arun(text))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
