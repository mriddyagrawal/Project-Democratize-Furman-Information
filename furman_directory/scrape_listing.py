"""Stage 1: Crawl all pages of the Furman people directory to collect profile URLs.

Paginates through https://www.furman.edu/people/page/{N}/ and extracts
each person's name, subtitle (title/role shown on listing), and profile URL.
"""

import json
import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from shared.rate_limit import polite_delay, request_with_retry
from shared.text import clean_text

BASE_URL = "https://www.furman.edu/people/"
HERE = Path(__file__).parent
OUTPUT = HERE / "data" / "people_urls.json"


def _page_url(page_num: int) -> str:
    if page_num <= 1:
        return BASE_URL
    return f"{BASE_URL}page/{page_num}/"


def _name_from_slug(url: str) -> str:
    """Derive a fallback name from the profile URL slug."""
    # e.g. https://www.furman.edu/people/caro-douglas-2/ -> "Caro Douglas"
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    # Strip trailing numbers (e.g. "caro-douglas-2" -> "caro-douglas")
    slug = re.sub(r"-\d+$", "", slug)
    return slug.replace("-", " ").title()


def _parse_listing_page(html: str) -> list[dict]:
    """Extract people entries from a single listing page."""
    soup = BeautifulSoup(html, "html.parser")
    people = []

    for card in soup.select("div.module-content-block-people-group-item"):
        link_tag = card.select_one("a[href*='/people/']")
        if not link_tag:
            continue

        profile_url = link_tag.get("href", "")
        if not profile_url.startswith("http"):
            profile_url = "https://www.furman.edu" + profile_url

        # Name from the h2
        name_tag = card.select_one(
            "h2.module-content-block-people-group-item-contents-name"
        )
        name = clean_text(name_tag.get_text(" ", strip=True)) if name_tag else ""

        # Fallback: derive name from URL slug
        if not name:
            name = _name_from_slug(profile_url)

        # Title / role shown on the listing card
        title_tag = card.select_one(
            "div.module-content-block-people-group-item-contents-title"
        )
        listing_title = clean_text(title_tag.get_text(strip=True)) if title_tag else ""

        people.append({
            "name": name,
            "listing_title": listing_title,
            "profile_url": profile_url,
        })

    return people


def _detect_max_pages(html: str) -> int:
    """Find the last page number from pagination links."""
    soup = BeautifulSoup(html, "html.parser")
    max_page = 1
    for a_tag in soup.select("a.page-numbers, a[href*='/people/page/']"):
        href = a_tag.get("href", "")
        text = a_tag.get_text(strip=True)
        if text.isdigit():
            max_page = max(max_page, int(text))
    return max_page


def scrape_all_listings() -> list[dict]:
    """Crawl every page of the people directory and return all entries."""
    all_people = []

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        # Fetch page 1 to detect total pages
        print("  Fetching page 1 to detect pagination...")
        resp = request_with_retry(client, "GET", _page_url(1))
        max_pages = _detect_max_pages(resp.text)
        print(f"  Detected {max_pages} pages.")

        page_people = _parse_listing_page(resp.text)
        all_people.extend(page_people)
        print(f"  Page 1: {len(page_people)} people")

        for page_num in range(2, max_pages + 1):
            resp = request_with_retry(client, "GET", _page_url(page_num))
            page_people = _parse_listing_page(resp.text)
            all_people.extend(page_people)

            if page_num % 10 == 0 or page_num == max_pages:
                print(f"  Page {page_num}/{max_pages}: {len(all_people)} people total")

    return all_people


def main():
    print("Stage 1: Scraping people directory listings...")
    people = scrape_all_listings()
    print(f"Found {len(people)} people across all pages.")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(people, f, indent=2)
    print(f"Saved to {OUTPUT}")

    return people


if __name__ == "__main__":
    main()
