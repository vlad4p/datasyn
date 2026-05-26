"""OECD AI incidents scrape helpers.

The partition date is interpreted as the OECD AIM incident date. The result
page is used to discover incident IDs for Argentina on that day, then the
public OECD incident API is used to retrieve the full structured incident JSON.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import urlencode, urljoin

import httpx
from bs4 import BeautifulSoup

OECD_BASE = "https://oecd.ai"
OECD_INCIDENTS_PAGE = f"{OECD_BASE}/en/incidents"
OECD_INCIDENT_API_BASE = "https://incidents-server.oecdai.org/api/v1/incidents"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_COUNTRY = os.environ.get("OECD_AI_INCIDENTS_COUNTRY", "ARG").strip() or "ARG"
MAX_INCIDENTS_PER_DAY = int(os.environ.get("OECD_AI_INCIDENTS_MAX_RESULTS", "100"))

PROPERTIES_CONFIG: dict[str, list[str]] = {
    "principles": [],
    "industries": [],
    "harm_types": [],
    "harm_levels": [],
    "harmed_entities": [],
    "business_functions": [],
    "ai_tasks": [],
    "autonomy_levels": [],
    "languages": [],
}

INCIDENT_PATH_RE = re.compile(
    r"(?:https://oecd\.ai)?/?en/incidents/(\d{4}-\d{2}-\d{2}-[A-Za-z0-9]+)"
)

log = logging.getLogger("datasyn.oecd_ai_incidents")


@dataclass(frozen=True)
class IncidentDoc:
    incident_id: str
    title: str
    incident_date: date | None
    url: str
    landing_key: str
    payload: dict[str, Any]


def _http_client() -> httpx.Client:
    return httpx.Client(
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/json",
            "Accept-Language": "en-US,en;q=0.9,es-AR;q=0.8,es;q=0.7",
        },
        timeout=httpx.Timeout(45.0),
        follow_redirects=True,
    )


def _date_path(d: date) -> str:
    return f"{d.year:04d}/{d.month:02d}/{d.day:02d}"


def _incident_url(incident_id: str) -> str:
    return f"{OECD_BASE}/en/incidents/{incident_id}"


def _incident_api_url(incident_id: str) -> str:
    return f"{OECD_INCIDENT_API_BASE}/{incident_id}"


def landing_key_for_incident(partition_day: date, incident_id: str) -> str:
    return f"landing/oecd_ai_incidents/{_date_path(partition_day)}/{incident_id}.json"


def build_search_url(partition_day: date, *, country: str = DEFAULT_COUNTRY) -> str:
    params = {
        "search_terms": "[]",
        "and_condition": "false",
        "countries": country,
        "from_date": partition_day.isoformat(),
        "to_date": partition_day.isoformat(),
        "properties_config": json.dumps(PROPERTIES_CONFIG, separators=(",", ":")),
        "order_by": "date",
        "num_results": str(MAX_INCIDENTS_PER_DAY),
    }
    return f"{OECD_INCIDENTS_PAGE}?{urlencode(params)}"


def incident_ids_from_search_html(html: str, partition_day: date) -> list[str]:
    """Extract incident IDs from the SSR result page, preserving page order."""
    found: list[str] = []
    seen: set[str] = set()
    day_prefix = partition_day.isoformat()

    soup = BeautifulSoup(html, "html.parser")
    hrefs = [str(a.get("href") or "") for a in soup.find_all("a")]
    hrefs.extend(m.group(0) for m in INCIDENT_PATH_RE.finditer(html))

    for href in hrefs:
        full = urljoin(OECD_BASE, href)
        match = INCIDENT_PATH_RE.search(full)
        if not match:
            continue
        incident_id = match.group(1)
        if not incident_id.startswith(day_prefix) or incident_id in seen:
            continue
        seen.add(incident_id)
        found.append(incident_id)

    return found


def fetch_incident_ids_for_partition(
    client: httpx.Client,
    partition_day: date,
    *,
    country: str = DEFAULT_COUNTRY,
) -> list[str]:
    url = build_search_url(partition_day, country=country)
    response = client.get(url)
    response.raise_for_status()
    ids = incident_ids_from_search_html(response.text, partition_day)
    return ids[:MAX_INCIDENTS_PER_DAY]


def fetch_incident_json(client: httpx.Client, incident_id: str) -> dict[str, Any]:
    response = client.get(_incident_api_url(incident_id), headers={"Accept": "application/json"})
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected OECD incident API response for {incident_id}: {type(data)!r}")
    return data


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _related_articles(raw: dict[str, Any]) -> list[dict[str, Any]]:
    related: list[dict[str, Any]] = []
    for article in _as_list(raw.get("articles")):
        if not isinstance(article, dict):
            continue
        title = str(article.get("title") or "").strip()
        url = str(article.get("url") or "").strip()
        related.append(
            {
                "name": title,
                "title": title,
                "url": url,
                "date": article.get("date"),
                "publisher": article.get("publisher"),
                "country": article.get("country"),
                "evidences": _as_list(article.get("evidences")),
                "image": article.get("image"),
                "thumb_image": article.get("thumbImage"),
                "concepts": _as_list(article.get("concepts")),
            }
        )
    return related


def structure_incident_json(raw: dict[str, Any], *, scraped_at: datetime) -> dict[str, Any]:
    incident_id = str(raw.get("id") or "").strip()
    if not incident_id:
        raise ValueError("OECD incident JSON is missing id")

    properties = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
    evidences = [str(v).strip() for v in _as_list(raw.get("evidences")) if str(v).strip()]

    return {
        "incident_id": incident_id,
        "title": str(raw.get("title") or "").strip(),
        "url": _incident_url(incident_id),
        "api_url": _incident_api_url(incident_id),
        "incident_date": raw.get("date"),
        "location": raw.get("location"),
        "summary": raw.get("summary"),
        "monitor_reason": "\n\n".join(evidences),
        "evidences": evidences,
        "image": raw.get("image"),
        "company": raw.get("company"),
        "concepts": _as_list(raw.get("concepts")),
        "properties": properties,
        "ai_principles": _as_list(properties.get("principles")),
        "industries": _as_list(properties.get("industries")),
        "affected_stakeholders": _as_list(properties.get("harmed_entities")),
        "harm_types": _as_list(properties.get("harm_types")),
        "severity": _as_list(properties.get("harm_levels")),
        "business_functions": _as_list(properties.get("business_functions")),
        "ai_system_tasks": _as_list(properties.get("ai_tasks")),
        "autonomy_level": properties.get("autonomy_level"),
        "languages": _as_list(properties.get("languages")),
        "aiid_ids": _as_list(raw.get("aiid_ids")),
        "language_counts": raw.get("language_counts") or {},
        "is_legacy": raw.get("is_legacy"),
        "article_count": raw.get("n_articles") or len(_as_list(raw.get("articles"))),
        "related_articles": _related_articles(raw),
        "raw": raw,
        "scraped_at": scraped_at.isoformat(),
    }


def scrape_incidents_for_partition(
    *,
    partition_day: date,
    scraped_at: datetime,
    country: str = DEFAULT_COUNTRY,
    sleep_s: float | None = None,
) -> list[IncidentDoc]:
    """Fetch all OECD AIM incidents for Argentina on the partition date."""
    wait = float(os.environ.get("OECD_AI_INCIDENTS_SLEEP_S", "0.25")) if sleep_s is None else sleep_s
    out: list[IncidentDoc] = []

    with _http_client() as client:
        incident_ids = fetch_incident_ids_for_partition(client, partition_day, country=country)
        for incident_id in incident_ids:
            try:
                raw = fetch_incident_json(client, incident_id)
                payload = structure_incident_json(raw, scraped_at=scraped_at)
                out.append(
                    IncidentDoc(
                        incident_id=incident_id,
                        title=str(payload.get("title") or incident_id),
                        incident_date=date.fromisoformat(str(payload["incident_date"]))
                        if payload.get("incident_date")
                        else None,
                        url=str(payload.get("url") or _incident_url(incident_id)),
                        landing_key=landing_key_for_incident(partition_day, incident_id),
                        payload=payload,
                    )
                )
            except Exception as exc:
                log.warning("skip OECD incident %s: %s", incident_id, exc)
                continue
            time.sleep(wait)

    return out
