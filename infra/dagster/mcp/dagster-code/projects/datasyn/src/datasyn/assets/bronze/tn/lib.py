"""TN scrape helpers: hubs tecno, política, economía y opinión.

Patrones de URL por sección:

- ``tecno``: ``/tecno/<rubro>/YYYY/MM/DD/<slug>/``
- ``politica`` | ``economia`` | ``opinion``: ``/<sección>/YYYY/MM/DD/<slug>/``
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

TN_BASE = "https://tn.com.ar"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# tema lógico → URL del hub
SECTIONS: dict[str, str] = {
    "tecno": f"{TN_BASE}/tecno/",
    "politica": f"{TN_BASE}/politica/",
    "economia": f"{TN_BASE}/economia/",
    "opinion": f"{TN_BASE}/opinion/",
}

MAX_LINKS_PER_SECTION = int(os.environ.get("TN_MAX_LINKS_PER_SECTION", "120"))

log = logging.getLogger("datasyn.tn")


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


def _normalize_article_url(href: str, tema: str) -> str | None:
    href = href.strip().split("#")[0].split("?")[0]
    if not href:
        return None
    full = urljoin(TN_BASE, href)
    parsed = urlparse(full)
    if parsed.netloc.lower() not in ("tn.com.ar", "www.tn.com.ar"):
        return None
    path = parsed.path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    if tema == "tecno":
        # /tecno/<rubro>/YYYY/MM/DD/<slug>
        if len(parts) < 6 or parts[0] != "tecno":
            return None
        y, mo, d = parts[2], parts[3], parts[4]
    else:
        # /politica|economia|opinion/YYYY/MM/DD/<slug>
        if len(parts) < 5 or parts[0] != tema:
            return None
        y, mo, d = parts[1], parts[2], parts[3]
    try:
        int(y), int(mo), int(d)
    except ValueError:
        return None
    return f"{TN_BASE}{path}/"


def _href_pattern_for_section(tema: str, path_date: str) -> re.Pattern[str]:
    if tema == "tecno":
        return re.compile(
            rf'href=["\']([^"\']*?/tecno/[^/]+{re.escape(path_date)}[^"\'#?]+)["\']',
            re.IGNORECASE,
        )
    return re.compile(
        rf'href=["\']([^"\']*?/{re.escape(tema)}{re.escape(path_date)}[^"\'#?]+)["\']',
        re.IGNORECASE,
    )


def _itemlist_urls(data: object) -> list[str]:
    if isinstance(data, dict):
        items = data.get("ItemListElement") or data.get("itemListElement") or []
        return [str(u) for it in items if isinstance(it, dict) and (u := it.get("url"))]
    if isinstance(data, list):
        out: list[str] = []
        for block in data:
            out.extend(_itemlist_urls(block))
        return out
    return []


def _collect_article_urls_for_date(html: str, day: date, tema: str) -> list[str]:
    """Enlaces del día en el hub (href + JSON-LD ItemList)."""
    y, m, dd = day.year, day.month, day.day
    path_date = f"/{y:04d}/{m:02d}/{dd:02d}/"
    pattern = _href_pattern_for_section(tema, path_date)
    found: set[str] = set()
    for mch in pattern.finditer(html):
        url = _normalize_article_url(mch.group(1), tema)
        if url:
            found.add(url)
        if len(found) >= MAX_LINKS_PER_SECTION:
            break

    for script in BeautifulSoup(html, "html.parser").find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text() or ""
        if "ItemList" not in raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for url_raw in _itemlist_urls(data):
            url = _normalize_article_url(url_raw, tema)
            if url and path_date in urlparse(url).path:
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
    """Descarga hubs TN, filtra notas del día por fecha en URL, extrae cuerpo."""
    date_path = _date_path(partition_day)
    out: list[ArticleDoc] = []
    seen_urls: set[str] = set()
    fallback = datetime(
        partition_day.year,
        partition_day.month,
        partition_day.day,
        tzinfo=timezone.utc,
    )
    with _http_client() as client:
        for tema, section_url in SECTIONS.items():
            r = client.get(section_url)
            r.raise_for_status()
            urls = _collect_article_urls_for_date(r.text, partition_day, tema)
            for url in urls:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                try:
                    ar = client.get(url)
                    ar.raise_for_status()
                    soup = BeautifulSoup(ar.text, "html.parser")
                    titulo = _extract_title(soup) or url
                    pub = _extract_published(soup, fallback)
                    body = _extract_body_markdown(soup)
                    slug = _slug_from_url(url)
                    landing_key = f"landing/tn/{tema}/{date_path}/{slug}.md"
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
