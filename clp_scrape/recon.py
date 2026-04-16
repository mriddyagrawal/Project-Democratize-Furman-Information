"""Quick recon: open the CLP page in a browser and dump what we see."""

from pathlib import Path
from playwright.sync_api import sync_playwright

CLP_URL = "https://www.furman.edu/academics/cultural-life-program/upcoming-clp-events/"
HERE = Path(__file__).parent
OUTPUT_DIR = HERE / "data"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page()

        print(f"Loading {CLP_URL} ...")
        page.goto(CLP_URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(5000)

        # Save full rendered HTML
        (OUTPUT_DIR / "debug_full.html").write_text(page.content())
        print(f"Saved rendered HTML to {OUTPUT_DIR / 'debug_full.html'}")

        # Check for iframes
        iframes = page.query_selector_all("iframe")
        for i, iframe in enumerate(iframes):
            src = iframe.get_attribute("src") or "(no src)"
            name = iframe.get_attribute("name") or iframe.get_attribute("id") or ""
            print(f"  iframe[{i}]: src={src}  name={name}")

            # Try to get iframe content
            frame = iframe.content_frame()
            if frame:
                frame_html = frame.content()
                (OUTPUT_DIR / f"debug_iframe_{i}.html").write_text(frame_html)
                print(f"  Saved iframe content to debug_iframe_{i}.html")

                # Show text preview
                try:
                    text = frame.inner_text("body")[:3000]
                    print(f"  --- iframe text preview ---")
                    print(text)
                    print(f"  --- end iframe preview ---")
                except Exception:
                    pass

        # Show main page text
        body_text = page.inner_text("body")
        print(f"\n=== Main page text ({len(body_text)} chars) ===")
        print(body_text[:3000])
        print("=== end ===")

        # Check what network requests were made (look for API/calendar endpoints)
        print("\n=== Intercepted URLs (reloading page to capture) ===")
        urls = []
        page.on("response", lambda resp: urls.append(f"{resp.status} {resp.url}"))
        page.reload(wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(5000)

        for u in urls:
            if any(kw in u.lower() for kw in ["event", "calendar", "clp", "api", "feed", "json", "ical"]):
                print(f"  {u}")

        if not any("event" in u.lower() or "calendar" in u.lower() for u in urls):
            print("  (no obvious event/calendar API calls detected)")
            print("  All requests:")
            for u in urls[:50]:
                print(f"    {u}")

        input("\nPress ENTER to close the browser (look at what's on screen first)...")
        browser.close()


if __name__ == "__main__":
    main()
