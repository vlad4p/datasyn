"""Bronze: INDEC EPH ``registro`` PDF variables via one LiteLLM extraction."""

from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from dagster import MaterializeResult, MetadataValue, asset
from dagster_duckdb import DuckDBResource

from datasyn.assets.bronze.indec_eph.indec_eph_trimestral_lib import (
    EmitFn,
    LANDING_SUBDIR,
    _emit,
    data_local_root,
    sync_tree_to_minio,
)
from datasyn.utils.iceberg import materialize_rows

SOURCE_PAGE = "https://www.indec.gob.ar/indec/web/Institucional-Indec-BasesDeDatos"
FTP_ROOT = "https://www.indec.gob.ar/ftp/cuadros/menusuperior/eph/"
BRONZE_SCHEMA = "bronze"
TABLE_VARIABLES = "indec_eph_variables"
DEFAULT_MODEL = "gemini/gemini-3.1-flash-lite-preview"
VARIABLES_SUBDIR = LANDING_SUBDIR / "variables"

EXTRACT_PROMPT = """\
Eres un asistente que lee el PDF "Diseño de Registro" de INDEC EPH (Encuesta Permanente
de Hogares) y devuelve TODAS las variables documentadas en él, en un único JSON.

El PDF tiene dos secciones de variables:
1. Variables del registro **hogar**.
2. Variables del registro **individual**.

Y al final un **anexo** con notas técnicas que debes sintetizar en español.

Cada fila en las tablas de variables tiene cuatro columnas:
- ``campo``: nombre exacto en mayúsculas.
- ``tipo``: una sola letra (``N`` numérico, ``C`` carácter, ``D`` fecha).
- ``longitud``: entero entre paréntesis.
- ``descripcion``: texto descriptivo y enumeraciones de valores si aparecen.

Reglas estrictas:
1. Devuelve EXCLUSIVAMENTE JSON válido (sin comentarios, sin markdown, sin ```).
2. Estructura EXACTA:
   {
     "hogar": [
       {"campo": "STR", "tipo": "C|N|D", "longitud": INT, "descripcion": "STR", "pagina": INT},
       ...
     ],
     "individual": [ {"campo": "...", "tipo": "...", "longitud": INT, "descripcion": "...", "pagina": INT}, ... ],
     "anexo_summary": "RESUMEN_EN_ESPAÑOL"
   }
3. ``pagina`` es el número de página del PDF (1-based); si no puedes determinarla, usa 0.
4. NO inventes variables e incluye solo las que aparecen literalmente.
5. NO repitas una misma ``campo`` dentro de la misma sección.
6. ``anexo_summary``: resumen conciso (<= 2000 caracteres) en español.
"""


@dataclass(frozen=True)
class VariableRow:
    campo: str
    tipo: str
    longitud: int
    descripcion: str
    registro_base: str
    pagina: int
    year: int
    quarter: int

    def as_tuple(self) -> tuple:
        return (
            self.campo,
            self.tipo,
            self.longitud,
            self.descripcion,
            self.registro_base,
            self.pagina,
            self.year,
            self.quarter,
        )


