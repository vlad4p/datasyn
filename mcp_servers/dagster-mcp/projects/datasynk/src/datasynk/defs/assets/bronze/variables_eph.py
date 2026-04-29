"""EPH variable dictionary PDF → LiteLLM vision → bronze table."""

from __future__ import annotations

import base64
import json
import os
import re
import time
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dagster import MaterializeResult, asset
from dagster_duckdb import DuckDBResource

from ..._eph_year_discovery import EPH_VARIABLES_REGISTER_BASENAME, eph_variables_pdf_path

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None  # type: ignore[misc, assignment]

SCHEMA = "bronze"
TABLE = f"{SCHEMA}.indec_mercado_laboral_variables"
PDF_BASENAME = EPH_VARIABLES_REGISTER_BASENAME
DEFAULT_MODEL = "local/gemini-3.1-pro-preview"
logger = logging.getLogger(__name__)


def _duckdb_path() -> str:
    return os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb").strip()


def _resolve_path(p: Path) -> Path:
    try:
        return p.resolve(strict=False)
    except TypeError:  # pragma: no cover
        return p.resolve()


def _pdf_path_candidates() -> list[Path]:
    candidates: list[Path] = [eph_variables_pdf_path()]
    roots: list[Path] = []
    dlr = (os.environ.get("DATA_LOCAL_ROOT") or "").strip()
    if dlr:
        roots.append(Path(dlr).expanduser())
    roots.append(Path("/data-local"))
    for root in roots:
        candidates.append(_resolve_path(root / "indec" / "pdf-variables" / PDF_BASENAME))

    duck = Path(_duckdb_path()).expanduser()
    candidates.append(
        _resolve_path(duck.parent / "data-local" / "indec" / "pdf-variables" / PDF_BASENAME)
    )
    seen: set[str] = set()
    out: list[Path] = []
    for p in candidates:
        key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _pdf_path() -> Path:
    explicit = (os.environ.get("INDEC_EPH_VARIABLES_PDF") or "").strip()
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if p.is_file():
            return p
        raise FileNotFoundError(f"PDF not found: {p} (INDEC_EPH_VARIABLES_PDF)")
    tried = _pdf_path_candidates()
    for p in tried:
        if p.is_file():
            return p
    raise FileNotFoundError("PDF not found. Tried:\n  - " + "\n  - ".join(str(x) for x in tried))


def _page_range() -> tuple[int, int]:
    start = int(os.environ.get("INDEC_EPH_VARIABLES_PAGE_START", "5"))
    end = int(os.environ.get("INDEC_EPH_VARIABLES_PAGE_END", "35"))
    if start < 1:
        start = 1
    if end < start:
        end = start
    return start, end


def _page_delay_seconds() -> float:
    return max(0.0, float(os.environ.get("INDEC_EPH_VARIABLES_PAGE_DELAY", "1")))


