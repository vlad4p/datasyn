"""La Nación Opinión / columnistas: listado, perfiles y notas con sufijo ``-nidDDMMYYYY``."""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from datasyn.assets.bronze.lanacion.lib import (
    LN_BASE,
    _extract_body_markdown,
    _extract_published,
    _extract_title,
    _http_client,
    _parse_nid_date_from_path,
)

COLUMNISTAS_HUB = f"{LN_BASE}/opinion/columnistas/"

log = logging.getLogger("datasyn.lanacion.opinion")

_MAX_COL = int(__import__("os").environ.get("LANACION_OPINION_MAX_COLUMNISTS", "260"))
_MAX_OP_PER_AUTHOR = int(__import__("os").environ.get("LANACION_OPINION_MAX_LINKS_PER_AUTHOR", "80"))


def stable_columnista_id(autor_url: str) -> int:
    """Id estable ( BIGINT ) derivado de la URL del autor."""
    norm = autor_url.strip().rstrip("/").lower()
    h = hashlib.sha256(norm.encode("utf-8")).digest()[:8]
    return int.from_bytes(h, "big") % (2**63 - 1)


def _slug_from_autor_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2 and parts[0].lower() == "autor":
        return parts[-1][:200]
    seg = path.split("/")[-1] or "autor"
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", seg)[:200]


def _date_path(d: date) -> str:
    return f"{d.year:04d}/{d.month:02d}/{d.day:02d}"


def collect_autor_urls(html: str) -> list[str]:
    pat = re.compile(r'href=["\'](/autor/[^"\'#?]+/)["\']', re.IGNORECASE)
    found: set[str] = set()
    for m in pat.finditer(html):
        rel = m.group(1).split("?")[0]
        if not rel.lower().startswith("/autor/"):
            continue
        u = urljoin(LN_BASE, rel)
        if u.rstrip("/") not in {x.rstrip("/") for x in found}:
            found.add(u)
        if len(found) >= _MAX_COL:
            break
    return sorted(found)


def collect_opinion_urls_for_day(html: str, partition_day: date) -> list[str]:
    pat = re.compile(r'href=["\'](/opinion/[^"\'#?]+-nid\d{8}/)["\']', re.IGNORECASE)
    out: list[str] = []
    seen: set[str] = set()
    for m in pat.finditer(html):
        rel = m.group(1).split("?")[0]
        u = urljoin(LN_BASE, rel)
        if u in seen:
            continue
        d = _parse_nid_date_from_path("/" + rel.lstrip("/"))
        if d != partition_day:
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= _MAX_OP_PER_AUTHOR:
            break
    return sorted(out)


def _extract_perfil_politico(soup: BeautifulSoup, nombre_fallback: str) -> str:
    """Biografía / posicionamiento editorial visible en la ficha del autor (perfil para análisis)."""
    og = soup.find("meta", property="og:description")
    if og and og.get("content"):
        t = str(og["content"]).strip()
        if len(t) > 80:
            return t
    desc = soup.find("meta", attrs={"name": "description"})
    if desc and desc.get("content"):
        t = str(desc["content"]).strip()
        if len(t) > 80:
            return t
    root = soup.find("article") or soup.find("main") or soup.find("body")
    if not root:
        return ""
    chunks: list[str] = []
    for p in root.find_all("p"):
        txt = p.get_text(" ", strip=True)
        if len(txt) > 120:
            chunks.append(txt)
        if len(chunks) >= 4:
            break
    if chunks:
        return "\n\n".join(chunks)
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(" ", strip=True)
    return nombre_fallback


@dataclass
class ColumnistDoc:
    columnista_id: int
    nombre: str
    autor_url: str
    slug: str
    perfil_politico: str
    landing_key: str


@dataclass
class OpinionDoc:
    columnista_id: int
    slug_columnista: str
    titulo: str
    url: str
    fecha_publicacion: datetime
    cuerpo_md: str
    tema: str
    landing_key: str