def _int_env(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    return int(raw) if raw else default


def _proxy_base() -> str:
    base = (
        os.environ.get("LITELLM_PROXY_BASE")
        or os.environ.get("LITELLM_API_BASE")
        or ""
    ).strip().rstrip("/")
    if not base:
        raise RuntimeError("Set LITELLM_PROXY_BASE or LITELLM_API_BASE.")
    return base if base.endswith("/v1") or "/v1/" in base else f"{base}/v1"


def _proxy_base_for_metadata() -> str:
    return (
        os.environ.get("LITELLM_PROXY_BASE")
        or os.environ.get("LITELLM_API_BASE")
        or ""
    ).strip() or "(unset)"


def _proxy_key() -> str:
    key = (
        os.environ.get("INDEC_EPH_VARIABLES_LITELLM_KEY")
        or os.environ.get("LITELLM_KEY")
        or os.environ.get("LITELLM_PROXY_KEY")
        or ""
    ).strip()
    if not key:
        raise RuntimeError(
            "Set INDEC_EPH_VARIABLES_LITELLM_KEY, LITELLM_KEY, or LITELLM_PROXY_KEY."
        )
    return key


def _model() -> str:
    return (os.environ.get("INDEC_EPH_VARIABLES_LITELLM_MODEL") or DEFAULT_MODEL).strip()


def _variables_pdf_url(year: int, quarter: int) -> str:
    return (
        os.environ.get("INDEC_EPH_VARIABLES_URL") or f"{FTP_ROOT}EPH_registro_{quarter}T{year}.pdf"
    ).strip()


def _variables_pdf_path(year: int, quarter: int) -> Path:
    return data_local_root() / VARIABLES_SUBDIR / str(year) / f"EPH_registro_{quarter}T{year}.pdf"


def _download_variables_pdf(
    *,
    year: int,
    quarter: int,
    overwrite: bool = False,
    emit: EmitFn | None = None,
) -> dict[str, Any]:
    url = _variables_pdf_url(year, quarter)
    target = _variables_pdf_path(year, quarter)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        size = target.stat().st_size
        _emit(emit, f"[variables_pdf] cache hit path={target} bytes={size}")
        return {"path": str(target), "bytes": size, "from_cache": True, "url": url}

    timeout_s = float(os.environ.get("INDEC_EPH_VARIABLES_HTTP_TIMEOUT", "120"))
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.unlink(missing_ok=True)
    t0 = time.perf_counter()
    _emit(emit, f"[variables_pdf] GET {url} -> {target}")
    with httpx.Client(timeout=httpx.Timeout(timeout_s)) as client:
        with client.stream("GET", url, follow_redirects=True) as resp:
            resp.raise_for_status()
            content_type = (resp.headers.get("content-type") or "").lower()
            if "html" in content_type:
                raise RuntimeError(f"refusing HTML body as PDF ({content_type}) url={url}")
            with tmp.open("wb") as fh:
                first = True
                for chunk in resp.iter_bytes(1 << 16):
                    if not chunk:
                        continue
                    if first:
                        if not chunk.startswith(b"%PDF"):
                            tmp.unlink(missing_ok=True)
                            raise RuntimeError(f"response is not a PDF (no %PDF magic) url={url}")
                        first = False
                    fh.write(chunk)
    os.replace(tmp, target)
    elapsed = time.perf_counter() - t0
    size = target.stat().st_size
    _emit(emit, f"[variables_pdf] done bytes={size} elapsed_sec={elapsed:.2f}")
    return {
        "path": str(target),
        "bytes": size,
        "from_cache": False,
        "url": url,
        "elapsed_sec": round(elapsed, 3),
    }


def _sync_pdf_to_minio(pdf_path: Path, *, emit: EmitFn | None = None) -> dict[str, Any]:
    return sync_tree_to_minio(pdf_path.parent, root=data_local_root(), emit=emit)


def _strip_json_fences(text: str) -> str:
    stripped = text.strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    raw = (resp.headers.get("retry-after") or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        from datetime import datetime, timezone
        from email.utils import parsedate_to_datetime

        try:
            dt = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())


def _post_with_retries(
    client: httpx.Client,
    *,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    label: str,
    emit: EmitFn | None,
) -> httpx.Response:
    retries = max(1, int(os.environ.get("INDEC_EPH_VARIABLES_MAX_RETRIES", "6")))
    backoff = 2.0
    last_err = "unknown error"
    for attempt in range(1, retries + 1):
        try:
            resp = client.post(url, headers=headers, json=body)
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            last_err = f"{type(exc).__name__}: {exc}"
        else:
            if resp.status_code < 400:
                return resp
            if resp.status_code not in {429} and resp.status_code < 500:
                raise RuntimeError(f"[{label}] HTTP {resp.status_code}: {(resp.text or '')[:500]}")
            last_err = f"HTTP {resp.status_code}: {(resp.text or '')[:300]}"
            if resp.status_code == 429:
                backoff = min(_retry_after_seconds(resp) or max(backoff, 30.0), 120.0)

        if attempt == retries:
            break
        _emit(emit, f"[{label}] retry attempt={attempt} error={last_err} sleep={backoff:.1f}s")
        time.sleep(backoff)
        backoff = min(backoff * 2, 60.0)
    raise RuntimeError(f"[{label}] exhausted {retries} attempts: {last_err}")


def _extract_pdf_payload(pdf_path: Path, *, emit: EmitFn | None = None) -> dict[str, Any]:
    label = f"variables_llm[{pdf_path.name}]"
    pdf_bytes = pdf_path.read_bytes()
    if not pdf_bytes.startswith(b"%PDF"):
        raise RuntimeError(f"[{label}] file is not a PDF: {pdf_path}")

    max_tokens = max(1024, int(os.environ.get("INDEC_EPH_VARIABLES_LITELLM_MAX_TOKENS", "32768")))
    body = {
        "model": _model(),
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": EXTRACT_PROMPT},
                    {
                        "type": "file",
                        "file": {
                            "filename": pdf_path.name,
                            "file_data": "data:application/pdf;base64,"
                            + base64.b64encode(pdf_bytes).decode("ascii"),
                        },
                    },
                ],
            }
        ],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    _emit(
        emit,
        f"[{label}] sending whole PDF model={_model()} bytes={len(pdf_bytes)} max_tokens={max_tokens}",
    )
    t0 = time.perf_counter()
    with httpx.Client(
        timeout=httpx.Timeout(float(os.environ.get("INDEC_EPH_VARIABLES_LITELLM_HTTP_TIMEOUT", "600"))),
        trust_env=False,
    ) as client:
        resp = _post_with_retries(
            client,
            url=f"{_proxy_base()}/chat/completions",
            headers={"Authorization": f"Bearer {_proxy_key()}", "Content-Type": "application/json"},
            body=body,
            label=label,
            emit=emit,
        )
    data = resp.json()
    try:
        text = str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"[{label}] unexpected chat response shape: {str(data)[:500]}") from exc

    cleaned = _strip_json_fences(text)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"[{label}] non-JSON response (head 500): {cleaned[:500]}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"[{label}] expected JSON object, got {type(payload).__name__}")

    payload["elapsed_sec"] = round(time.perf_counter() - t0, 3)
    payload["response_chars"] = len(cleaned)
    return payload


