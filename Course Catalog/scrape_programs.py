"""Download all Furman 2025-2026 program pages as raw HTML files."""

from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

BASE = "https://catalog.furman.edu"
CATOID = 29
LISTING_URL = f"{BASE}/content.php?catoid={CATOID}&navoid=1648"
PROGRAM_URL = f"{BASE}/preview_program.php?catoid={CATOID}&poid={{poid}}&returnto=1648"
DELAY = 0.5
BATCH_SIZE = 5

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

    remaining = [p for p in programs if p["poid"] not in done]

    def fetch_one(prog: dict) -> tuple[dict, requests.Response | None]:
        poid = prog["poid"]
        url = PROGRAM_URL.format(poid=poid)
        for attempt in range(1, 4):
            try:
                r = SESSION.get(url, timeout=30)
                r.raise_for_status()
                return prog, r
            except requests.RequestException as e:
                wait = attempt * 5
                tqdm.write(f"  error poid={poid} (attempt {attempt}/3): {e}; waiting {wait}s")
                time.sleep(wait)
        return prog, None

    pbar = tqdm(total=len(programs), desc="Scraping programs", unit="program",
                initial=len(done))
    for batch_start in range(0, len(remaining), BATCH_SIZE):
        batch = remaining[batch_start : batch_start + BATCH_SIZE]
        with ThreadPoolExecutor(max_workers=BATCH_SIZE) as executor:
            futures = {executor.submit(fetch_one, prog): prog for prog in batch}
            for future in as_completed(futures):
                prog, r = future.result()
                if r is None or not r.ok:
                    tqdm.write(f"  SKIPPED poid={prog['poid']} after 3 failures")
                    pbar.update(1)
                    continue

                requirements = extract_program(r.text)
                degree_type = classify_degree(prog["name"])

                requirements = re.sub(r"[\t\r]+", " ", requirements)
                requirements = re.sub(r"\n{3,}", "\n\n", requirements)
                requirements = re.sub(r" {2,}", " ", requirements).strip()

                results.append({
                    "poid": prog["poid"],
                    "department": prog["department"],
                    "name": prog["name"],
                    "degree_type": degree_type,
                    "requirements": requirements,
                })
                pbar.update(1)

        if len(results) % 50 < BATCH_SIZE:
            RAW_FILE.write_text(json.dumps(results, indent=2))

        time.sleep(DELAY)

    pbar.close()
    total = len(list(HTML_DIR.glob("*.html")))
    print(f"Done. {total} HTML files saved to {HTML_DIR}")


if __name__ == "__main__":
    sys.exit(main())
