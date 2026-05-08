"""LiteLLM-backed extractor for the INDEC EPH ``registro`` PDF (single-call).

The full PDF is base64-encoded and sent as **one** OpenAI-compatible chat completion
to the LiteLLM proxy (``gemini/gemini-3.1-flash-lite-preview`` by default). Gemini
ingests the PDF inline (``application/pdf``) and returns a single JSON document with
both variable sections (``hogar`` / ``individual``) and a Spanish summary of the anexo.
We then iterate the JSON and turn each entry into a :class:`VariableRow`.

Env (defaults align with ``infra/dagster/.env``):

* ``LITELLM_PROXY_BASE`` (or ``LITELLM_API_BASE``) — base URL; ``/v1`` is appended if missing.
* ``INDEC_EPH_VARIABLES_LITELLM_KEY`` (preferred) or ``LITELLM_KEY`` /
  ``LITELLM_PROXY_KEY`` — bearer token. The asset-scoped key wins so this
  module can use a key with broader model access (e.g. the LiteLLM master key)
  without rotating the global ``LITELLM_KEY``.
* ``INDEC_EPH_VARIABLES_LITELLM_MODEL`` — default ``gemini/gemini-3.1-flash-lite-preview``.
* ``INDEC_EPH_VARIABLES_LITELLM_HTTP_TIMEOUT`` — seconds (default 600).
* ``INDEC_EPH_VARIABLES_MAX_RETRIES`` — total attempts on 429/5xx/timeout (default 4).
* ``INDEC_EPH_VARIABLES_LITELLM_MAX_TOKENS`` — response cap (default 32768).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx

from datasyn.indec_eph_trimestral_lib import EmitFn, _emit
from datasyn.indec_eph_variables_lib import VariableRow

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini/gemini-3.1-flash-lite-preview"

EXTRACT_PROMPT = """\
Eres un asistente que lee el PDF "Diseño de Registro" de INDEC EPH (Encuesta Permanente
de Hogares) y devuelve TODAS las variables documentadas en él, en un único JSON.

El PDF tiene dos secciones de variables:
1. Variables del registro **hogar** (suele empezar tras la introducción, en torno a las
   primeras páginas, antes de la sección de individual).
2. Variables del registro **individual** (después de la sección de hogar).

Y al final un **anexo** con notas técnicas (recomendaciones, factores de expansión,
montos, deciles, etc.) que debes sintetizar en español.

Cada fila en las tablas de variables tiene cuatro columnas:
- ``campo``: nombre exacto en mayúsculas, puede llevar guion bajo (p. ej. ``CODUSU``,
  ``NRO_HOGAR``, ``AGLOMERADO``, ``PP07I2``).
- ``tipo``: una sola letra (``N`` numérico, ``C`` carácter, ``D`` fecha).
- ``longitud``: entero entre paréntesis a continuación del tipo (``N (2)`` -> 2).
- ``descripcion``: texto descriptivo y, si aparecen, las enumeraciones de valores
  (p. ej. "1 = Sí | 2 = No"). Conserva los códigos.

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
3. ``pagina`` es el número de página del PDF (1-based) donde aparece la variable.
   Si no puedes determinarla con seguridad, usa 0.
4. NO inventes variables: incluye solo las que aparecen literalmente en las tablas.
5. NO repitas una misma ``campo`` dentro de la misma sección.
6. ``anexo_summary``: resumen conciso (≤ 2000 caracteres) en español, conservando los
   puntos técnicos importantes y los nombres de variables citadas.
