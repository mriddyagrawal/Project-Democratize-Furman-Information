"""Main entry point for the Furman people directory scraper.

Runs two stages then exports a clean CSV:
  1. Crawl listing pages to discover all people + profile URLs
  2. Scrape each profile page for contact details
  3. Export clean CSV: name, title, email, phone, office
"""

import csv
from pathlib import Path

from furman_directory.scrape_listing import main as scrape_listings
from furman_directory.scrape_profiles import main as scrape_profiles

HERE = Path(__file__).parent
CSV_OUTPUT = HERE / "data" / "furman_directory.csv"

CSV_COLUMNS = ["name", "title", "email", "phone", "office"]


def export_csv(profiles: list[dict]):
    """Write profiles to a clean CSV file."""
    CSV_OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    # Filter out entries with no name or completely empty records
    clean = [p for p in profiles if p.get("name")]

    # Sort alphabetically by last name (approximate: last word of name)
    clean.sort(key=lambda p: p["name"].split()[-1].lower() if p["name"] else "")

    with open(CSV_OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(clean)

    print(f"Exported {len(clean)} contacts to {CSV_OUTPUT}")


def main():
    print("=" * 60)
    print("Furman University People Directory Scraper")
    print("=" * 60)

    people = scrape_listings()
    print()
    profiles = scrape_profiles(people)
    print()
    export_csv(profiles)

    print("\n" + "=" * 60)
    print("All stages complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
