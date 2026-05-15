"""La Nación listing scrape: hubs por sección, filtro por fecha en sufijo ``-nidDDMMYYYY``."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

LN_BASE = "https://www.lanacion.com.ar"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# tema lógico → URL del listado. ``judiciales`` usa el hub ``/seguridad/`` (no existe ``/judiciales/`` en LN).
SECTIONS: dict[str, str] = {
    "politica": f"{LN_BASE}/politica/",
    "economia": f"{LN_BASE}/economia/",
    "editoriales": f"{LN_BASE}/editoriales/",
    "buenos-aires": f"{LN_BASE}/buenos-aires/",
    "judiciales": f"{LN_BASE}/seguridad/",
}

MAX_LINKS_PER_SECTION = int(__import__("os").environ.get("LANACION_MAX_LINKS_PER_SECTION", "120"))

log = logging.getLogger("datasyn.lanacion")


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


def _path_prefix_from_hub_url(hub_url: str) -> str:
    path = urlparse(hub_url).path.strip("/")
    return path.split("/")[0] if path else ""


def _parse_nid_date_from_path(path: str) -> date | None:
    m = re.search(r"-nid(\d{8})/?", path.rstrip("/"))
    if not m:
        return None
    s = m.group(1)
    try:
        dd, mo, yyyy = int(s[0:2]), int(s[2:4]), int(s[4:8])
        return date(yyyy, mo, dd)
    except ValueError:
        return None


def _collect_article_urls_for_day(html: str, section_path: str, partition_day: date) -> list[str]:
    """Enlaces a notas ``/{section_path}/...-nidDDMMYYYY/`` cuya fecha NID coincide con ``partition_day``."""
    pattern = re.compile(
        rf'href=["\'](/{re.escape(section_path)}/[^"\'#?]+-nid\d{{8}}/)["\']',
        re.IGNORECASE,
    )
    found: set[str] = set()
    for mch in pattern.finditer(html):
        rel = mch.group(1)
        if _parse_nid_date_from_path(rel) != partition_day:
            continue
        url = urljoin(LN_BASE, rel)
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
    """Descarga hubs por sección, filtra notas del día vía ``-nidDDMMYYYY``, extrae cuerpo."""
    date_path = _date_path(partition_day)
    url_to_tema: dict[str, str] = {}

    with _http_client() as client:
        for tema, hub_url in SECTIONS.items():
            section_path = _path_prefix_from_hub_url(hub_url)
            if not section_path:
                continue
            r = client.get(hub_url)
            r.raise_for_status()
            for u in _collect_article_urls_for_day(r.text, section_path, partition_day):
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
                body = _extract_body_markdown(soup)
                slug = _slug_from_url(url)
                landing_key = f"landing/lanacion/{tema}/{date_path}/{slug}.md"
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
