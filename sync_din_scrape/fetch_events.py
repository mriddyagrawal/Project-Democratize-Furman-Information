"""Fetch events from Furman Engage using authenticated session."""

import json
import time
from pathlib import Path

from dotenv import load_dotenv

from sync_din_scrape.auth import login
from shared.rate_limit import polite_delay

EVENTS_API = "https://furman.campuslabs.com/engage/api/discovery/event/search"
HERE = Path(__file__).parent
OUTPUT = HERE / "data" / "events.json"


def fetch_events():
    load_dotenv()

    context = login(headless=False)
    page = context.pages[0] if context.pages else context.new_page()

    print("Fetching events...")
    all_events = []
    skip = 0
    page_size = 25

    while True:
        url = (
            f"{EVENTS_API}"
            f"?orderByField=endsOn&orderByDirection=ascending"
            f"&status=Approved&top={page_size}&skip={skip}"
        )
        resp = page.request.get(url)

        if resp.status != 200:
            print(f"  Got status {resp.status}, stopping.")
            break

        data = resp.json()
        items = data.get("value", [])
        if not items:
            break

        for item in items:
            all_events.append({
                "id": item.get("Id"),
                "name": item.get("Name"),
                "description": item.get("Description", ""),
                "location": item.get("Location", ""),
                "starts_on": item.get("StartsOn", ""),
                "ends_on": item.get("EndsOn", ""),
                "org_name": item.get("OrganizationName", ""),
                "org_id": item.get("OrganizationId"),
                "category_names": item.get("CategoryNames", []),
                "theme": item.get("Theme", ""),
                "rsvp_enabled": item.get("RsvpEnabled", False),
            })

        print(f"  Fetched {len(all_events)} events (skip={skip})")
        skip += page_size
        polite_delay(0.5)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(all_events, f, indent=2)

    print(f"\nDone. Saved {len(all_events)} events to {OUTPUT}")
    context.close()


if __name__ == "__main__":
    fetch_events()
