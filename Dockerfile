# Datacyber brain: FastAPI + Deep Agents (FilesystemBackend, remote tools via tool_servers.json).
FROM python:3.12-slim-bookworm

# Install dependencies with uv (requirements.txt is generated via `uv export`, see header in that file).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /project

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt \
    && rm -f /usr/local/bin/uv

# Baked image layout (dev Compose still bind-mounts the repo over /project).
COPY deepagents.toml tool_servers.json AGENTS.md /project/
COPY agent/ /project/agent/

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/project \
    PROJECT_ROOT=/project \
    REPORTS_DIR=/project/reports \
    INBOX_DIR=/project/inbox \
    JOBS_DIR=/project/tmp/process_jobs

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
