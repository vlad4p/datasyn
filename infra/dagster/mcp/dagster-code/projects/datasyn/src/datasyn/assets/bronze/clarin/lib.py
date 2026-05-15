"""Clarín: listados por sección (hub), enlaces ``/{seccion}/…html``, filtro por día vía ``article:published_time`` (UTC)."""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

CLARIN_BASE = "https://www.clarin.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# tema lógico → URL del listado (mismas rutas que el sitio público).
SECTIONS: dict[str, str] = {
    "politica": f"{CLARIN_BASE}/politica",
    "economia": f"{CLARIN_BASE}/economia",
    "rural": f"{CLARIN_BASE}/rural",
}

MAX_LINKS_PER_SECTION = int(os.environ.get("CLARIN_MAX_LINKS_PER_SECTION", "200"))

log = logging.getLogger("datasyn.clarin")


@dataclass
class ArticleDoc:
    tema: str
    titulo: str
    url: str
    fecha_publicacion: datetime
    cuerpo_md: str
    landing_key: str


def _http_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "es-AR,es;q=0.9"},
        timeout=httpx.Timeout(30.0),
        follow_redirects=True,
    )


def _collect_article_urls_from_hub(html: str, section_slug: str) -> list[str]:
    """Enlaces a notas ``/{section_slug}/… .html`` visibles en el HTML del hub."""
    soup = BeautifulSoup(html, "html.parser")
    prefix = f"/{section_slug}/"
    found: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip().split("#")[0].split("?")[0]
        if not href.endswith(".html"):
            continue
        if href.startswith(prefix):
            full = urljoin(CLARIN_BASE, href)
            host = urlparse(full).netloc.lower()
            if host.endswith("clarin.com"):
                found.add(full.rstrip("/"))
        if len(found) >= MAX_LINKS_PER_SECTION:
            break
    return sorted(found)


def _extract_title(soup: BeautifulSoup) -> str:
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return str(og["content"]).strip()
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)
    return ""


def _extract_published(soup: BeautifulSoup, fallback: datetime) -> datetime:
    t = soup.find("meta", property="article:published_time")
    if t and t.get("content"):
        raw = str(t["content"]).strip()
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    el = soup.find("time")
    if el and el.get("datetime"):
        try:
            return datetime.fromisoformat(str(el["datetime"]).replace("Z", "+00:00"))
        except ValueError:
            pass
    return fallback


def _extract_body_markdown(soup: BeautifulSoup) -> str:
    root = soup.find("article") or soup.find("div", class_=re.compile(r"article|body|content", re.I))
    if not root:
        root = soup.find("body") or soup
    parts: list[str] = []
    for p in root.find_all("p"):
        txt = p.get_text(" ", strip=True)
        if len(txt) > 40:
            parts.append(txt)
    if not parts:
        for p in soup.find_all("p"):
            txt = p.get_text(" ", strip=True)
            if len(txt) > 40:
                parts.append(txt)
    return "\n\n".join(parts) if parts else ""


def _slug_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    seg = path.split("/")[-1] or "articulo"
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", seg)[:160]


def _date_path(d: date) -> str:
    return f"{d.year:04d}/{d.month:02d}/{d.day:02d}"


def _utc_calendar_day(dt: datetime) -> date:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date()


def build_markdown_file(doc: ArticleDoc, scraped_at: datetime) -> str:
    meta_lines = [
        "---",
        f'tema: "{doc.tema}"',
        f'title: "{doc.titulo.replace(chr(34), chr(39))}"',
        f"url: {doc.url}",
        f"fecha_publicacion: {doc.fecha_publicacion.isoformat()}",
        f"scraped_at: {scraped_at.isoformat()}",
        f"landing_key: {doc.landing_key}",
        "---",
        "",
        doc.cuerpo_md,
    ]
    return "\n".join(meta_lines)


def scrape_articles_for_partition(
    *,
    partition_day: date,
    sleep_s: float = 0.35,
) -> list[ArticleDoc]:
    """Descarga hubs, recolecta URLs por sección, filtra notas cuyo ``published_time`` (UTC) cae en ``partition_day``."""
    date_path = _date_path(partition_day)
    url_to_tema: dict[str, str] = {}

    with _http_client() as client:
        for tema, hub_url in SECTIONS.items():
            r = client.get(hub_url)
            r.raise_for_status()
            for u in _collect_article_urls_from_hub(r.text, tema):
                url_to_tema.setdefault(u, tema)
            time.sleep(sleep_s)

    fallback_midnight = datetime(
        partition_day.year,
        partition_day.month,
        partition_day.day,
        tzinfo=timezone.utc,
    )
    out: list[ArticleDoc] = []
    with _http_client() as client:
        for url, tema in sorted(url_to_tema.items()):
            try:
                ar = client.get(url)
                ar.raise_for_status()
                soup = BeautifulSoup(ar.text, "html.parser")
                titulo = _extract_title(soup) or url
                pub = _extract_published(soup, fallback_midnight)
                if _utc_calendar_day(pub) != partition_day:
                    continue
                body = _extract_body_markdown(soup)
                slug = _slug_from_url(url)
                landing_key = f"landing/clarin/{tema}/{date_path}/{slug}.md"
                out.append(
                    ArticleDoc(
                        tema=tema,
                        titulo=titulo,
                        url=url,
                        fecha_publicacion=pub,
                        cuerpo_md=body,
                        landing_key=landing_key,
                    )
                )
            except Exception as exc:
                log.warning("skip url %s: %s", url, exc)
                continue
            time.sleep(sleep_s)

    return out
