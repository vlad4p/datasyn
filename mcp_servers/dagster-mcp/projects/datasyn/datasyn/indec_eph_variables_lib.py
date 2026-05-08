"""INDEC EPH ``registro`` PDF parser.

Source: https://www.indec.gob.ar/ftp/cuadros/menusuperior/eph/EPH_registro_<Q>T<YEAR>.pdf

Each page renders the variables list as plain text (not real PDF tables), e.g.::

    AGLOMERADO N (2) Código de Aglomerado
                02 = Gran La Plata
                03 = Bahía Blanca-Cerri
    CH04        N (1) Sexo
                1 = Varón
                2 = Mujer

We split each page's text on the regex ``^([A-Z][A-Z0-9_]+)\\s+([A-Z])\\s*\\((\\d+)\\)\\s+(.*)$``
and accumulate following lines as the description body until the next match.
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pdfplumber

from datasyn.indec_eph_trimestral_lib import (
    EmitFn,
    LANDING_SUBDIR,
    _emit,
    data_local_root,
    sync_tree_to_minio,
)

log = logging.getLogger(__name__)

SOURCE_PAGE = "https://www.indec.gob.ar/indec/web/Institucional-Indec-BasesDeDatos"
FTP_ROOT = "https://www.indec.gob.ar/ftp/cuadros/menusuperior/eph/"

BRONZE_SCHEMA = "bronze"
TABLE_VARIABLES = "indec_eph_variables"

VARIABLES_SUBDIR = LANDING_SUBDIR / "variables"

# ``CAMPO TIPO (longitud) descripcion`` — start-of-variable marker on each text line.
_VAR_LINE = re.compile(
    r"^(?P<campo>[A-ZÑ][A-ZÑ0-9_]+)\s+(?P<tipo>[A-Z])\s*\((?P<longitud>\d+)\)\s+(?P<descripcion>.*)$"
)


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


def variables_pdf_url(year: int, quarter: int) -> str:
    override = (os.environ.get("INDEC_EPH_VARIABLES_URL") or "").strip()
    if override:
        return override
    return f"{FTP_ROOT}EPH_registro_{quarter}T{year}.pdf"


def variables_pdf_path(year: int, quarter: int) -> Path:
    return data_local_root() / VARIABLES_SUBDIR / str(year) / f"EPH_registro_{quarter}T{year}.pdf"


def download_variables_pdf(
    *,
    year: int,
    quarter: int,
    overwrite: bool = False,
    timeout_s: float | None = None,
    emit: EmitFn | None = None,
) -> dict[str, Any]:
    """Fetch the registro PDF, cache under ``DATA_LOCAL_ROOT/landing/indec/eph/variables/<year>/``."""

    if timeout_s is None:
        timeout_s = float(os.environ.get("INDEC_EPH_VARIABLES_HTTP_TIMEOUT", "120"))
    url = variables_pdf_url(year, quarter)
    target = variables_pdf_path(year, quarter)
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and not overwrite:
        sz = target.stat().st_size
        _emit(emit, f"[variables_pdf] cache hit path={target} bytes={sz}")
        return {"path": str(target), "bytes": sz, "from_cache": True, "url": url}

    t0 = time.perf_counter()
    _emit(emit, f"[variables_pdf] GET {url} -> {target}")
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.unlink(missing_ok=True)
    with httpx.Client(timeout=httpx.Timeout(timeout_s)) as client:
        with client.stream("GET", url, follow_redirects=True) as resp:
            resp.raise_for_status()
            ct = (resp.headers.get("content-type") or "").lower()
            if "html" in ct:
                raise RuntimeError(f"refusing HTML body as PDF ({ct}) url={url}")
            with tmp.open("wb") as fh:
                first = True
                for chunk in resp.iter_bytes(1 << 16):
                    if first:
                        if not chunk.startswith(b"%PDF"):
                            tmp.unlink(missing_ok=True)
                            raise RuntimeError(f"response is not a PDF (no %PDF magic) url={url}")
                        first = False
                    fh.write(chunk)
    os.replace(tmp, target)
    elapsed = time.perf_counter() - t0
    sz = target.stat().st_size
    _emit(emit, f"[variables_pdf] done bytes={sz} elapsed_sec={elapsed:.2f}")
    return {
        "path": str(target),
        "bytes": sz,
        "from_cache": False,
        "url": url,
        "elapsed_sec": round(elapsed, 3),
    }


def _flush(
    pending: dict[str, Any] | None,
    desc_lines: list[str],
    out: list[VariableRow],
    *,
    registro_base: str,
    year: int,
    quarter: int,
) -> None:
    if not pending:
        return
    desc = "\n".join(s.rstrip() for s in desc_lines).strip()
    out.append(
        VariableRow(
            campo=pending["campo"],
            tipo=pending["tipo"],
            longitud=int(pending["longitud"]),
            descripcion=desc,
            registro_base=registro_base,
            pagina=pending["pagina"],
            year=year,
            quarter=quarter,
        )
    )


def parse_variable_pages(
    pdf_path: Path,
    *,
    page_start: int,
    page_end: int,
    registro_base: str,
    year: int,
    quarter: int,
    emit: EmitFn | None = None,
) -> list[VariableRow]:
    """Parse 1-based inclusive page range; return one row per ``CAMPO``."""

    if page_start < 1 or page_end < page_start:
        raise ValueError(f"invalid page range start={page_start} end={page_end}")

    rows: list[VariableRow] = []
    pending: dict[str, Any] | None = None
    desc_lines: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        last = min(page_end, total)
        _emit(
            emit,
            f"[variables_parse] {registro_base} pages {page_start}-{last}/{total} src={pdf_path.name}",
        )
        for human_page in range(page_start, last + 1):
            page = pdf.pages[human_page - 1]
            text = page.extract_text() or ""
            for raw in text.splitlines():
                line = raw.rstrip()
                if not line.strip():
                    if pending is not None:
                        desc_lines.append("")
                    continue
                m = _VAR_LINE.match(line)
                if m:
                    _flush(
                        pending,
                        desc_lines,
                        rows,
                        registro_base=registro_base,
                        year=year,
                        quarter=quarter,
                    )
                    pending = {
                        "campo": m.group("campo"),
                        "tipo": m.group("tipo"),
                        "longitud": m.group("longitud"),
                        "pagina": human_page,
                    }
                    desc_lines = [m.group("descripcion").strip()]
                else:
                    if pending is None:
                        # Header / section banner before the first variable on a page; skip.
                        continue
                    desc_lines.append(line.strip())
    _flush(pending, desc_lines, rows, registro_base=registro_base, year=year, quarter=quarter)
    _emit(emit, f"[variables_parse] {registro_base} extracted_rows={len(rows)}")
    return rows


def extract_anexo_text(pdf_path: Path, *, pages: list[int]) -> str:
    """Concatenate text from 1-based page numbers (used for the anexo / general comments)."""

    parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        for p in pages:
            if 1 <= p <= total:
                parts.append((pdf.pages[p - 1].extract_text() or "").strip())
    return "\n\n".join(s for s in parts if s).strip()


def summarize_anexo_es(text: str, *, max_chars: int = 1500) -> str:
    """Heuristic Spanish summary: keep the first ``max_chars`` worth of complete paragraphs."""

    if not text:
        return ""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out: list[str] = []
    used = 0
    for p in paragraphs:
        if used + len(p) + 2 > max_chars and out:
            break
        out.append(p)
        used += len(p) + 2
    return "\n\n".join(out)


def sync_pdf_to_minio(pdf_path: Path, *, emit: EmitFn | None = None) -> dict[str, Any]:
    """Mirror the cached PDF directory into the MinIO ``data-local`` bucket (no-op if disabled)."""

    return sync_tree_to_minio(pdf_path.parent, root=data_local_root(), emit=emit)


__all__ = [
    "BRONZE_SCHEMA",
    "FTP_ROOT",
    "SOURCE_PAGE",
    "TABLE_VARIABLES",
    "VARIABLES_SUBDIR",
    "VariableRow",
    "download_variables_pdf",
    "extract_anexo_text",
    "parse_variable_pages",
    "summarize_anexo_es",
    "sync_pdf_to_minio",
    "variables_pdf_path",
    "variables_pdf_url",
]
