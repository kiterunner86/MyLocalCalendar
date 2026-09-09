"""
schema_org_ingest.py

The cleanest, lowest-legal-risk ingestion connector: parses JSON-LD
`schema.org/Event` markup that sites already publish for search engines
(the same markup Google's own "Events near you" feature reads). No
scraping-controversy here — this is data the site owner explicitly
published for machines to consume.

Talks to Supabase's REST API (PostgREST) directly over plain HTTP rather
than the `supabase-py` client library, which currently doesn't reliably
support Supabase's newer `sb_secret_...` / `sb_publishable_...` API key
format (it raises "Invalid API key" locally before making any request).
Plain REST calls with the key in the `apikey`/`Authorization` headers
avoid that entirely and add one less dependency.

Usage:
    python schema_org_ingest.py

Reads ingestion/sources.json for the list of source URLs to check,
fetches each page, extracts any Event objects from its JSON-LD blocks,
normalizes them, and upserts into Supabase.

Requires env vars (see .env.example):
    NEXT_PUBLIC_SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY   (service-role/secret key — this script
                                 writes data, so it must bypass RLS;
                                 never expose this key in frontend code)
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

SOURCES_FILE = os.path.join(os.path.dirname(__file__), "sources.json")

# A realistic browser header set. Several venue sites block the default
# "python-requests" user agent as a basic bot filter; this isn't spoofing
# a session or bypassing a login wall, just presenting like an ordinary
# browser visit to a public page — the same page schema.org markup was
# published for anyone (or anything) to read.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def get_supabase_config():
    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print(
            "Missing NEXT_PUBLIC_SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY "
            "env vars. Nothing will be written — running in dry-run mode.",
            file=sys.stderr,
        )
        return None
    return {
        "rest_url": f"{url}/rest/v1",
        "headers": {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
    }


def supabase_insert(config: dict, table: str, row: dict) -> dict | None:
    resp = requests.post(
        f"{config['rest_url']}/{table}",
        headers=config["headers"],
        json=row,
        timeout=20,
    )
    if not resp.ok:
        print(f"  Supabase insert into {table} failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        return None
    data = resp.json()
    return data[0] if isinstance(data, list) and data else None


def event_already_exists(config: dict, source_url: str) -> bool:
    """Simple dedup guard for the skeleton: skip if we've already stored
    this exact source URL. Real duplicate-matching across sources (title
    similarity, venue, date proximity) is a later layer, not this one."""
    resp = requests.get(
        f"{config['rest_url']}/events",
        headers=config["headers"],
        params={"source_url": f"eq.{source_url}", "select": "id"},
        timeout=20,
    )
    return resp.ok and len(resp.json()) > 0


def fetch(url: str) -> requests.Response | None:
    try:
        resp = requests.get(url, timeout=20, headers=BROWSER_HEADERS)
        resp.raise_for_status()
        return resp
    except requests.RequestException as exc:
        print(f"  Failed to fetch {url}: {exc}", file=sys.stderr)
        return None


def extract_json_ld_events(html: str) -> list[dict]:
    """Pull every schema.org Event object out of a page's JSON-LD blocks."""
    soup = BeautifulSoup(html, "html.parser")
    events = []

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            # @graph is a common wrapper pattern
            graph = item.get("@graph")
            pool = graph if isinstance(graph, list) else [item]
            for node in pool:
                if isinstance(node, dict) and _is_event_type(node.get("@type")):
                    events.append(node)

    return events


def _is_event_type(type_field) -> bool:
    if isinstance(type_field, str):
        return "Event" in type_field
    if isinstance(type_field, list):
        return any("Event" in t for t in type_field if isinstance(t, str))
    return False


