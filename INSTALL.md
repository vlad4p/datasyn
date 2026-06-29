# INSTALL — DataSyn

Deploy the **brain** (FastAPI agent) and **UI** (React).

- [`README.md`](README.md) — overview
- [`AGENTS.md`](AGENTS.md) — agent contract

Platform services (LiteLLM, MCP, Dagster) run separately — configure in `.env` and `mcp.json`.

---

## Deploy workflow

| Role | Location | Commands |
|------|----------|----------|
| **Build machine** | Git clone | `make build-agent` · `make build-ui` · `make push` |
| **VM** | `docker-compose.yaml` + `.env` only | `docker compose pull` → `docker compose up -d` |

Do **not** clone this repo on the VM. Copy [`docker-compose.yaml`](docker-compose.yaml) and `.env` to the server.

---

## 1. Build machine

```bash
git clone …/datasyn.git && cd datasyn
cp .env.example .env
```

Set registry in `.env`:

```bash
DATASYN_IMAGE_REGISTRY=localhost:5000    # or registry.example.com:5000
```

```bash
make build-agent
make build-ui
make push                  # both
make push agent            # brain only
make push ui               # ui only
```

---

## 2. VM

```bash
mkdir -p /opt/datasyn && cd /opt/datasyn
# copy docker-compose.yaml + .env.example → .env from build machine
```

Edit `.env` for the VM:

```bash
DATASYN_IMAGE_REGISTRY=registry.example.com:5000
LITELLM_PROXY_BASE=http://host.docker.internal:4000
DAGSTER_URL=http://host.docker.internal:3001
```

```bash
docker compose pull
docker compose up -d
```

| Service | URL |
|---------|-----|
| Brain | http://&lt;vm-host&gt;:8002 |
| UI | http://&lt;vm-host&gt;:8003 |

---

## Host development

```bash
cp .env.example .env
cp mcp.json.example mcp.json
make uv-sync && make ui-install
make agent-dev
```

| What | URL |
|------|-----|
| UI (Vite) | http://127.0.0.1:5173 |
| Brain | http://127.0.0.1:8002 |

---

## Configuration (`.env`)

Single template: [`.env.example`](.env.example) → copy to `.env` (gitignored).

| Variable | Purpose |
|----------|---------|
| `DATASYN_IMAGE_REGISTRY` | Registry for `make push` and VM `pull` |
| `DATASYN_IMAGE_NAMESPACE` | Default `datasyn` |
| `DATASYN_IMAGE_TAG` | Default `latest` |
| `LITELLM_PROXY_BASE` | Host: `127.0.0.1:4000`; Docker/VM: `host.docker.internal:4000` |
| `DAGSTER_URL` | Host: `127.0.0.1:3001`; Docker/VM: `host.docker.internal:3001` |

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `make push` fails | Set `DATASYN_IMAGE_REGISTRY` in `.env` |
| VM pull 404 | Registry/tag must match `make print-images` |
| LiteLLM unreachable in Docker | `LITELLM_PROXY_BASE=http://host.docker.internal:4000` |
