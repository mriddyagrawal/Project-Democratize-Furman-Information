"""Main entry point for the syncDIN (Furman Engage) scraper.

Runs in two stages:
  1. Discover organizations (sequential pagination)
  2. Fetch docs + download files (concurrent batches)
"""

from sync_din_scrape.discover import main as discover
from sync_din_scrape.fetch_and_download import main as fetch_and_download


def main():
    print("=" * 60)
    print("syncDIN Scraper — Furman Engage Organizations & Documents")
    print("=" * 60)

    discover()
    print()
    fetch_and_download()

    print("\n" + "=" * 60)
    print("All stages complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