def normalize_event(raw: dict, source_name: str, city: str) -> dict:
    """Map a schema.org Event object onto our internal event shape."""
    location = raw.get("location") or {}
    if isinstance(location, list):
        location = location[0] if location else {}
    address = location.get("address")
    if isinstance(address, dict):
        address = ", ".join(
            str(v) for v in address.values() if isinstance(v, str)
        )

    offers = raw.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}

    start = raw.get("startDate")
    try:
        start_dt = dateparser.parse(start).astimezone(timezone.utc).isoformat() if start else None
    except (ValueError, TypeError):
        start_dt = None

    return {
        "title": raw.get("name"),
        "description": raw.get("description"),
        "source_url": raw.get("url"),
        "venue_name": location.get("name"),
        "venue_address": address,
        "start_datetime": start_dt,
        "price": offers.get("price"),
        "booking_url": offers.get("url"),
        "image_reference": raw.get("image"),
        "source_name": source_name,
        "city": city,
        "raw": raw,
    }


def run():
    with open(SOURCES_FILE) as f:
        sources = json.load(f)

    config = get_supabase_config()
    total_found = 0

    for source in sources:
        print(f"Checking source: {source['name']} ({source['url']})")
        resp = fetch(source["url"])
        if resp is None:
            continue

        pages_to_check = [resp.text]

        # Many venue sites publish Event markup on each show's own page
        # rather than on the listing page itself. When a source declares
        # a link pattern to follow, discover those detail-page URLs from
        # the listing and fetch a bounded number of them too.
        link_pattern = source.get("follow_links_matching")
        if link_pattern:
            soup = BeautifulSoup(resp.text, "html.parser")
            detail_urls = []
            seen = set()
            for a in soup.find_all("a", href=True):
                href = urljoin(source["url"], a["href"])
                if re.search(link_pattern, href) and href not in seen:
                    seen.add(href)
                    detail_urls.append(href)

            max_pages = source.get("max_detail_pages", 20)
            detail_urls = detail_urls[:max_pages]
            print(f"  Following {len(detail_urls)} detail page(s) matching '{link_pattern}'.")

            for detail_url in detail_urls:
                detail_resp = fetch(detail_url)
                if detail_resp is not None:
                    pages_to_check.append(detail_resp.text)

        raw_events = []
        for html in pages_to_check:
            raw_events.extend(extract_json_ld_events(html))

        print(f"  Found {len(raw_events)} Event object(s) with schema.org markup.")
        total_found += len(raw_events)

        for raw_event in raw_events:
            normalized = normalize_event(raw_event, source["name"], source.get("city", "Dubai"))

            if not normalized["title"] or not normalized["start_datetime"]:
                print(f"  Skipping incomplete event: {normalized.get('title')}")
                continue

            if config is None:
                print(f"  [dry-run] Would upsert: {normalized['title']} @ {normalized['start_datetime']}")
                continue

            if normalized["source_url"] and event_already_exists(config, normalized["source_url"]):
                print(f"  Already stored, skipping: {normalized['title']}")
                continue

            # Minimal insert path for the skeleton: this does not yet do
            # venue normalization or duplicate matching against other
            # sources — that's the next layer to build once this pipeline
            # is proven end-to-end.
            event_row = {
                "title": normalized["title"],
                "description": normalized["description"],
                "category": "other",
                "source_url": normalized["source_url"],
                "booking_url": normalized["booking_url"],
                "image_reference": normalized["image_reference"],
                "status": "published",
                "last_verified_at": datetime.now(timezone.utc).isoformat(),
            }
            inserted = supabase_insert(config, "events", event_row)
            event_id = inserted["id"] if inserted else None

            if event_id and normalized["start_datetime"]:
                supabase_insert(
                    config,
                    "event_occurrences",
                    {
                        "event_id": event_id,
                        "start_datetime": normalized["start_datetime"],
                        "is_free": normalized["price"] in (None, "0", 0),
                        "price_min": normalized["price"],
                    },
                )
                print(f"  Inserted: {normalized['title']}")

    print(f"\nDone. {total_found} event object(s) found across {len(sources)} source(s).")


if __name__ == "__main__":
    run()
