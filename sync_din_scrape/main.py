"""Main entry point for the syncDIN (Furman Engage) scraper.

Runs in three stages:
  1. Discover organizations (sequential pagination)
  2. Fetch docs + download files (concurrent batches, recursive folders)
  3. Fetch all events and save per-org
"""

from sync_din_scrape.discover import main as discover
from sync_din_scrape.fetch_and_download import main as fetch_and_download
from sync_din_scrape.fetch_events import main as fetch_events


def main():
    print("=" * 60)
    print("syncDIN Scraper — Furman Engage Organizations & Documents")
    print("=" * 60)

    discover()
    print()
    fetch_and_download()
    print()
    fetch_events()

    print("\n" + "=" * 60)
    print("All stages complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
