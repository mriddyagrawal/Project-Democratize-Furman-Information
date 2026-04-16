"""Main entry point for the syncDIN (Furman Engage) scraper.

Runs all three stages in sequence:
  1. Discover organizations
  2. Fetch document manifests
  3. Download all documents
"""

from sync_din_scrape.discover import main as discover
from sync_din_scrape.fetch_docs import main as fetch_docs
from sync_din_scrape.download import main as download


def main():
    print("=" * 60)
    print("syncDIN Scraper — Furman Engage Organizations & Documents")
    print("=" * 60)

    discover()
    print()
    fetch_docs()
    print()
    download()

    print("\n" + "=" * 60)
    print("All stages complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
