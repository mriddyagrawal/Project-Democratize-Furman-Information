"""Scrape Furman University 2025-2026 program requirements into an Excel spreadsheet."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from openpyxl import Workbook
from tqdm import tqdm

BASE = "https://catalog.furman.edu"
CATOID = 29
LISTING_URL = f"{BASE}/content.php?catoid={CATOID}&navoid=1648"
PROGRAM_URL = f"{BASE}/preview_program.php?catoid={CATOID}&poid={{poid}}&returnto=1648"
DELAY = 0.5

DATA_DIR = Path(__file__).parent / "Program Details"
DATA_DIR.mkdir(exist_ok=True)
POIDS_FILE = DATA_DIR / "poids.json"
RAW_FILE = DATA_DIR / "programs_raw.json"
XLSX_FILE = DATA_DIR / "furman_programs_2025_2026.xlsx"

SESSION = requests.Session()
SESSION.headers.update(
    {"User-Agent": "Mozilla/5.0 (catalog-scraper; educational use)"}
)

DEGREE_PATTERNS = [
    (r"\bB\.?A\.?\b", "B.A."),
    (r"\bB\.?S\.?\b", "B.S."),
    (r"\bB\.?M\.?\b", "B.M."),
    (r"\bB\.?Mus\.?\b", "B.M."),
    (r"\bMinor\b", "Minor"),
]


def collect_programs() -> list[dict]:
    """Collect all program IDs, names, and departments from the listing page."""
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

    print(f"Found {len(programs)} programs across {len(set(p['department'] for p in programs))} departments.")
    return programs


def classify_degree(name: str) -> str:
    for pattern, label in DEGREE_PATTERNS:
        if re.search(pattern, name):
            return label
    return ""


def extract_program(html: str) -> str:
    """Extract program requirements text from a detail page."""
    soup = BeautifulSoup(html, "html.parser")
    cores = soup.find_all("div", class_="acalog-core")
    if not cores:
        td = soup.find("td", class_="block_content")
        if td:
            text = td.get_text("\n", strip=True)
            start = 0
            for marker in ["must include:", "must complete:", "requires:", "Required"]:
                idx = text.find(marker)
                if idx >= 0:
                    start = idx
                    break
            end = text.find("Return to:")
            if end < 0:
                end = text.find("Back to Top")
            if end > 0:
                text = text[start:end]
            else:
                text = text[start:]
            return text.strip()
        return ""

    sections: list[str] = []
    for core in cores:
        h2 = core.find("h2")
        header = h2.get_text(strip=True) if h2 else ""
        items: list[str] = []
        for li in core.find_all("li", class_="acalog-course"):
            items.append(li.get_text(" ", strip=True))
        body_parts: list[str] = []
        for child in core.children:
            if child.name == "h2":
                continue
            if child.name == "hr":
                continue
            if child.name == "ul":
                continue
            if hasattr(child, "get_text"):
                t = child.get_text(" ", strip=True)
                if t:
                    body_parts.append(t)
            elif isinstance(child, str) and child.strip():
                body_parts.append(child.strip())

        section_text = ""
        if header:
            section_text += header + "\n"
        if body_parts:
            section_text += "\n".join(body_parts) + "\n"
        if items:
            section_text += "\n".join(f"  {item}" for item in items) + "\n"
        if section_text.strip():
            sections.append(section_text.strip())

    return "\n\n".join(sections)


def main() -> None:
    if POIDS_FILE.exists():
        programs = json.loads(POIDS_FILE.read_text())
        print(f"Loaded {len(programs)} cached programs from {POIDS_FILE.name}")
    else:
        programs = collect_programs()
        POIDS_FILE.write_text(json.dumps(programs, indent=2))
        print(f"Saved {len(programs)} programs to {POIDS_FILE.name}")

    if RAW_FILE.exists():
        results = json.loads(RAW_FILE.read_text())
        done = {r["poid"] for r in results}
        print(f"Resuming: {len(done)} programs already fetched.")
    else:
        results = []
        done = set()

    remaining = [p for p in programs if p["poid"] not in done]
    pbar = tqdm(remaining, desc="Scraping programs", unit="program",
                initial=len(done), total=len(programs))
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
            tqdm.write(f"  SKIPPED poid={poid} after 3 failures")
            continue

        requirements = extract_program(r.text)
        degree_type = classify_degree(prog["name"])

        results.append({
            "poid": poid,
            "department": prog["department"],
            "name": prog["name"],
            "degree_type": degree_type,
            "requirements": requirements,
        })

        time.sleep(DELAY)

    RAW_FILE.write_text(json.dumps(results, indent=2))
    print(f"Fetched {len(results)} programs. Saved to {RAW_FILE.name}.")

    results_sorted = sorted(results, key=lambda p: (p["department"], p["name"]))
    wb = Workbook()
    ws = wb.active
    ws.title = "Programs 2025-2026"
    headers = ["Department", "Program Name", "Degree Type", "Full Requirements Text"]
    ws.append(headers)
    for p in results_sorted:
        ws.append([p["department"], p["name"], p["degree_type"], p["requirements"]])

    widths = [30, 50, 12, 120]
    for col, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = w

    wb.save(XLSX_FILE)
    print(f"Wrote {len(results_sorted)} rows to {XLSX_FILE}")


if __name__ == "__main__":
    sys.exit(main())
