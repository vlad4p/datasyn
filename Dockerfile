# Datasyn brain: FastAPI + Deep Agents (FilesystemBackend, remote tools via mcp.json).
FROM python:3.12-slim-bookworm

# Install dependencies with uv (requirements.txt is generated via `uv export`, see header in that file).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /project

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Baked image layout (skills + agent code ship in the image for VM deploy).
COPY deepagents.toml mcp.json AGENTS.md /project/
COPY agent/ /project/agent/
COPY skills/ /project/skills/

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/project \
    PROJECT_ROOT=/project \
    REPORTS_DIR=/project/reports \
    INBOX_DIR=/project/inbox \
    JOBS_DIR=/project/tmp/process_jobs

EXPOSE 8000

# uvicorn on PATH after `uv pip install --system` (see requirements.txt / uv export)
CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
