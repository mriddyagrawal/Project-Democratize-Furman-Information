"""Scrape Cultural Life Program (CLP) events from furman.edu.

The CLP page loads a JS calendar. We use Playwright to render it,
navigate back 3 months, and extract event name, date, and description.
"""

import json
import re
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, TimeoutError

CLP_URL = "https://www.furman.edu/academics/cultural-life-program/upcoming-clp-events/"
HERE = Path(__file__).parent
OUTPUT_DIR = HERE / "data"
MONTHS_BACK = 3


def _dump_debug(page: Page, label: str):
    """Save page HTML for debugging."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"debug_{label}.html"
    path.write_text(page.content())
    print(f"  [debug] Saved {path}")


def _find_calendar(page: Page) -> str | None:
    """Detect what kind of calendar is on the page and return its type."""
    content = page.content().lower()

    # Check for common calendar platforms
    checks = {
        "trumba": ["trumba", "trumba.com"],
        "25live": ["25live", "collegenet"],
        "localist": ["localist"],
        "google_calendar": ["calendar.google.com", "googleapis.com/calendar"],
        "fullcalendar": ["fullcalendar", "fc-event"],
        "the_events_calendar": ["tribe-events", "tribe_events"],
        "embedded_iframe": [],
    }

    for cal_type, markers in checks.items():
        for marker in markers:
            if marker in content:
                return cal_type

    # Check for iframes (calendar might be embedded)
    iframes = page.query_selector_all("iframe")
    for iframe in iframes:
        src = iframe.get_attribute("src") or ""
        if src:
            print(f"  Found iframe: {src}")
            return "iframe"

    return None


def _scrape_generic(page: Page) -> list[dict]:
    """Try to extract events from whatever is on the page."""
    events = []

    # Look for anything that looks like event containers
    selectors = [
        "[class*='event']", "[class*='Event']",
        "[class*='calendar']", "[class*='Calendar']",
        "article", ".entry", ".post",
        "table tbody tr",
        "li a[href*='event']",
        "[data-event]", "[data-date]",
    ]

    for sel in selectors:
        elements = page.query_selector_all(sel)
        if elements and len(elements) > 1:
            print(f"  Trying selector '{sel}' — {len(elements)} elements")
            for el in elements:
                text = el.inner_text().strip()
                if len(text) < 5:
                    continue

                event = {"raw_text": text}
                link = el.query_selector("a")
                if link:
                    event["title"] = link.inner_text().strip()
                    event["link"] = link.get_attribute("href") or ""

                events.append(event)

            if events:
                return events

    return events


def _follow_event_link(page: Page, browser, url: str) -> str:
    """Open an event link in a new tab and grab the description."""
    try:
        new_page = browser.new_page()
        new_page.goto(url, wait_until="networkidle", timeout=30_000)
        new_page.wait_for_timeout(2000)

        # Try to find description content
        desc_selectors = [
            "[class*='description']", "[class*='detail']",
            "[class*='content']", "[class*='body']",
            "article", ".entry-content", "main p",
        ]
        for sel in desc_selectors:
            el = new_page.query_selector(sel)
            if el:
                text = el.inner_text().strip()
                if len(text) > 20:
                    new_page.close()
                    return text

        # Fallback: grab all paragraph text
        paragraphs = new_page.query_selector_all("main p, article p, .content p")
        desc = "\n".join(p.inner_text().strip() for p in paragraphs if p.inner_text().strip())
        new_page.close()
        return desc
    except Exception as e:
        print(f"    Could not fetch description: {e}")
        return ""


def scrape_clp_events() -> list[dict]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        print(f"Loading {CLP_URL} ...")
        page.goto(CLP_URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(5000)

        _dump_debug(page, "initial_load")

        # Detect calendar type
        cal_type = _find_calendar(page)
        print(f"  Calendar type detected: {cal_type or 'unknown'}")

        # If there's an iframe, switch into it
        if cal_type == "iframe":
            iframes = page.query_selector_all("iframe")
            for iframe in iframes:
                src = iframe.get_attribute("src") or ""
                if src:
                    print(f"  Navigating into iframe: {src}")
                    page.goto(src, wait_until="networkidle", timeout=60_000)
                    page.wait_for_timeout(3000)
                    _dump_debug(page, "iframe_content")
                    break

        # Log what we can see
        print("\n  === Page text preview ===")
        body_text = page.inner_text("body")
        # Show first 2000 chars to understand what's there
        preview = body_text[:2000]
        print(preview)
        print("  === End preview ===\n")

        # Also log all links that contain 'event' in href or text
        print("  === Event-related links ===")
        all_links = page.query_selector_all("a")
        event_links = []
        for link in all_links:
            href = link.get_attribute("href") or ""
            text = link.inner_text().strip()
            if any(kw in (href + text).lower() for kw in ["event", "clp", "calendar", "program"]):
                print(f"    {text[:80]} -> {href[:120]}")
                event_links.append({"text": text, "href": href})
        print(f"  === Found {len(event_links)} event-related links ===\n")

        # Try to navigate backward through months
        # Look for prev/back/arrow buttons
        nav_buttons = page.query_selector_all(
            "[class*='prev'], [class*='Prev'], [class*='back'], "
            "[aria-label*='prev'], [aria-label*='Previous'], "
            "button:has-text('‹'), button:has-text('←'), "
            "a:has-text('‹'), a:has-text('←'), "
            "[class*='nav'] button, [class*='fc-prev']"
        )
        if nav_buttons:
            print(f"  Found {len(nav_buttons)} navigation buttons — will go back {MONTHS_BACK} months")

        # Scrape current month + go back 3 months
        all_events = []

        for month_offset in range(MONTHS_BACK + 1):
            if month_offset > 0 and nav_buttons:
                print(f"  Navigating to previous month ({month_offset})...")
                try:
                    nav_buttons[0].click()
                    page.wait_for_timeout(3000)
                    # Re-find nav buttons after page update
                    nav_buttons = page.query_selector_all(
                        "[class*='prev'], [class*='Prev'], [class*='back'], "
                        "[aria-label*='prev'], [aria-label*='Previous'], "
                        "button:has-text('‹'), button:has-text('←'), "
                        "a:has-text('‹'), a:has-text('←'), "
                        "[class*='nav'] button, [class*='fc-prev']"
                    )
                except Exception as e:
                    print(f"  Could not navigate back: {e}")
                    break

            _dump_debug(page, f"month_{month_offset}")
            month_events = _scrape_generic(page)
            print(f"  Month offset -{month_offset}: found {len(month_events)} events")
            all_events.extend(month_events)

        # If we got events with links, try to get descriptions
        print(f"\n  Total raw events: {len(all_events)}")
        for i, event in enumerate(all_events):
            link = event.get("link", "")
            if link and link.startswith("http"):
                print(f"  [{i+1}/{len(all_events)}] Fetching description for: {event.get('title', '?')[:60]}")
                event["description"] = _follow_event_link(page, context, link)

        browser.close()

    return all_events


def main():
    events = scrape_clp_events()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / "events.json"
    with open(output_file, "w") as f:
        json.dump(events, f, indent=2)

    print(f"\nDone. Got {len(events)} events.")
    print(f"Saved to {output_file}")


if __name__ == "__main__":
    main()