def _processed_log_path(pdf: Path) -> Path:
    raw = (os.environ.get("INDEC_EPH_VARIABLES_LOG") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    next_to_pdf = (pdf.parent / "log_processed_file.txt").resolve()
    if os.access(str(next_to_pdf.parent), os.W_OK):
        return next_to_pdf
    duck = Path(_duckdb_path()).expanduser()
    return (duck.parent / "dagster_logs" / "indec_mercado_laboral" / f"{pdf.stem}.processed.log").resolve()


def _append_log_line(log_path: Path, line: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")
        f.flush()


def _litellm_key() -> str:
    return (os.environ.get("LITELLM_KEY") or os.environ.get("LITELLM_PROXY_KEY") or "").strip()


def _litellm_base() -> str:
    raw = (
        os.environ.get("LITELLM_API_BASE")
        or os.environ.get("LITELLM_PROXY_BASE")
        or os.environ.get("LITELLM_URL")
        or "http://host.docker.internal:4000"
    ).strip().rstrip("/")
    if not raw:
        raw = "http://host.docker.internal:4000"
    if "0.0.0.0" in raw:
        raw = raw.replace("0.0.0.0", "127.0.0.1")
    if os.path.exists("/.dockerenv") and ("127.0.0.1" in raw or "localhost" in raw):
        raw = raw.replace("127.0.0.1", "host.docker.internal").replace("localhost", "host.docker.internal")
    if "/v1" not in raw:
        raw = f"{raw}/v1"
    return raw


def _model_id() -> str:
    # Keep compatibility with existing project env files that define CHAT_MODEL.
    return (os.environ.get("LITELLM_VARIABLES_MODEL") or os.environ.get("CHAT_MODEL") or DEFAULT_MODEL).strip()


def _litellm_max_retries() -> int:
    return max(0, int(os.environ.get("LITELLM_VARIABLES_MAX_RETRIES", "3")))


def _litellm_retry_base_seconds() -> float:
    return max(0.0, float(os.environ.get("LITELLM_VARIABLES_RETRY_BASE_SECONDS", "1.5")))


def _langfuse_enabled() -> bool:
    pub = (os.environ.get("LANGFUSE_PUBLIC_KEY") or "").strip()
    sec = (os.environ.get("LANGFUSE_SECRET_KEY") or "").strip()
    return bool(pub and sec)


def _langfuse_client() -> Any | None:
    if not _langfuse_enabled():
        return None
    try:
        from langfuse import get_client

        return get_client()
    except Exception as exc:  # pragma: no cover
        logger.warning("Langfuse client unavailable: %s: %s", type(exc).__name__, exc)
        return None


def _looks_vision_capable(model: str) -> bool:
    m = (model or "").strip().lower()
    if not m:
        return False
    # Fast-fail only for known non-vision families we have hit in this project.
    if "gpt-3.5" in m:
        return False
    if "vision" in m or "gemini" in m or "gpt-4o" in m or "o4" in m or "claude-3" in m:
        return True
    # Unknown aliases may still be valid behind LiteLLM; do not block them.
    return True


def _render_page_png(pdf: Path, page_index: int, zoom: float = 2.0) -> bytes:
    if fitz is None:
        raise RuntimeError("PyMuPDF (pymupdf) is required to rasterize PDF pages.")
    doc = fitz.open(pdf)
    try:
        page = doc[page_index]
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def _parse_variables_json(text: str) -> list[dict[str, Any]]:
    t = (text or "").strip()
    if not t:
        return []
    m = _JSON_FENCE.search(t)
    if m:
        t = m.group(1).strip()
    try:
        data = json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end > start:
            data = json.loads(t[start : end + 1])
        else:
            return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        vars_ = data.get("variables")
        if isinstance(vars_, list):
            return [x for x in vars_ if isinstance(x, dict)]
    return []


def _call_litellm_vision(*, png_bytes: bytes, page_number: int, model: str, base: str, api_key: str) -> list[dict[str, Any]]:
    b64 = base64.standard_b64encode(png_bytes).decode("ascii")
    url = f"{base.rstrip('/')}/chat/completions"
    instructions = (
        "Analiza este documento técnico del INDEC."
        "Busca las secciones de 'Registro de la base de datos'."
        "Extrae CADA columna en una lista JSON de objetos con campos: campo, longitud, tipo, descripcion, notas. "
        "Devuelve ÚNICAMENTE JSON válido: {\"variables\":[...]}. Si no hay variables, usa {\"variables\":[]}."
    )
    body: dict[str, Any] = {
        "model": model,
        "temperature": 0.0,
        "max_tokens": 8192,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"{instructions}\n(Page index in file: {page_number}.)"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"}},
                ],
            }
        ],
    }
    timeout = float(os.environ.get("LITELLM_VARIABLES_HTTP_TIMEOUT", "180"))
    max_retries = _litellm_max_retries()
    retry_base = _litellm_retry_base_seconds()
    r: httpx.Response | None = None
    with httpx.Client(timeout=timeout) as client:
        for attempt in range(max_retries + 1):
            try:
                r = client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=body,
                )
                if r.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    time.sleep(retry_base * (2**attempt))
                    continue
                r.raise_for_status()
                break
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as e:
                if attempt < max_retries:
                    time.sleep(retry_base * (2**attempt))
                    continue
                response_preview = ""
                if isinstance(e, httpx.HTTPStatusError) and e.response is not None:
                    response_preview = (e.response.text or "").strip()
                if len(response_preview) > 1200:
                    response_preview = response_preview[:1200] + "...<truncated>"
                raise RuntimeError(
                    "LiteLLM vision request failed "
                    f"(model={model}, page={page_number}, url={url}, retries={max_retries}). "
                    f"Error: {type(e).__name__}: {e}. "
                    f"Response body: {response_preview or '<empty>'}"
                ) from e
    if r is None:
        raise RuntimeError(
            f"LiteLLM vision request produced no response (model={model}, page={page_number}, url={url})"
        )
    payload = r.json()
    choices = payload.get("choices") or []
    if not choices:
        return []
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if isinstance(content, list):
        parts = [str(block.get("text", "")) for block in content if isinstance(block, dict) and block.get("type") == "text"]
        text = "\n".join(parts)
    else:
        text = str(content or "")
    return _parse_variables_json(text)


