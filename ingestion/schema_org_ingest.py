"""
schema_org_ingest.py

The cleanest, lowest-legal-risk ingestion connector: parses JSON-LD
`schema.org/Event` markup that sites already publish for search engines
(the same markup Google's own "Events near you" feature reads). No
scraping-controversy here — this is data the site owner explicitly
published for machines to consume.

Usage:
    python schema_org_ingest.py

Reads ingestion/sources.json for the list of source URLs to check,
fetches each page, extracts any Event objects from its JSON-LD blocks,
normalizes them, and upserts into Supabase.

Requires env vars (see .env.example):
    NEXT_PUBLIC_SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY   (service role — this script writes data,
                                 so it must bypass RLS; never expose this
                                 key in frontend code)
"""

import json
import os
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from supabase import create_client, Client

SOURCES_FILE = os.path.join(os.path.dirname(__file__), "sources.json")


def get_supabase_client() -> Client:
    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print(
            "Missing NEXT_PUBLIC_SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY "
            "env vars. Nothing will be written — running in dry-run mode.",
            file=sys.stderr,
        )
        return None
    return create_client(url, key)


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

    supabase = get_supabase_client()
    total_found = 0

    for source in sources:
        print(f"Checking source: {source['name']} ({source['url']})")
        try:
            resp = requests.get(
                source["url"],
                timeout=20,
                headers={"User-Agent": "MyLocalCalendarBot/0.1 (+schema.org Event ingestion)"},
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"  Failed to fetch: {exc}", file=sys.stderr)
            continue

        raw_events = extract_json_ld_events(resp.text)
        print(f"  Found {len(raw_events)} Event object(s) with schema.org markup.")
        total_found += len(raw_events)

        for raw_event in raw_events:
            normalized = normalize_event(raw_event, source["name"], source.get("city", "Dubai"))

            if not normalized["title"] or not normalized["start_datetime"]:
                print(f"  Skipping incomplete event: {normalized.get('title')}")
                continue

            if supabase is None:
                print(f"  [dry-run] Would upsert: {normalized['title']} @ {normalized['start_datetime']}")
                continue

            # Minimal upsert path for the skeleton: this does not yet do
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
            result = supabase.table("events").insert(event_row).execute()
            event_id = result.data[0]["id"] if result.data else None

            if event_id and normalized["start_datetime"]:
                supabase.table("event_occurrences").insert(
                    {
                        "event_id": event_id,
                        "start_datetime": normalized["start_datetime"],
                        "is_free": normalized["price"] in (None, "0", 0),
                        "price_min": normalized["price"],
                    }
                ).execute()
                print(f"  Inserted: {normalized['title']}")

    print(f"\nDone. {total_found} event object(s) found across {len(sources)} source(s).")


if __name__ == "__main__":
    run()
