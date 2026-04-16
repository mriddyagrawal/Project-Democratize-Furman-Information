"""Scrape Cultural Life Program (CLP) events from Furman's 25Live calendar.

The CLP calendar is powered by 25Live (CollegeNet) which exposes a JSON API.
We fetch the last 3 months of events and extract: name, date, description.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from shared.text import clean_text, strip_html

CALENDAR_API = "https://25livepub.collegenet.com/calendars/clp.json"
HERE = Path(__file__).parent
OUTPUT_DIR = HERE / "data"
MONTHS_BACK = 3
MONTHS_FORWARD = 3


def fetch_clp_events() -> list[dict]:
    today = datetime.now()
    start = today - timedelta(days=MONTHS_BACK * 30)
    end = today + timedelta(days=MONTHS_FORWARD * 30)

    start_str = start.strftime("%Y%m%d")
    end_str = end.strftime("%Y%m%d")

    print(f"Fetching CLP events from {start_str} to {end_str} ...")

    with httpx.Client(timeout=30) as client:
        resp = client.get(CALENDAR_API, params={
            "startdate": start_str,
            "enddate": end_str,
        })
        resp.raise_for_status()
        raw_events = resp.json()

    print(f"  Got {len(raw_events)} raw events from API")

    events = []
    for item in raw_events:
        if item.get("canceled"):
            continue

        events.append({
            "name": clean_text(item.get("title", "")),
            "date": clean_text(item.get("dateTimeFormatted", "")),
            "description": strip_html(item.get("description") or ""),
            "_sort_key": item.get("startDateTime", ""),
        })

    events.sort(key=lambda e: e["_sort_key"])
    for e in events:
        del e["_sort_key"]
    return events


def main():
    events = fetch_clp_events()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / "events.json"
    with open(output_file, "w") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)

    print(f"\nDone. {len(events)} events saved to {output_file}")

    # Quick preview
    for e in events[:5]:
        print(f"  {e['date']:40s} | {e['name'][:50]}")
    if len(events) > 5:
        print(f"  ... and {len(events) - 5} more")


if __name__ == "__main__":
    main()
