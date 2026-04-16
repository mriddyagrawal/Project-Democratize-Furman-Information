"""Stage 1: Discover all organizations from Furman Engage API."""

import json
from pathlib import Path

import httpx

from shared.rate_limit import polite_delay, request_with_retry
from shared.text import clean_text, strip_html

BASE = "https://furman.campuslabs.com/engage/api/discovery/search/organizations"
PAGE_SIZE = 25
HERE = Path(__file__).parent
OUTPUT = HERE / "data" / "orgs.json"


def fetch_all_orgs() -> list[dict]:
    orgs = []
    skip = 0

    with httpx.Client(timeout=30) as client:
        while True:
            params = {
                "orderBy[0]": "UpperName asc",
                "top": str(PAGE_SIZE),
                "skip": str(skip),
                "filter": "",
                "query": "",
            }
            resp = request_with_retry(client, "GET", BASE, params=params)
            data = resp.json()

            items = data.get("value", [])
            if not items:
                break

            for item in items:
                orgs.append({
                    "name": item["Name"],
                    "short_name": item.get("ShortName", ""),
                    "slug": item["WebsiteKey"],
                    "status": item.get("Status", ""),
                    "visibility": item.get("Visibility", ""),
                    "category_names": item.get("CategoryNames", []),
                    "description": strip_html(item.get("Description", "")),
                    "summary": clean_text(item.get("Summary")),
                })

            print(f"  fetched {len(orgs)} orgs (skip={skip})")
            skip += PAGE_SIZE

    return orgs


def main():
    print("Stage 1: Discovering all organizations...")
    orgs = fetch_all_orgs()
    print(f"Found {len(orgs)} organizations total.")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(orgs, f, indent=2)
    print(f"Saved to {OUTPUT}")


if __name__ == "__main__":
    main()
