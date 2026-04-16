"""Scrape the Furman University 2025-2026 course catalog into an Excel spreadsheet."""

from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from openpyxl import Workbook
from tqdm import tqdm

BASE = "https://catalog.furman.edu"
CATOID = 29
NAVOID = 1649
LIST_URL = (
    f"{BASE}/content.php?catoid={CATOID}&catoid={CATOID}&navoid={NAVOID}"
    f"&filter%5Bitem_type%5D=3&filter%5Bonly_active%5D=1&filter%5B3%5D=1"
    f"&filter%5Bcpage%5D={{page}}"
)
COURSE_URL = f"{BASE}/preview_course_nopop.php?catoid={CATOID}&coid={{coid}}"
TOTAL_PAGES = 18
BATCH_SIZE = 5
BATCH_DELAY = 1.0

DATA_DIR = Path(__file__).parent / "Course Data"
DATA_DIR.mkdir(exist_ok=True)
COIDS_FILE = DATA_DIR / "coids.json"
RAW_FILE = DATA_DIR / "courses_raw.json"
XLSX_FILE = DATA_DIR / "furman_courses_2025_2026.xlsx"

SESSION = requests.Session()
SESSION.headers.update(
    {"User-Agent": "Mozilla/5.0 (catalog-scraper; educational use)"}
)


def collect_coids() -> list[str]:
    seen: list[str] = []
    seen_set: set[str] = set()
    for page in range(1, TOTAL_PAGES + 1):
        url = LIST_URL.format(page=page)
        print(f"Listing page {page}/{TOTAL_PAGES}...", flush=True)
        r = SESSION.get(url, timeout=30)
        r.raise_for_status()
        found = re.findall(
            rf"preview_course_nopop\.php\?catoid={CATOID}&(?:amp;)?coid=(\d+)",
            r.text,
        )
        new_count = 0
        for c in found:
            if c not in seen_set:
                seen_set.add(c)
                seen.append(c)
                new_count += 1
        print(f"  found {len(found)} links, {new_count} new (total: {len(seen)})")
        time.sleep(BATCH_DELAY)
    return seen


def extract_course(html: str, coid: str) -> dict | None:
    """Parse a course detail page into structured fields."""
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        return None
    heading = h1.get_text(" ", strip=True)

    m = re.match(r"([A-Z]{2,}[-\s]?\d+[A-Z]?)\s+(.*)", heading)
    if m:
        code, title = m.group(1).replace(" ", "-"), m.group(2).strip()
    else:
        parts = heading.split(None, 1)
        code = parts[0] if parts else heading
        title = parts[1] if len(parts) > 1 else ""

    # GER sits in an <em> tag immediately after the first <hr>.
    ger = ""
    all_hrs = soup.find_all("hr")
    if all_hrs:
        em = all_hrs[0].find_next_sibling("em")
        if em:
            em_text = em.get_text(strip=True)
            if em_text.upper().startswith("GER"):
                ger = em_text

    container = h1.parent
    hrs = container.find_all("hr") if container else []
    if len(hrs) < 2:
        hrs = all_hrs

    if len(hrs) < 2:
        body_text = container.get_text("\n", strip=True) if container else ""
    else:
        start, end = hrs[0], hrs[1]
        parts_out: list[str] = []
        node = start.next_sibling
        while node is not None and node is not end:
            if isinstance(node, NavigableString):
                parts_out.append(str(node))
            elif isinstance(node, Tag):
                if node.name == "br":
                    parts_out.append("\n")
                else:
                    parts_out.append(node.get_text("\n"))
            node = node.next_sibling
        body_text = "\n".join(parts_out)

    lines = [re.sub(r"\s+", " ", ln).strip() for ln in body_text.splitlines()]
    lines = [ln for ln in lines if ln]
    # Remove the GER line from body lines so it doesn't leak into description.
    if ger:
        lines = [ln for ln in lines if not ln.strip().upper().startswith("GER")]

    prereq_parts: list[str] = []
    desc_lines: list[str] = []
    credits_val = ""
    in_prereq = False

    for ln in lines:
        low = ln.lower()
        if (
            low.startswith("prerequisite")
            or low.startswith("pre-requisite")
            or low.startswith("corequisite")
            or low.startswith("co-requisite")
        ):
            in_prereq = True
            after = ln.split(":", 1)
            if len(after) == 2 and after[1].strip():
                prereq_parts.append(after[1].strip())
            else:
                prereq_parts.append(ln.rstrip(":").strip())
            continue

        credit_match = re.search(
            r"(\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?)\s+credits?\.?",
            ln,
            re.IGNORECASE,
        )
        if credit_match and ln.strip().lower().rstrip(".").endswith(
            ("credit", "credits")
        ):
            pre_credit = ln[: credit_match.start()].strip()
            if pre_credit:
                if in_prereq and not desc_lines:
                    desc_lines.append(pre_credit)
                    in_prereq = False
                else:
                    desc_lines.append(pre_credit)
            credits_val = credit_match.group(0).strip().rstrip(".")
            continue

        if in_prereq and (
            re.fullmatch(r"(AND|OR|and|or)", ln)
            or re.fullmatch(r"[A-Z]{2,}[-\s]?\d+[A-Z]?", ln)
            or len(ln) < 60
        ):
            prereq_parts.append(ln)
            continue

        in_prereq = False
        desc_lines.append(ln)

    if not credits_val:
        m2 = re.search(
            r"(\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?)\s+credits?",
            body_text,
            re.IGNORECASE,
        )
        if m2:
            credits_val = m2.group(0).strip()

    prereq = " ".join(p for p in prereq_parts if p).strip()
    prereq = re.sub(
        r"^(Prerequisite[s]?:?\s*)+", "", prereq, flags=re.IGNORECASE
    ).strip()

    description = " ".join(desc_lines).strip()

    return {
        "coid": coid,
        "code": code,
        "title": title,
        "ger": ger,
        "prerequisites": prereq,
        "description": description,
        "credits": credits_val,
    }


