"""
seed_dummy_event.py

Inserts one hardcoded, clearly-fake event straight into Supabase — no web
fetching involved. Purpose: verify the write path (Supabase REST + schema +
RLS + frontend rendering) works end-to-end, independent of whether any
given ingestion source can actually be reached. That's a separate, later
problem (see the Dubai Opera bot-protection issue) — this script exists to
isolate and confirm the other half of the pipeline right now.

Usage:
    python ingestion/seed_dummy_event.py

Requires the same env vars as schema_org_ingest.py:
    NEXT_PUBLIC_SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import requests

SUPABASE_URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SERVICE_KEY:
    print("Missing NEXT_PUBLIC_SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY.", file=sys.stderr)
    sys.exit(1)

HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def insert(table: str, row: dict) -> dict:
    resp = requests.post(f"{SUPABASE_URL}/rest/v1/{table}", headers=HEADERS, json=row, timeout=20)
    if not resp.ok:
        print(f"Insert into {table} failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        sys.exit(1)
    return resp.json()[0]


def main():
    event = insert(
        "events",
        {
            "title": "[TEST DATA] Sample Structure-Check Event",
            "description": "This is a placeholder event inserted to verify the pipeline structure, not a real event.",
            "category": "other",
            "source_url": "https://example.com/test-event",
            "booking_url": "https://example.com/book",
            "status": "published",
            "last_verified_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    print(f"Inserted event: {event['id']} - {event['title']}")

    start = datetime.now(timezone.utc) + timedelta(days=7)
    occurrence = insert(
        "event_occurrences",
        {
            "event_id": event["id"],
            "start_datetime": start.isoformat(),
            "is_free": False,
            "price_min": 100,
        },
    )
    print(f"Inserted occurrence: {occurrence['id']} - starts {occurrence['start_datetime']}")
    print("\nDone. Check the frontend or Supabase Table Editor to confirm it shows up.")


if __name__ == "__main__":
    main()
