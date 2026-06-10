"""CLI: ``uv run skills-sync push|pull|list``."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from agent.skills.config import skills_settings
from agent.skills.discovery import discover_skills
from agent.skills.resolver import resolve_skills_root
from agent.skills.sync import pull_skills_from_litellm, push_skills_to_litellm


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Sync Datasyn agent skills with LiteLLM Skills Gateway")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List skills in the active local directory")
    sub.add_parser("pull", help="Download skills bundle from LiteLLM into cache")
    sub.add_parser("push", help="Publish ./skills to LiteLLM Skills Gateway")

    args = parser.parse_args()
    cfg = skills_settings

    if args.command == "list":
        root = resolve_skills_root(cfg=cfg)
        names = discover_skills(root)
        print(json.dumps({"source": cfg.source, "root": str(root), "skills": names}, indent=2))
        return

    if args.command == "pull":
        result = pull_skills_from_litellm(cfg=cfg)
        print(json.dumps(result, indent=2))
        return

    if args.command == "push":
        result = push_skills_to_litellm(cfg=cfg)
        print(json.dumps(result, indent=2))
        return

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