@asset(
    name="variables_eph",
    group_name="indec_mercado_laboral",
    description=(
        "Rasterize PDF pages (INDEC EPH variable register), call LiteLLM vision model "
        f"(default ``{DEFAULT_MODEL}``), and upsert rows into ``{TABLE}`` as JSON."
    ),
)
def variables_eph(context, database: DuckDBResource) -> MaterializeResult:
    pdf = _pdf_path()
    key = _litellm_key()
    if not key:
        raise RuntimeError("Set LITELLM_KEY or LITELLM_PROXY_KEY in the user-code environment.")
    base = _litellm_base()
    model = _model_id()
    if not _looks_vision_capable(model):
        raise RuntimeError(
            f"Model '{model}' is not vision-capable for variables_eph (image_url payload). "
            "Set LITELLM_VARIABLES_MODEL (or CHAT_MODEL) to a vision model alias available in LiteLLM "
            "(for example local/gemini-3.1-pro-preview)."
        )
    start_1, end_1 = _page_range()
    i0 = max(4, start_1 - 1)
    i1 = max(i0, end_1 - 1)
    doc = fitz.open(pdf) if fitz else None
    if doc is None:
        raise RuntimeError("PyMuPDF (pymupdf) is not installed.")
    try:
        n_pages = len(doc)
    finally:
        doc.close()
    i1 = min(i1, n_pages - 1)
    log_path = _processed_log_path(pdf)
    delay_s = _page_delay_seconds()
    duck = _duckdb_path()
    rows_written = 0
    pages_failed = 0
    lf = _langfuse_client()
    lf_root = None
    if lf is not None:
        try:
            lf_root = lf.start_as_current_observation(
                as_type="span",
                name="datasynk.variables_eph",
                input={
                    "source_pdf": str(pdf),
                    "page_range": f"{start_1}-{end_1}",
                    "model_id": model,
                    "litellm_base": base,
                },
            )
            lf_root.__enter__()
        except Exception as exc:  # pragma: no cover
            logger.warning("Langfuse root span failed: %s: %s", type(exc).__name__, exc)
            lf_root = None
    with database.get_connection() as con:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        con.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                page_number INTEGER NOT NULL,
                variables JSON NOT NULL,
                source_pdf VARCHAR NOT NULL,
                model_id VARCHAR NOT NULL,
                extracted_at TIMESTAMP NOT NULL,
                PRIMARY KEY (source_pdf, page_number)
            )
            """
        )
        src = str(pdf)
        con.execute(f"DELETE FROM {TABLE} WHERE source_pdf = ?", [src])
        extracted_at = datetime.now(UTC).replace(tzinfo=None)
        _append_log_line(
            log_path,
            f"# variables_eph start ts={extracted_at.isoformat()}Z pdf={src} pages={start_1}-{end_1} model={model}",
        )
        for page_idx in range(i0, i1 + 1):
            page_display = page_idx + 1
            lf_page = None
            if lf_root is not None:
                try:
                    lf_page = lf.start_as_current_observation(
                        as_type="span",
                        name="datasynk.variables_eph.page",
                        input={"page_number": page_display, "source_pdf": src, "model_id": model},
                    )
                    lf_page.__enter__()
                except Exception:  # pragma: no cover
                    lf_page = None
            try:
                png = _render_page_png(pdf, page_idx)
                vars_list = _call_litellm_vision(
                    png_bytes=png,
                    page_number=page_display,
                    model=model,
                    base=base,
                    api_key=key,
                )
            except Exception as exc:
                pages_failed += 1
                context.log.error(
                    "variables_eph page=%s failed: %s: %s",
                    page_display,
                    type(exc).__name__,
                    exc,
                )
                _append_log_line(
                    log_path,
                    f"{datetime.now(UTC).replace(tzinfo=None).isoformat()}Z\tpage={page_display}\terror={type(exc).__name__}:{exc}",
                )
                vars_list = []
                if lf_page is not None:
                    try:
                        lf_page.__exit__(type(exc), exc, exc.__traceback__)
                    except Exception:
                        pass
                    lf_page = None
            con.execute(
                f"INSERT INTO {TABLE} (page_number, variables, source_pdf, model_id, extracted_at) VALUES (?, ?, ?, ?, ?)",
                [page_display, json.dumps(vars_list), src, model, extracted_at],
            )
            rows_written += 1
            _append_log_line(
                log_path,
                f"{datetime.now(UTC).replace(tzinfo=None).isoformat()}Z\tpage={page_display}\tvariables={len(vars_list)}\tduckdb=inserted",
            )
            if lf_page is not None:
                try:
                    lf_page.__exit__(None, None, None)
                except Exception:
                    pass
            if page_idx < i1 and delay_s > 0:
                time.sleep(delay_s)
    _append_log_line(
        log_path,
        f"# variables_eph end ts={datetime.now(UTC).replace(tzinfo=None).isoformat()}Z pages_written={rows_written}",
    )
    if lf_root is not None:
        try:
            lf_root.__exit__(None, None, None)
            lf.flush()
        except Exception:
            pass
    return MaterializeResult(
        metadata={
            "duckdb_path": duck,
            "table": TABLE,
            "source_pdf": str(pdf),
            "pages": f"{start_1}-{end_1} (0-based indices {i0}-{i1})",
            "model_id": model,
            "litellm_base": base,
            "rows_pages": rows_written,
            "pages_failed": pages_failed,
            "processed_log": str(log_path),
            "page_delay_seconds": delay_s,
        }
    )


def build_variables_eph_assets():
    return [variables_eph]
