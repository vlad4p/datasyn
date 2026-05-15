"""Infobae listing scrape helpers: URLs por fecha en path, markdown + MinIO."""

from __future__ import annotations

import re
import time
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

INF_BASE = "https://www.infobae.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# tema lógico → path de sección (coincide con URL Infobae)
SECTIONS: dict[str, str] = {
    "politica": f"{INF_BASE}/politica/",
    "judiciales": f"{INF_BASE}/judiciales/",
    "economia": f"{INF_BASE}/economia/",
}

# Máximo de enlaces por sección por corrida (evita runs enormes)
MAX_LINKS_PER_SECTION = int(__import__("os").environ.get("INFOBAE_MAX_LINKS_PER_SECTION", "120"))

log = logging.getLogger("datasyn.infobae")


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


def _date_path(d: date) -> str:
    return f"{d.year:04d}/{d.month:02d}/{d.day:02d}"


def _collect_article_urls_for_date(html: str, tema: str, day: date) -> list[str]:
    """Extrae URLs de notas cuyo path incluye /tema/YYYY/MM/DD/ (patrón Infobae)."""
    y, m, dd = day.year, day.month, day.day
    pattern = re.compile(
        rf'href=["\'](/{re.escape(tema)}/{y:04d}/{m:02d}/{dd:02d}/[^"\'#?]+)["\']',
        re.IGNORECASE,
    )
    found: set[str] = set()
    for mch in pattern.finditer(html):
        path = mch.group(1)
        if path.count("/") < 5:
            continue
        url = urljoin(INF_BASE, path)
        if url not in found:
            found.add(url)
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
    """Heurística: párrafos bajo article o contenedor principal."""
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
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", seg)[:120]


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
    """Descarga secciones, filtra notas del día por URL, extrae cuerpo."""
    date_path = _date_path(partition_day)
    out: list[ArticleDoc] = []
    with _http_client() as client:
        for tema, section_url in SECTIONS.items():
            r = client.get(section_url)
            r.raise_for_status()
            urls = _collect_article_urls_for_date(r.text, tema, partition_day)
            for url in urls:
                try:
                    ar = client.get(url)
                    ar.raise_for_status()
                    soup = BeautifulSoup(ar.text, "html.parser")
                    titulo = _extract_title(soup) or url
                    pub = _extract_published(
                        soup,
                        datetime(
                            partition_day.year,
                            partition_day.month,
                            partition_day.day,
                            tzinfo=timezone.utc,
                        ),
                    )
                    body = _extract_body_markdown(soup)
                    slug = _slug_from_url(url)
                    landing_key = f"landing/infobae/{tema}/{date_path}/{slug}.md"
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
            time.sleep(sleep_s)
    return out
