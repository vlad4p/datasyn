---
name: web-scraping
description: >-
  Scrape websites and save results to data/landing for DuckDB ingestion.
  Use when the user asks to scrape, crawl, fetch web data, download HTML,
  or collect data from a URL.
---

# Web Scraping

## Principles

- **Respect robots.txt** and site terms of service
- **Rate limit** requests (≥1s between calls unless API allows otherwise)
- **Save raw data** to `data/landing/` before transforming
- **Prefer APIs** over HTML scraping when available

## Workflow

1. Check `robots.txt` and ToS
2. Fetch content (httpx + BeautifulSoup, or API client)
3. Save to landing: `data/landing/{source}_{date}.json` or `.csv`
4. Ingest into DuckDB with `ingest-data` skill

## Template script (save to `scripts/python/scrape_example.py`)

```python
"""Scrape example — adapt selectors and URL."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

import sys
from pathlib import Path
sys.path.insert(0, str(Path("scripts/python").resolve()))
import db
landing = db.get_landing_path()

HEADERS = {"User-Agent": "datasyn-local/0.1 (research; contact: local)"}


def scrape_listing(url: str) -> list[dict]:
    items: list[dict] = []
    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for el in soup.select("article"):
            title = el.select_one("h2")
            items.append({
                "title": title.get_text(strip=True) if title else None,
                "url": url,
                "scraped_at": datetime.now().isoformat(),
            })
            time.sleep(1)
    return items


def save_and_ingest(items: list[dict], name: str) -> Path:
    out = get_landing_path() / f"{name}_{datetime.now():%Y%m%d}.json"
    out.write_text(json.dumps(items, indent=2, ensure_ascii=False))
    return out
```

## Pagination pattern

```python
page = 1
while page <= max_pages:
    data = fetch_page(page)
    if not data:
        break
    all_items.extend(data)
    page += 1
    time.sleep(1.5)
```

## After scraping

```bash
# Then ask agent to ingest via skill ingest-data (SQL), e.g. read_json_auto → table source_articles
```

## Dependencies

Already in `pyproject.toml`: `httpx`, `beautifulsoup4`, `lxml`
