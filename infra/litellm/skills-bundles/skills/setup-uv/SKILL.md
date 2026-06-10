---
name: setup-uv
description: >-
  Set up and manage the uv virtual environment for datasyn-local.
  Use when the user asks to install dependencies, create venv, sync packages,
  or configure Python with uv.
---

# Setup uv Virtual Environment

## Install uv (if missing)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Or: `brew install uv` (macOS)

## Project setup

From repository root:

```bash
uv sync --all-extras
```

This reads `pyproject.toml` and creates `.venv/` in the project.

## Daily commands

```bash
uv run python scripts/python/db.py info
uv run ipython
uv add pandas
uv add --dev pytest
uv sync
```

## Verify

```bash
uv run python -c "import duckdb; print(duckdb.__version__)"
uv run python scripts/python/db.py info
```

## Environment variables

```bash
cp .env.example .env
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `uv: command not found` | Reinstall uv, restart shell |
| Wrong Python version | `uv python install 3.11 && uv sync` |
| Import errors | Run from project root; use `uv run` |
| Stale venv | `rm -rf .venv && uv sync` |
