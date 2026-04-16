"""Download all Furman 2025-2026 program pages as raw HTML files."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

BASE = "https://catalog.furman.edu"
CATOID = 29
LISTING_URL = f"{BASE}/content.php?catoid={CATOID}&navoid=1648"
PROGRAM_URL = f"{BASE}/preview_program.php?catoid={CATOID}&poid={{poid}}&returnto=1648"
DELAY = 0.5

DATA_DIR = Path(__file__).parent / "Program Details"
DATA_DIR.mkdir(exist_ok=True)
HTML_DIR = DATA_DIR / "html"
HTML_DIR.mkdir(exist_ok=True)
POIDS_FILE = DATA_DIR / "poids.json"

SESSION = requests.Session()
SESSION.headers.update(
    {"User-Agent": "Mozilla/5.0 (catalog-scraper; educational use)"}
)


def collect_programs() -> list[dict]:
    print("Fetching program listing page...", flush=True)
    r = SESSION.get(LISTING_URL, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    links = soup.find_all(
        "a", href=re.compile(r"preview_program\.php\?catoid=29&poid=\d+")
    )
    programs: list[dict] = []
    seen: set[str] = set()

    for link in links:
        m = re.search(r"poid=(\d+)", link["href"])
        if not m:
            continue
        poid = m.group(1)
        if poid in seen:
            continue
        seen.add(poid)
        name = link.get_text(strip=True)
        heading = link.find_previous(["h2", "h3", "h4", "strong", "b"])
        dept = heading.get_text(strip=True) if heading else ""
        programs.append({"poid": poid, "name": name, "department": dept})

    print(
        f"Found {len(programs)} programs across "
        f"{len(set(p['department'] for p in programs))} departments."
    )
    return programs


def sanitize_filename(name: str) -> str:
    return re.sub(r"[^\w\s\-.,()]", "", name).strip().replace(" ", "_")


def main() -> None:
    if POIDS_FILE.exists():
        programs = json.loads(POIDS_FILE.read_text())
        print(f"Loaded {len(programs)} cached programs from {POIDS_FILE.name}")
    else:
        programs = collect_programs()
        POIDS_FILE.write_text(json.dumps(programs, indent=2))
        print(f"Saved {len(programs)} programs to {POIDS_FILE.name}")

    already = {f.stem.split("_poid")[0] for f in HTML_DIR.glob("*.html")}
    remaining = [p for p in programs if sanitize_filename(p["name"]) not in already]

    pbar = tqdm(
        remaining,
        desc="Downloading programs",
        unit="program",
        initial=len(programs) - len(remaining),
        total=len(programs),
    )
    for prog in pbar:
        poid = prog["poid"]
        pbar.set_postfix_str(prog["name"][:40])
        url = PROGRAM_URL.format(poid=poid)
        r = None
        for attempt in range(1, 4):
            try:
                r = SESSION.get(url, timeout=30)
                r.raise_for_status()
                break
            except requests.RequestException as e:
                wait = attempt * 5
                tqdm.write(f"  error (attempt {attempt}/3): {e}; waiting {wait}s")
                time.sleep(wait)
        if r is None or not r.ok:
            tqdm.write(f"  SKIPPED poid={poid} ({prog['name']})")
            continue

        filename = f"{sanitize_filename(prog['name'])}_poid{poid}.html"
        (HTML_DIR / filename).write_text(r.text, encoding="utf-8")
        time.sleep(DELAY)

    pbar.close()
    total = len(list(HTML_DIR.glob("*.html")))
    print(f"Done. {total} HTML files saved to {HTML_DIR}")


if __name__ == "__main__":
    sys.exit(main())
