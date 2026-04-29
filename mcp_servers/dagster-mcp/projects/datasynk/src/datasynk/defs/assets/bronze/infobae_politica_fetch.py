"""Fetch Infobae política articles to a writable directory.

**Where files land**

1. Optional ``INFOBAE_OUTPUT_ROOT`` → ``{INFOBAE_OUTPUT_ROOT}/infobae/politica/<day>/``.
2. Else ``DATA_LOCAL_ROOT`` or ``/data-local/…`` if the mount is **read-write**.
3. Else ``{dirname(DUCKDB_PATH)}/scrapes/infobae/politica/<day>/`` (typically ``/data/scrapes/…``
   on the ``duckdb_data`` volume), because many stacks mount ``/data-local`` **read-only**
   on ``dagster_user_code``.

DuckDB / ``duckdb-mcp`` can ingest from ``/data/scrapes/…`` the same way as from
``/data-local/…`` when that path exists inside their container (same ``duckdb_data`` mount
at ``/data``).
"""

from __future__ import annotations

import errno
import json
import os
import re
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from dagster import MaterializeResult, asset

LISTING_URL = "https://www.infobae.com/politica/"
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
MAX_BODY_CHARS = 200_000


def _data_local_root() -> Path:
    raw = (os.environ.get("DATA_LOCAL_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path("/data-local")


def _duckdb_parent() -> Path:
    return Path(os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb")).expanduser().resolve().parent


def _output_rel_day(day: date) -> Path:
    return Path("infobae") / "politica" / day.isoformat()


def _probe_writable_dir(path: Path) -> None:
    """Raise ``OSError`` if *path* cannot be created or is not writable."""
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".dagster_write_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass


def _resolve_output_day_dir(day: date, context) -> tuple[Path, str]:
    """Pick first writable directory; mirrors ``variables_eph`` landing-zone vs DuckDB volume."""
    rel = _output_rel_day(day)

    explicit = (os.environ.get("INFOBAE_OUTPUT_ROOT") or "").strip()
    if explicit:
        path = Path(explicit).expanduser().resolve() / rel
        try:
            _probe_writable_dir(path)
            context.log.info("infobae_politica_fetch output (%s): %s", "INFOBAE_OUTPUT_ROOT", path)
            return path, "INFOBAE_OUTPUT_ROOT"
        except OSError as exc:
            raise OSError(
                f"INFOBAE_OUTPUT_ROOT is set but path is not writable: {path}"
            ) from exc

    candidates: list[tuple[Path, str]] = [
        (_data_local_root() / rel, "data-local"),
        (_duckdb_parent() / "scrapes" / rel, "duckdb_volume_scrapes"),
    ]

    last_exc: OSError | None = None
    for path, label in candidates:
        try:
            _probe_writable_dir(path)
            context.log.info("infobae_politica_fetch output (%s): %s", label, path)
            return path, label
        except OSError as exc:
            last_exc = exc
            if exc.errno in (errno.EROFS, errno.EACCES, errno.EPERM):
                context.log.warning(
                    "infobae output path not writable (%s): %s — %s", label, path, exc
                )
            else:
                context.log.warning("infobae output path failed (%s): %s — %s", label, path, exc)

    msg = "No writable directory for infobae scrape (tried data-local and DuckDB volume scrapes/). "
    msg += "Set INFOBAE_OUTPUT_ROOT or mount /data-local read-write on user-code."
    raise OSError(msg) from last_exc


def _scrape_day() -> date:
    """Folder name for this run (override with ``INFOBAE_POLITICA_DAY=YYYY-MM-DD``)."""
    s = (os.environ.get("INFOBAE_POLITICA_DAY") or "").strip()
    if s:
        y, m, d = (int(x) for x in s.split("-", 2))
        return date(y, m, d)
    return datetime.now(UTC).date()


def _lookback_days() -> int:
    return max(1, int(os.environ.get("INFOBAE_LOOKBACK_DAYS", "10")))


def _listing_max_pages() -> int:
    return max(1, int(os.environ.get("INFOBAE_LISTING_MAX_PAGES", "20")))


def _fetch_delay_s() -> float:
    return max(0.0, float(os.environ.get("INFOBAE_FETCH_DELAY_SECONDS", "0.35")))


def _max_articles() -> int | None:
    raw = (os.environ.get("INFOBAE_MAX_ARTICLES") or "").strip()
    if not raw:
        return None
    n = int(raw)
    return n if n > 0 else None


def _include_unknown_pubdate() -> bool:
    return (os.environ.get("INFOBAE_INCLUDE_UNKNOWN_DATE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _http_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": (os.environ.get("HTTP_USER_AGENT") or DEFAULT_UA).strip()},
        timeout=httpx.Timeout(45.0, connect=15.0),
        follow_redirects=True,
    )


def _is_politica_article_url(url: str) -> bool:
    try:
        p = urlparse(url)
    except Exception:
        return False
    if "infobae.com" not in (p.netloc or "").lower():
        return False
    segs = [s for s in (p.path or "").split("/") if s]
    try:
        i = next(j for j, s in enumerate(segs) if s.lower() == "politica")
    except StopIteration:
        return False
    if i + 4 >= len(segs):
        return False
    y, mo, d = segs[i + 1], segs[i + 2], segs[i + 3]
    if not (len(y) == 4 and y.isdigit() and mo.isdigit() and d.isdigit()):
        return False
    return True


def _collect_listing_hrefs(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[str] = []
    seen: set[str] = set()
    for tag in soup.find_all("a", href=True):
        full = urljoin(base_url, tag["href"])
        full = full.split("#")[0]
        if full in seen:
            continue
        if not _is_politica_article_url(full):
            continue
        seen.add(full)
        out.append(full)
    return out


_WS = re.compile(r"\s+")


def _meta_content(soup: BeautifulSoup, *, prop: str | None = None, name: str | None = None) -> str:
    for sel, val in (("property", prop), ("name", name)):
        if val is None:
            continue
        tag = soup.find("meta", attrs={sel: val})
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
    return ""


def _parse_datetime_loose(raw: str | None) -> datetime | None:
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        pass
    # Strip common GMT patterns
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except (ValueError, TypeError):
        return None


def _json_ld_blobs(soup: BeautifulSoup) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        if not script.string or not script.string.strip():
            continue
        try:
            data = json.loads(script.string)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            out.append(data)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    out.append(item)
    return out


def _author_from_json_ld(blocks: list[dict[str, Any]]) -> str:
    names: list[str] = []
    for b in blocks:
        t = (b.get("@type") or b.get("type") or "")
        types = t if isinstance(t, list) else [t]
        if "NewsArticle" not in types and "Article" not in types:
            continue
        auth = b.get("author")
        if isinstance(auth, dict):
            n = auth.get("name")
            if isinstance(n, str) and n.strip():
                names.append(n.strip())
        elif isinstance(auth, list):
            for a in auth:
                if isinstance(a, dict) and isinstance(a.get("name"), str):
                    names.append(a["name"].strip())
        elif isinstance(auth, str) and auth.strip():
            names.append(auth.strip())
    seen: set[str] = set()
    uniq = []
    for n in names:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return ", ".join(uniq)


def _dates_from_json_ld(blocks: list[dict[str, Any]]) -> tuple[datetime | None, datetime | None]:
    pub, mod = None, None
    for b in blocks:
        t = (b.get("@type") or b.get("type") or "")
        types = t if isinstance(t, list) else [t]
        if "NewsArticle" not in types and "Article" not in types:
            continue
        pub = pub or _parse_datetime_loose(b.get("datePublished"))
        mod = mod or _parse_datetime_loose(b.get("dateModified"))
    return pub, mod


def _byline_from_html(soup: BeautifulSoup) -> str:
    for sel in (
        "[class*='author']",
        "[class*='byline']",
        "a[href*='/perfil/']",
        "span[class*='author']",
    ):
        node = soup.select_one(sel)
        if node:
            t = _WS.sub(" ", node.get_text(" ", strip=True)).strip()
            if 3 < len(t) < 300:
                return t
    return ""


def _extract_article_fields(html: str, url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    ld = _json_ld_blobs(soup)

    title = _meta_content(soup, prop="og:title") or ""
    if not title:
        t = soup.find("title")
        if t and t.string:
            title = _WS.sub(" ", t.get_text()).strip()

    description = _meta_content(soup, prop="og:description") or _meta_content(
        soup, name="description"
    )

    author_meta = (
        _meta_content(soup, name="author")
        or _meta_content(soup, prop="article:author")
        or _author_from_json_ld(ld)
        or _byline_from_html(soup)
    )

    pub_ld, mod_ld = _dates_from_json_ld(ld)
    published_at = pub_ld or _parse_datetime_loose(_meta_content(soup, prop="article:published_time"))
    modified_at = mod_ld or _parse_datetime_loose(_meta_content(soup, prop="article:modified_time"))

    section = _meta_content(soup, prop="article:section") or ""

    body = ""
    art = soup.find("article")
    if art:
        body = _WS.sub(" ", art.get_text(" ", strip=True)).strip()
    if not body:
        for sel in ("div[class*='article']", "main"):
            node = soup.select_one(sel)
            if node:
                body = _WS.sub(" ", node.get_text(" ", strip=True)).strip()
                break
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS]

    pub_iso = (
        published_at.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if published_at
        else None
    )
    mod_iso = (
        modified_at.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if modified_at
        else None
    )

    return {
        "url": url,
        "title": title,
        "description": description,
        "author": author_meta,
        "section": section,
        "published_at": pub_iso,
        "modified_at": mod_iso,
        "body_text": body,
        "fetched_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def _listing_page_url(page: int) -> str:
    if page <= 1:
        return LISTING_URL
    sep = "&" if "?" in LISTING_URL else "?"
    return f"{LISTING_URL}{sep}page={page}"


def _gather_listing_urls(client: httpx.Client, context, max_pages: int) -> tuple[list[str], list[str]]:
    """Return (ordered unique article URLs, listing URLs fetched)."""
    seen: set[str] = set()
    ordered: list[str] = []
    listing_pages: list[str] = []
    for page in range(1, max_pages + 1):
        url = _listing_page_url(page)
        context.log.info("GET listing page %s", url)
        try:
            r = client.get(url)
            if r.status_code != 200:
                context.log.warning("listing page %s status %s", url, r.status_code)
                break
        except Exception as exc:
            context.log.warning("listing page failed %s: %s", url, exc)
            break
        listing_pages.append(url)
        batch = _collect_listing_hrefs(r.text, url)
        new_count = 0
        for u in batch:
            if u not in seen:
                seen.add(u)
                ordered.append(u)
                new_count += 1
        if page > 1 and new_count == 0:
            break
        time.sleep(_fetch_delay_s())
    return ordered, listing_pages


def _in_window(
    published_at: datetime | None,
    window_start: datetime,
    *,
    include_unknown: bool,
) -> bool:
    if published_at is None:
        return include_unknown
    return published_at >= window_start


@asset(
    name="infobae_politica_fetch",
    group_name="infobae",
    description=(
        "Scrape https://www.infobae.com/politica/ (paginated listing), fetch each article, "
        "extract title, author, dates, section, body; keep rows whose publication date falls in "
        "the last INFOBAE_LOOKBACK_DAYS (default 10). Writes JSONL + manifest under a writable "
        "path: INFOBAE_OUTPUT_ROOT, else data-local, else /data/scrapes/… next to warehouse."
    ),
)
def infobae_politica_fetch(context) -> MaterializeResult:
    day = _scrape_day()
    day_dir, output_kind = _resolve_output_day_dir(day, context)
    jsonl_path = day_dir / "articles.jsonl"
    manifest_path = day_dir / "manifest.json"

    delay = _fetch_delay_s()
    cap = _max_articles()
    lookback = _lookback_days()
    max_pages = _listing_max_pages()
    window_end = datetime.now(UTC)
    window_start = window_end - timedelta(days=lookback)
    include_unknown = _include_unknown_pubdate()

    with _http_client() as client:
        hrefs, listing_urls = _gather_listing_urls(client, context, max_pages)
        if cap is not None:
            hrefs = hrefs[:cap]

        manifest: dict[str, Any] = {
            "listing_urls": listing_urls,
            "scrape_run_day": day.isoformat(),
            "lookback_days": lookback,
            "window_start_utc": window_start.replace(microsecond=0).isoformat().replace(
                "+00:00", "Z"
            ),
            "window_end_utc": window_end.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "article_urls_found": len(hrefs),
            "include_unknown_publication_date": include_unknown,
            "output_dir": str(day_dir),
            "output_resolution": output_kind,
            "article_fetch_delay_seconds": delay,
            "data_local_note": (
                "If dagster_user_code mounts /data-local read-only, output falls back to "
                f"{_duckdb_parent() / 'scrapes' / _output_rel_day(day)} (ingest via read_json_auto "
                "with that path inside duckdb-mcp when /data is the same volume)."
            ),
            "errors": [],
            "filtered_out_old": 0,
        }

        ok = 0
        filtered = 0
        with jsonl_path.open("w", encoding="utf-8") as jf:
            for i, article_url in enumerate(hrefs):
                try:
                    context.log.info("article %s/%s GET %s", i + 1, len(hrefs), article_url)
                    ar = client.get(article_url)
                    ar.raise_for_status()
                    row = _extract_article_fields(ar.text, article_url)
                    row["listing_index"] = i
                    pub_raw = row.get("published_at")
                    pub_dt = _parse_datetime_loose(pub_raw) if pub_raw else None
                    if not _in_window(pub_dt, window_start, include_unknown=include_unknown):
                        filtered += 1
                        if delay > 0 and i + 1 < len(hrefs):
                            time.sleep(delay)
                        continue
                    jf.write(json.dumps(row, ensure_ascii=False) + "\n")
                    ok += 1
                except Exception as exc:  # noqa: BLE001
                    err = f"{type(exc).__name__}: {exc}"
                    context.log.warning("failed %s: %s", article_url, err)
                    manifest["errors"].append({"url": article_url, "error": err})
                if delay > 0 and i + 1 < len(hrefs):
                    time.sleep(delay)

        manifest["articles_written"] = ok
        manifest["filtered_out_old"] = filtered
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    return MaterializeResult(
        metadata={
            "output_resolution": output_kind,
            "output_dir": str(day_dir),
            "articles_jsonl": str(jsonl_path),
            "manifest": str(manifest_path),
            "urls_listed": len(hrefs),
            "rows_jsonl": ok,
            "filtered_outside_window": filtered,
            "lookback_days": lookback,
            "fetch_errors": len(manifest["errors"]),
        }
    )