_TIPO_ALIASES = {
    "n": "N",
    "num": "N",
    "numerico": "N",
    "numérico": "N",
    "number": "N",
    "c": "C",
    "char": "C",
    "caracter": "C",
    "carácter": "C",
    "string": "C",
    "str": "C",
    "text": "C",
    "d": "D",
    "date": "D",
    "fecha": "D",
}


def _coerce_int(raw: Any, default: int = 0) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _coerce_rows(raw_rows: Any, *, registro_base: str, year: int, quarter: int) -> list[VariableRow]:
    if not isinstance(raw_rows, list):
        return []

    rows: list[VariableRow] = []
    seen: set[str] = set()
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        campo = str(raw.get("campo") or "").strip()
        tipo = _TIPO_ALIASES.get(str(raw.get("tipo") or "").strip().lower(), str(raw.get("tipo") or "").upper()[:1])
        if not campo or not tipo or campo in seen:
            continue
        seen.add(campo)
        rows.append(
            VariableRow(
                campo=campo,
                tipo=tipo,
                longitud=_coerce_int(raw.get("longitud")),
                descripcion=str(raw.get("descripcion") or "").strip(),
                registro_base=registro_base,
                pagina=_coerce_int(raw.get("pagina")),
                year=year,
                quarter=quarter,
            )
        )
    return rows


def _extract_pdf_with_llm(
    pdf_path: Path,
    *,
    year: int,
    quarter: int,
    emit: EmitFn | None = None,
) -> dict[str, Any]:
    payload = _extract_pdf_payload(pdf_path, emit=emit)
    hogar_rows = _coerce_rows(payload.get("hogar"), registro_base="hogar", year=year, quarter=quarter)
    individual_rows = _coerce_rows(
        payload.get("individual"),
        registro_base="individual",
        year=year,
        quarter=quarter,
    )
    anexo_summary = str(payload.get("anexo_summary") or "").strip()
    _emit(
        emit,
        f"[variables_llm[{pdf_path.name}]] done elapsed_sec={payload['elapsed_sec']:.2f} "
        f"hogar={len(hogar_rows)} individual={len(individual_rows)} anexo_chars={len(anexo_summary)}",
    )
    return {
        "hogar": hogar_rows,
        "individual": individual_rows,
        "anexo_summary": anexo_summary,
        "elapsed_sec": payload["elapsed_sec"],
        "response_chars": payload["response_chars"],
    }