def build_columnist_markdown(doc: ColumnistDoc, scraped_at: datetime) -> str:
    esc = doc.nombre.replace('"', "'")
    slug_esc = doc.slug.replace('"', "'")
    return "\n".join(
        [
            "---",
            'kind: "columnista"',
            f"columnista_id: {doc.columnista_id}",
            f'nombre: "{esc}"',
            f"autor_url: {doc.autor_url}",
            f'slug: "{slug_esc}"',
            f"scraped_at: {scraped_at.isoformat()}",
            f"landing_key: {doc.landing_key}",
            "---",
            "",
            doc.perfil_politico,
        ]
    )


def build_opinion_markdown(doc: OpinionDoc, scraped_at: datetime) -> str:
    esc = doc.titulo.replace('"', "'")
    tema = (doc.tema or "").replace('"', "'")
    slug_c = doc.slug_columnista.replace('"', "'")
    return "\n".join(
        [
            "---",
            'kind: "opinion"',
            f"columnista_id: {doc.columnista_id}",
            f'slug_columnista: "{slug_c}"',
            f'title: "{esc}"',
            f"url: {doc.url}",
            f'tema: "{tema}"',
            f"fecha_publicacion: {doc.fecha_publicacion.isoformat()}",
            f"scraped_at: {scraped_at.isoformat()}",
            f"landing_key: {doc.landing_key}",
            "---",
            "",
            doc.cuerpo_md,
        ]
    )


def scrape_opinion_partition(*, partition_day: date, sleep_s: float = 0.35) -> tuple[list[ColumnistDoc], list[OpinionDoc]]:
    """Descarga hub columnistas, una ficha por autor y notas de opinión del día (vía ``-nid``)."""
    date_path = _date_path(partition_day)
    fallback_midnight = datetime(
        partition_day.year,
        partition_day.month,
        partition_day.day,
        tzinfo=timezone.utc,
    )
    columnists: list[ColumnistDoc] = []
    opinions: list[OpinionDoc] = []

    with _http_client() as client:
        hub = client.get(COLUMNISTAS_HUB)
        hub.raise_for_status()
        autor_urls = collect_autor_urls(hub.text)
        log.info("columnistas encontrados: %s", len(autor_urls))
        time.sleep(sleep_s)

        for autor_url in autor_urls:
            slug = _slug_from_autor_url(autor_url)
            cid = stable_columnista_id(autor_url)
            try:
                r = client.get(autor_url)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")
                nombre = _extract_title(soup) or slug
                perfil = _extract_perfil_politico(soup, nombre)
                ck = f"landing/lanacion/opinion/columnistas/{slug}.md"
                columnists.append(
                    ColumnistDoc(
                        columnista_id=cid,
                        nombre=nombre,
                        autor_url=autor_url.rstrip("/") + "/",
                        slug=slug,
                        perfil_politico=perfil,
                        landing_key=ck,
                    )
                )
                opinion_urls = collect_opinion_urls_for_day(r.text, partition_day)
                for ou in opinion_urls:
                    try:
                        ar = client.get(ou)
                        ar.raise_for_status()
                        asoup = BeautifulSoup(ar.text, "html.parser")
                        titulo = _extract_title(asoup) or ou
                        pub = _extract_published(asoup, fallback_midnight)
                        body = _extract_body_markdown(asoup)
                        # Tema secundario (chip) si existe
                        tema = ""
                        chip = asoup.find("a", href=re.compile(r"/tema/|/tag/", re.I))
                        if chip and chip.get_text(strip=True):
                            tema = chip.get_text(" ", strip=True)[:500]
                        art_slug = urlparse(ou).path.rstrip("/").split("/")[-1] or "opinion"
                        art_slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", art_slug)[:160]
                        ok = f"landing/lanacion/opinion/articulos/{date_path}/{slug}__{art_slug}.md"
                        opinions.append(
                            OpinionDoc(
                                columnista_id=cid,
                                slug_columnista=slug,
                                titulo=titulo,
                                url=ou,
                                fecha_publicacion=pub,
                                cuerpo_md=body,
                                tema=tema,
                                landing_key=ok,
                            )
                        )
                    except Exception as exc:
                        log.warning("skip opinion %s: %s", ou, exc)
                    time.sleep(sleep_s)
            except Exception as exc:
                log.warning("skip autor %s: %s", autor_url, exc)
            time.sleep(sleep_s)

    return columnists, opinions
