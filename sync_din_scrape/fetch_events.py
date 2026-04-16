"""Fetch all events from Furman Engage and save per-org.

Uses the public discovery API (no auth required).
Each org's events are saved as events.json inside its data/orgs/<slug>/ folder.
A combined events.json is also saved at data/events.json.
"""

import csv
import json
from collections import defaultdict
from pathlib import Path

import httpx

from shared.rate_limit import polite_delay, request_with_retry
from shared.text import clean_text, strip_html

EVENTS_API = "https://furman.campuslabs.com/engage/api/discovery/event/search"
PAGE_SIZE = 100
HERE = Path(__file__).parent
ORGS_FILE = HERE / "data" / "orgs.json"
ORGS_DIR = HERE / "data" / "orgs"
OUTPUT = HERE / "data" / "events.json"
CSV_OUTPUT = HERE / "data" / "events.csv"

CSV_COLUMNS = [
    "name", "org_name", "starts_on", "ends_on",
    "location", "categories", "theme", "description",
]


def _clean_event(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "name": clean_text(item.get("name")),
        "description": strip_html(item.get("description", "")),
        "location": clean_text(item.get("location", "")),
        "starts_on": item.get("startsOn", ""),
        "ends_on": item.get("endsOn", ""),
        "org_name": clean_text(item.get("organizationName", "")),
        "org_id": item.get("organizationId"),
        "category_names": item.get("categoryNames") or [],
        "theme": item.get("theme", ""),
        "visibility": item.get("visibility", ""),
    }


def fetch_all_events() -> list[dict]:
    """Paginate through the events API and return all events."""
    all_events = []
    skip = 0

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        while True:
            resp = request_with_retry(
                client, "GET", EVENTS_API,
                params={
                    "orderByField": "endsOn",
                    "orderByDirection": "descending",
                    "status": "Approved",
                    "top": str(PAGE_SIZE),
                    "skip": str(skip),
                },
            )
            data = resp.json()
            items = data.get("value", [])
            if not items:
                break

            for item in items:
                all_events.append(_clean_event(item))

            total = data.get("@odata.count", "?")
            print(f"  Fetched {len(all_events)}/{total} events")
            skip += PAGE_SIZE
            polite_delay(0.3)

    return all_events


def _build_org_id_to_slug() -> dict[int, str]:
    """Map org IDs to slugs using orgs.json and profile.json files."""
    mapping = {}

    # First try profile.json files which have the numeric id
    if ORGS_DIR.exists():
        for profile_path in ORGS_DIR.glob("*/profile.json"):
            with open(profile_path) as f:
                profile = json.load(f)
            org_id = profile.get("id")
            if org_id:
                mapping[int(org_id)] = profile_path.parent.name

    return mapping


def save_per_org(events: list[dict], id_to_slug: dict[int, str]):
    """Group events by org and save events.json in each org folder."""
    by_org: dict[int, list[dict]] = defaultdict(list)
    unmatched = 0

    for event in events:
        org_id = event.get("org_id")
        if org_id:
            by_org[org_id].append(event)

    saved = 0
    for org_id, org_events in by_org.items():
        slug = id_to_slug.get(org_id)
        if not slug:
            unmatched += len(org_events)
            continue

        org_dir = ORGS_DIR / slug
        org_dir.mkdir(parents=True, exist_ok=True)

        out_path = org_dir / "events.json"
        with open(out_path, "w") as f:
            json.dump(org_events, f, indent=2)
        saved += 1

    print(f"  Saved events for {saved} orgs ({unmatched} events had no matching org slug)")


def export_csv(events: list[dict]):
    """Write a clean CSV of all events."""
    CSV_OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    with open(CSV_OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for event in events:
            row = {
                "name": event["name"],
                "org_name": event["org_name"],
                "starts_on": event["starts_on"],
                "ends_on": event["ends_on"],
                "location": event["location"],
                "categories": "; ".join(event.get("category_names") or []),
                "theme": event["theme"],
                "description": event["description"],
            }
            writer.writerow(row)

    print(f"Exported {len(events)} events to {CSV_OUTPUT}")


def main():
    print("Fetching all Furman Engage events...")
    events = fetch_all_events()
    print(f"Found {len(events)} events total.")

    # Save combined JSON
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(events, f, indent=2)
    print(f"Saved combined events to {OUTPUT}")

    # Save clean CSV
    export_csv(events)

    # Save per-org
    id_to_slug = _build_org_id_to_slug()
    if id_to_slug:
        save_per_org(events, id_to_slug)
    else:
        print("  No org ID→slug mapping found (run discover + fetch_and_download first)")


if __name__ == "__main__":
    main()
