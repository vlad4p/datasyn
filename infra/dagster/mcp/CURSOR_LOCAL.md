# Cursor + local dagster-mcp (HTTP)

This MCP serves **Streamable HTTP** on **`http://127.0.0.1:8043/mcp`** (not stdio). Cursor connects with a **remote** `url` entry; keep the container (or `python server.py`) running while you use the agent.

## 1. Start the server (Docker)

From the repo root:

```bash
chmod +x infra/dagster/mcp/scripts/run-dagster-mcp-local-docker.sh
./infra/dagster/mcp/scripts/run-dagster-mcp-local-docker.sh
```

Requires Docker network **`infra-datasynk`**:

```bash
docker network create infra-datasynk 2>/dev/null || true
```

Stop: Ctrl+C (container is `--rm`).

## 2. Cursor `~/.cursor/mcp.json`

Add (or keep) a server that points at localhost:

```json
"dagster-local": {
  "type": "remote",
  "url": "http://127.0.0.1:8043/mcp",
  "enabled": true
}
```

Reload MCP / restart Cursor after editing.

## 3. Developing Python without rebuilding every time

Run from the host inside a venv (same port):

```bash
cd infra/dagster/mcp
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DAGSTER_PROJECTS_ROOT="${PWD}/dagster-code/projects"
export DAGSTER_COMPOSE_FILE="${PWD}/../docker-compose.yaml"
python server.py
```

Ensure nothing else is bound to **8043**.

## Note on “docker MCP” in Cursor

Cursor’s **`command` + `docker` + `-i`** pattern is for **stdio** MCP servers. This stack uses **HTTP** (`FastMCP` + `transport="http"`), so use **`url`** to `127.0.0.1:8043`, not a stdio docker wrapper.