def course_sort_key(code: str) -> tuple:
    m = re.match(r"([A-Z]+)[-\s]?(\d+)([A-Z]?)", code)
    if m:
        return (m.group(1), int(m.group(2)), m.group(3))
    return (code, 0, "")


def main() -> None:
    if COIDS_FILE.exists():
        coids = json.loads(COIDS_FILE.read_text())
        print(f"Loaded {len(coids)} cached coids from {COIDS_FILE.name}")
    else:
        coids = collect_coids()
        COIDS_FILE.write_text(json.dumps(coids, indent=2))
        print(f"Saved {len(coids)} coids to {COIDS_FILE.name}")

    courses: list[dict] = []
    if RAW_FILE.exists():
        courses = json.loads(RAW_FILE.read_text())
        done = {c["coid"] for c in courses}
        print(f"Resuming: {len(done)} courses already fetched.")
    else:
        done = set()

    remaining = [c for c in coids if c not in done]

    def fetch_one(coid: str) -> tuple[str, requests.Response | None]:
        url = COURSE_URL.format(coid=coid)
        for attempt in range(1, 4):
            try:
                r = SESSION.get(url, timeout=30)
                r.raise_for_status()
                return coid, r
            except requests.RequestException as e:
                wait = attempt * 5
                tqdm.write(f"  error coid={coid} (attempt {attempt}/3): {e}; waiting {wait}s")
                time.sleep(wait)
        return coid, None

    pbar = tqdm(total=len(coids), desc="Scraping courses", unit="course",
                initial=len(done))
    for batch_start in range(0, len(remaining), BATCH_SIZE):
        batch = remaining[batch_start : batch_start + BATCH_SIZE]
        with ThreadPoolExecutor(max_workers=BATCH_SIZE) as executor:
            futures = {executor.submit(fetch_one, coid): coid for coid in batch}
            for future in as_completed(futures):
                coid, r = future.result()
                if r is None:
                    tqdm.write(f"  SKIPPED coid={coid} after 3 failures")
                    pbar.update(1)
                    continue
                course = extract_course(r.text, coid)
                if course:
                    courses.append(course)
                else:
                    tqdm.write(f"  no course found for coid={coid}")
                pbar.update(1)

        if len(courses) % 50 < BATCH_SIZE:
            RAW_FILE.write_text(json.dumps(courses, indent=2))

        time.sleep(BATCH_DELAY)
    pbar.close()

    RAW_FILE.write_text(json.dumps(courses, indent=2))
    print(f"Fetched {len(courses)} courses. Saved to {RAW_FILE.name}.")

    courses_sorted = sorted(courses, key=lambda c: course_sort_key(c["code"]))
    wb = Workbook()
    ws = wb.active
    ws.title = "Courses 2025-2026"
    headers = ["Course Code", "Course Title", "GER", "Prerequisites", "Description", "Credits"]
    ws.append(headers)
    for c in courses_sorted:
        ws.append(
            [c["code"], c["title"], c.get("ger", ""), c["prerequisites"], c["description"], c["credits"]]
        )

    widths = [14, 50, 30, 40, 80, 14]
    for col, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = w

    wb.save(XLSX_FILE)
    print(f"Wrote {len(courses_sorted)} rows to {XLSX_FILE}")


if __name__ == "__main__":
    sys.exit(main())
