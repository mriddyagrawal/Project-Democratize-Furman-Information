"""Stage 2: Scrape individual profile pages for contact details.

Uses Playwright async API with 3 parallel pages — faster than sequential,
gentle enough to avoid rate limits.
"""

import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright, Page
from shared.text import clean_text

HERE = Path(__file__).parent
INPUT = HERE / "data" / "people_urls.json"
OUTPUT = HERE / "data" / "people_profiles.json"
WORKERS = 3


async def _extract_profile(page: Page, url: str, listing_title: str) -> dict:
    """Navigate to a profile URL and extract contact info."""
    try:
        await page.goto(url, wait_until="networkidle", timeout=30_000)
        await page.wait_for_timeout(800)
    except Exception:
        return {
            "name": "", "title": clean_text(listing_title), "email": "",
            "phone": "", "office": "", "profile_url": url,
        }

    email = ""
    mailto = await page.query_selector('a[href^="mailto:"]')
    if mailto:
        href = await mailto.get_attribute("href") or ""
        email = href.replace("mailto:", "").strip()

    phone = ""
    tel = await page.query_selector('a[href^="tel:"]')
    if tel:
        phone = (await tel.inner_text()).strip()

    name = ""
    for sel in ["article h2", ".entry-content h2", "main h2", "h1.entry-title", "h1"]:
        el = await page.query_selector(sel)
        if el:
            name = clean_text(await el.inner_text())
            break

    title = ""
    for sel in ["article h4", ".entry-content h4", "main h4",
                ".person-title", ".entry-subtitle", ".profile-title"]:
        el = await page.query_selector(sel)
        if el:
            title = clean_text(await el.inner_text())
            break
    if not title:
        title = clean_text(listing_title)

    office = ""
    for li in await page.query_selector_all("main li"):
        text = (await li.inner_text()).strip()
        if text.lower().startswith("office:"):
            office = text.split(":", 1)[1].strip()
            break

    # Fallback: extract affiliation from bio text ("at the Riley Institute", etc.)
    department = ""
    bio_els = await page.query_selector_all("main p")
    for el in bio_els[:3]:
        bio_text = (await el.inner_text()).strip()
        if bio_text and len(bio_text) > 20:
            matches = re.findall(
                r"(?:at|in|of|for|with) the ([A-Z][^,.]{3,50}?"
                r"(?:Institute|Department|Center|Office|School|College|Program|Lab|Laboratory|Library|Clinic))",
                bio_text,
            )
            if matches:
                department = matches[0].strip()
                break

    return {
        "name": name, "title": title, "email": email,
        "phone": phone, "office": clean_text(office),
        "department": clean_text(department), "profile_url": url,
    }


async def _worker(
    page: Page, queue: asyncio.Queue,
    results: list, counter: dict, total: int,
):
    """Worker: pull items from queue, scrape each one."""
    while True:
        try:
            idx, person = queue.get_nowait()
        except asyncio.QueueEmpty:
            return

        profile = await _extract_profile(
            page, person["profile_url"], person.get("listing_title", "")
        )
        # Fall back to listing name if profile page didn't have one
        if not profile["name"] and person.get("name"):
            profile["name"] = clean_text(person["name"])
        results[idx] = profile
        counter["done"] += 1
        done = counter["done"]

        if done % 25 == 0 or done == total:
            with_email = sum(1 for p in results if p and p.get("email"))
            print(f"  Scraped {done}/{total} profiles ({with_email} with emails)")

        queue.task_done()


async def _run(people: list[dict]) -> list[dict]:
    total = len(people)
    results = [None] * total
    counter = {"done": 0}

    queue: asyncio.Queue = asyncio.Queue()
    for i, person in enumerate(people):
        queue.put_nowait((i, person))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel="chrome", headless=True)

        pages = []
        for _ in range(WORKERS):
            ctx = await browser.new_context()
            pages.append(await ctx.new_page())

        workers = [_worker(page, queue, results, counter, total) for page in pages]
        await asyncio.gather(*workers)

        await browser.close()

    return [p for p in results if p]


def scrape_all_profiles(people: list[dict] | None = None) -> list[dict]:
    if people is None:
        with open(INPUT) as f:
            people = json.load(f)
    return asyncio.run(_run(people))


def main(people: list[dict] | None = None):
    print(f"Stage 2: Scraping profile pages ({WORKERS} parallel tabs)...")
    profiles = scrape_all_profiles(people)
    print(f"Scraped {len(profiles)} profiles.")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(profiles, f, indent=2)
    print(f"Saved to {OUTPUT}")

    return profiles


if __name__ == "__main__":
    main()
