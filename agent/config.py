"""Runtime configuration from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Resolve repo root (…/agent/config.py → project root), not CWD — so uvicorn from another cwd still loads `.env`.
# `override=True` so a stale shell `export LITELLM_KEY=...` cannot shadow the file (common 401 cause).
# Directory that contains the ``agent/`` package (repository root when running from this tree).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_env_file = _REPO_ROOT / ".env"
# Read by ``GET /health`` → ``pipeline.brain.dotenv`` (no secrets).
ENV_DOTENV_RESOLVED_PATH = str(_env_file.resolve())
ENV_DOTENV_LOADED_AT_IMPORT = _env_file.is_file()
if ENV_DOTENV_LOADED_AT_IMPORT:
    load_dotenv(_env_file, override=True)


def _path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser().resolve()


def _env_first(*names: str) -> str | None:
    """First non-empty env value (Datacyber-style aliases for LiteLLM key/base)."""
    for n in names:
        v = os.environ.get(n)
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


def _normalize_litellm_base(url: str) -> str:
    """OpenAI-compatible clients expect ``base_url`` to end with ``/v1`` (like ``https://api.openai.com/v1``).

    Accepts ``http://host:4000`` and normalizes to ``http://host:4000/v1``.
    """
    u = url.strip().rstrip("/")
    if not u:
        return u
    if "/v1" not in u:
        u = f"{u}/v1"
    return u


def _rewrite_all_interfaces_litellm_host(url: str) -> str:
    """``0.0.0.0`` is valid for *listening* but not as a destination; outbound HTTP to it fails.

    Map to loopback so ``LITELLM_*_BASE=http://0.0.0.0:4000`` works like ``127.0.0.1:4000``.
    """
    if not url or "0.0.0.0" not in url:
        return url
    return url.replace("0.0.0.0", "127.0.0.1")


def _rewrite_litellm_host_for_docker(url: str) -> str:
    """Inside Docker, ``localhost`` / ``127.0.0.1`` is the container, not the host running LiteLLM.

    Rewrites to ``host.docker.internal`` (requires ``extra_hosts`` on Linux — see docker-compose).
    Set ``LITELLM_DOCKER_HOST_REWRITE=0`` to disable.
    """
    if not url:
        return url
    if os.environ.get("LITELLM_DOCKER_HOST_REWRITE", "1").strip().lower() in (
        "0",
        "false",
        "no",
    ):
        return url
    in_docker = os.path.exists("/.dockerenv")
    if not in_docker:
        return url
    if "localhost" not in url and "127.0.0.1" not in url:
        return url
    u = url.replace("127.0.0.1", "host.docker.internal")
    return u.replace("localhost", "host.docker.internal")


def _model_provider() -> str:
    """LLM backend: ``litellm``, ``openrouter`` (direct OpenRouter API), or ``gemini``."""
    raw = (os.environ.get("MODEL_PROVIDER") or "litellm").strip().lower()
    if raw in ("or", "openrouter"):
        return "openrouter"
    if raw in ("litellm", "gemini"):
        return raw
    raise ValueError(
        f"MODEL_PROVIDER must be 'litellm', 'openrouter', or 'gemini', got {raw!r}"
    )


def _gemini_api_key() -> str | None:
    return _env_first("GEMINI_API_KEY", "GOOGLE_API_KEY")


def _cors_extra_origins() -> tuple[str, ...]:
    """Comma-separated extra browser origins for the FastAPI brain (e.g. Vite on LAN IP)."""
    raw = os.environ.get("CORS_EXTRA_ORIGINS", "").strip()
    if not raw:
        return ()
    return tuple(x.strip() for x in raw.split(",") if x.strip())


def _litellm_base_from_env() -> str | None:
    raw = _env_first(
        "LITELLM_API_BASE",
        "LITELLM_PROXY_BASE",
        "LITELLM_URL",
    )
    if not raw:
        return None
    normalized = _normalize_litellm_base(raw)
    normalized = _rewrite_all_interfaces_litellm_host(normalized)
    return _rewrite_litellm_host_for_docker(normalized)


OPENROUTER_DEFAULT_API_BASE = "https://openrouter.ai/api/v1"


def _openrouter_base_from_env() -> str | None:
    """OpenRouter OpenAI-compatible root (typically ``…/api/v1``)."""
    raw = _env_first("OPENROUTER_BASE_URL")
    if not raw:
        return None
    normalized = _normalize_litellm_base(raw)
    normalized = _rewrite_all_interfaces_litellm_host(normalized)
    return _rewrite_litellm_host_for_docker(normalized)


@dataclass(frozen=True)
class Settings:
    project_root: Path
    reports_dir: Path
    inbox_dir: Path
    jobs_dir: Path
    model_provider: str
    chat_model: str | None
    litellm_key: str | None
    litellm_api_base: str | None
    openrouter_api_key: str | None
    openrouter_api_base: str | None
    gemini_api_key: str | None
    duckdb_path_in_process: str
    sql_row_cap: int
    warehouse_api_url: str
    api_host: str
    api_port: int
    cors_extra_origins: tuple[str, ...]
    pipeline_debug: bool

    @classmethod
    def load(cls) -> Settings:
        project_root = _path("PROJECT_ROOT", ".")
        return cls(
            project_root=project_root,
            reports_dir=_path("REPORTS_DIR", str(project_root / "reports")),
            inbox_dir=_path("INBOX_DIR", str(project_root / "inbox")),
            jobs_dir=_path("JOBS_DIR", str(project_root / "tmp" / "process_jobs")),
            model_provider=_model_provider(),
            chat_model=((os.environ.get("CHAT_MODEL") or "").strip() or None),
            litellm_key=_env_first("LITELLM_KEY", "LITELLM_PROXY_KEY"),
            litellm_api_base=_litellm_base_from_env(),
            openrouter_api_key=_env_first("OPENROUTER_API_KEY", "OPENROUTER_KEY"),
            openrouter_api_base=_openrouter_base_from_env(),
            gemini_api_key=_gemini_api_key(),
            duckdb_path_in_process=os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb"),
            sql_row_cap=int(os.environ.get("SQL_ROW_CAP", "500")),
            warehouse_api_url=os.environ.get("WAREHOUSE_API_URL", "http://127.0.0.1:8080"),
            api_host=os.environ.get("API_HOST", "0.0.0.0"),
            api_port=int(os.environ.get("API_PORT", "8000")),
            cors_extra_origins=_cors_extra_origins(),
            pipeline_debug=os.environ.get("DATACYBER_PIPELINE_DEBUG", "")
            .strip()
            .lower()
            in ("1", "true", "yes"),
        )


settings = Settings.load()