_VARIABLES_SCHEMA_SQL = (
    "campo VARCHAR, tipo VARCHAR, longitud INTEGER, descripcion TEXT, "
    "registro_base VARCHAR, pagina INTEGER, year INTEGER, quarter INTEGER"
)
_VARIABLES_PLACEHOLDERS = "?, ?, ?, ?, ?, ?, ?, ?"


@asset(
    group_name="bronze",
    compute_kind="litellm",
    description=(
        "Download INDEC EPH registro PDF, extract hogar/individual variables with one LiteLLM "
        "PDF call, and write bronze.indec_eph_variables."
    ),
)
def indec_eph_variables(context, database: DuckDBResource) -> MaterializeResult:
    year = _int_env("INDEC_EPH_TRIMESTRAL_YEAR", 2025)
    quarter = _int_env("INDEC_EPH_VARIABLES_QUARTER", 3)
    url = _variables_pdf_url(year, quarter)
    model = _model()
    context.log.info(
        "indec_eph_variables start year=%s quarter=%s model=%s proxy=%s url=%s",
        year,
        quarter,
        model,
        _proxy_base_for_metadata(),
        url,
    )

    dl = _download_variables_pdf(year=year, quarter=quarter, emit=context.log.info)
    pdf_path = Path(dl["path"])
    sync_res = _sync_pdf_to_minio(pdf_path, emit=context.log.info)
    extracted = _extract_pdf_with_llm(pdf_path, year=year, quarter=quarter, emit=context.log.info)

    hogar_rows = extracted["hogar"]
    individual_rows = extracted["individual"]
    rows = [r.as_tuple() for r in (*hogar_rows, *individual_rows)]

    duck_path = os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb").strip()
    with database.get_connection() as con:
        out = materialize_rows(
            con,
            namespace=BRONZE_SCHEMA,
            table=TABLE_VARIABLES,
            schema_sql=_VARIABLES_SCHEMA_SQL,
            rows=rows,
            insert_placeholders=_VARIABLES_PLACEHOLDERS,
        )

    context.log.info(
        "indec_eph_variables done hogar=%d individual=%d total=%d storage=%s "
        "anexo_chars=%d llm_elapsed_sec=%.2f response_chars=%d",
        len(hogar_rows),
        len(individual_rows),
        len(rows),
        out.get("storage"),
        len(extracted["anexo_summary"]),
        float(extracted.get("elapsed_sec") or 0.0),
        int(extracted.get("response_chars") or 0),
    )

    rel = out.get("iceberg_fqn") or out.get("duckdb_fqn")
    return MaterializeResult(
        metadata={
            "source_portal": MetadataValue.url(SOURCE_PAGE),
            "source_pdf_url": MetadataValue.url(url),
            "pdf_path": dl["path"],
            "pdf_bytes": dl["bytes"],
            "minio_uploaded": int(sync_res.get("uploaded", 0)),
            "minio_skipped": bool(sync_res.get("skipped", False)),
            "duckdb_path": duck_path,
            "storage": out.get("storage"),
            "relation_fqn": rel,
            "row_count": out.get("row_count"),
            "hogar_rows": len(hogar_rows),
            "individual_rows": len(individual_rows),
            "year": year,
            "quarter": quarter,
            "anexo_chars": len(extracted["anexo_summary"]),
            "anexo_summary_es": MetadataValue.md(extracted["anexo_summary"] or "_(empty)_"),
            "litellm_model": model,
            "litellm_proxy_base": _proxy_base_for_metadata(),
            "litellm_elapsed_sec": float(extracted.get("elapsed_sec") or 0.0),
            "litellm_response_chars": int(extracted.get("response_chars") or 0),
        }
    )