"""


# ---- env helpers ----------------------------------------------------------


def _proxy_base() -> str:
    base = (
        os.environ.get("LITELLM_PROXY_BASE")
        or os.environ.get("LITELLM_API_BASE")
        or ""
    ).strip().rstrip("/")
    if not base:
        raise RuntimeError(
            "Set LITELLM_PROXY_BASE (or LITELLM_API_BASE) — e.g. http://litellm:4000"
        )
    if not base.endswith("/v1") and "/v1/" not in base:
        base = base + "/v1"
    return base


def _proxy_key() -> str:
    # Prefer an asset-scoped key so this module can use a token with broader
    # model access (e.g. ``gemini-3.1-*-preview``) without changing the global
    # ``LITELLM_KEY`` used by other services.
    key = (
        os.environ.get("INDEC_EPH_VARIABLES_LITELLM_KEY")
        or os.environ.get("LITELLM_KEY")
        or os.environ.get("LITELLM_PROXY_KEY")
        or ""
    ).strip()
    if not key:
        raise RuntimeError(
            "Set INDEC_EPH_VARIABLES_LITELLM_KEY (preferred) or LITELLM_KEY to your LiteLLM key."
        )
    return key


def _model() -> str:
    return (os.environ.get("INDEC_EPH_VARIABLES_LITELLM_MODEL") or DEFAULT_MODEL).strip()


def _timeout_s() -> float:
    return float(os.environ.get("INDEC_EPH_VARIABLES_LITELLM_HTTP_TIMEOUT", "600"))


def _max_retries() -> int:
    return max(1, int(os.environ.get("INDEC_EPH_VARIABLES_MAX_RETRIES", "6")))


def _max_tokens() -> int:
    return max(1024, int(os.environ.get("INDEC_EPH_VARIABLES_LITELLM_MAX_TOKENS", "32768")))


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """Parse ``Retry-After`` (seconds or HTTP-date). Returns None when absent/invalid."""

    raw = (resp.headers.get("retry-after") or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone

        try:
            dt = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())


# ---- low-level HTTP / JSON helpers ---------------------------------------


def _strip_json_fences(text: str) -> str:
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _post_with_retries(
    client: httpx.Client,
    *,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    label: str,
    emit: EmitFn | None,
) -> httpx.Response:
    """POST with retry on connect/timeout/429/5xx.

    Backoff strategy: exponential starting at 2s (cap 60s) for connect/5xx;
    Gemini's free-tier RPM limit is tight, so 429 uses a longer base (30s, cap 120s)
    and honors ``Retry-After`` when the proxy/upstream provides it.
    """

    retries = _max_retries()
    last_err: str | None = None
    backoff = 2.0
    for attempt in range(1, retries + 1):
        try:
            r = client.post(url, headers=headers, json=body)
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            _emit(emit, f"[{label}] retry attempt={attempt} error={last_err} sleep={backoff:.1f}s")
            if attempt == retries:
                break
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
            continue
        if r.status_code == 429:
            ra = _retry_after_seconds(r)
            sleep_s = ra if ra is not None and ra > 0 else max(backoff, 30.0)
            sleep_s = min(sleep_s, 120.0)
            last_err = f"HTTP 429: {(r.text or '')[:300]}"
            _emit(
                emit,
                f"[{label}] retry attempt={attempt} status=429 retry_after={ra} sleep={sleep_s:.1f}s",
            )
            if attempt == retries:
                break
            time.sleep(sleep_s)
            backoff = min(max(backoff * 2, 30.0), 120.0)
            continue
        if r.status_code >= 500:
            last_err = f"HTTP {r.status_code}: {(r.text or '')[:300]}"
            _emit(emit, f"[{label}] retry attempt={attempt} status={r.status_code} sleep={backoff:.1f}s")
            if attempt == retries:
                break
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"[{label}] non-retriable HTTP {r.status_code}: {(r.text or '')[:500]}")
        return r
    raise RuntimeError(f"[{label}] exhausted {retries} attempts: {last_err}")


def _chat_with_pdf(
    client: httpx.Client,
    *,
    pdf_b64: str,
    pdf_filename: str,
    prompt: str,
    label: str,
    emit: EmitFn | None,
) -> str:
    """One chat completion with the whole PDF inline (``application/pdf``)."""

    body: dict[str, Any] = {
        "model": _model(),
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        # OpenAI-compat ``file`` content; LiteLLM forwards the inline
                        # base64 PDF as Gemini ``inline_data`` with ``application/pdf``.
                        "type": "file",
                        "file": {
                            "filename": pdf_filename,
                            "file_data": f"data:application/pdf;base64,{pdf_b64}",
                        },
                    },
                ],
            }
        ],
        "temperature": 0.0,
        "max_tokens": _max_tokens(),
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {_proxy_key()}",
        "Content-Type": "application/json",
    }
    url = f"{_proxy_base()}/chat/completions"
    r = _post_with_retries(client, url=url, headers=headers, body=body, label=label, emit=emit)
    data = r.json()
    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"[{label}] unexpected chat response shape: {str(data)[:500]}") from exc


# ---- row coercion ---------------------------------------------------------


_TIPO_ALIASES = {
    "n": "N", "num": "N", "numerico": "N", "numérico": "N", "number": "N",
    "c": "C", "char": "C", "caracter": "C", "carácter": "C", "string": "C", "str": "C", "text": "C",
    "d": "D", "date": "D", "fecha": "D",
}


def _normalize_tipo(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    return _TIPO_ALIASES.get(s.lower(), s.upper()[:1])


def _coerce_int(raw: Any, default: int = 0) -> int:
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def _coerce_rows(
    raw_rows: Any,
    *,
    registro_base: str,
    year: int,
    quarter: int,
    emit: EmitFn | None,
    label: str,
) -> list[VariableRow]:
    if raw_rows is None:
        return []
    if not isinstance(raw_rows, list):
        _emit(emit, f"[{label}] expected list for {registro_base}, got {type(raw_rows).__name__}")
        return []

    rows: list[VariableRow] = []
    seen: set[str] = set()
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        campo = str(raw.get("campo") or "").strip()
        tipo = _normalize_tipo(raw.get("tipo"))
        if not campo or not tipo or campo in seen:
            continue
        seen.add(campo)
        rows.append(
            VariableRow(
                campo=campo,
                tipo=tipo,
                longitud=_coerce_int(raw.get("longitud"), 0),
                descripcion=str(raw.get("descripcion") or "").strip(),
                registro_base=registro_base,
                pagina=_coerce_int(raw.get("pagina"), 0),
                year=year,
                quarter=quarter,
            )
        )
    return rows


# ---- public API: single call ---------------------------------------------


def extract_pdf_with_llm(
    pdf_path: Path,
    *,
    year: int,
    quarter: int,
    emit: EmitFn | None = None,
) -> dict[str, Any]:
    """Send the entire PDF in one LiteLLM call; return parsed sections + anexo summary.

    Returns:
        {
          "hogar": list[VariableRow],
          "individual": list[VariableRow],
          "anexo_summary": str,
          "model": str,
          "pdf_bytes": int,
          "elapsed_sec": float,
          "response_chars": int,
        }
    """

    label = f"variables_llm[{pdf_path.name}]"
    pdf_bytes = pdf_path.read_bytes()
    if not pdf_bytes.startswith(b"%PDF"):
        raise RuntimeError(f"[{label}] file is not a PDF (no %PDF magic): {pdf_path}")
    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")

    _emit(
        emit,
        f"[{label}] sending whole PDF model={_model()} bytes={len(pdf_bytes)} "
        f"b64_chars={len(pdf_b64)} max_tokens={_max_tokens()}",
    )
    t0 = time.perf_counter()
    timeout = httpx.Timeout(_timeout_s())
    with httpx.Client(timeout=timeout, trust_env=False) as client:
        text = _chat_with_pdf(
            client,
            pdf_b64=pdf_b64,
            pdf_filename=pdf_path.name,
            prompt=EXTRACT_PROMPT,
            label=label,
            emit=emit,
        )
    elapsed = time.perf_counter() - t0

    cleaned = _strip_json_fences(text)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"[{label}] non-JSON response (head 500): {cleaned[:500]}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"[{label}] expected JSON object, got {type(payload).__name__}")

    hogar_rows = _coerce_rows(
        payload.get("hogar"),
        registro_base="hogar",
        year=year,
        quarter=quarter,
        emit=emit,
        label=label,
    )
    indiv_rows = _coerce_rows(
        payload.get("individual"),
        registro_base="individual",
        year=year,
        quarter=quarter,
        emit=emit,
        label=label,
    )
    anexo_summary = str(payload.get("anexo_summary") or "").strip()

    _emit(
        emit,
        f"[{label}] done elapsed_sec={elapsed:.2f} hogar={len(hogar_rows)} "
        f"individual={len(indiv_rows)} anexo_chars={len(anexo_summary)} "
        f"response_chars={len(cleaned)}",
    )

    return {
        "hogar": hogar_rows,
        "individual": indiv_rows,
        "anexo_summary": anexo_summary,
        "model": _model(),
        "pdf_bytes": len(pdf_bytes),
        "elapsed_sec": round(elapsed, 3),
        "response_chars": len(cleaned),
    }


__all__ = [
    "DEFAULT_MODEL",
    "EXTRACT_PROMPT",
    "extract_pdf_with_llm",
]
