"""Convert clp_scrape/data/events.json to a CSV with normalized characters."""

from __future__ import annotations

import csv
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
JSON_FILE = DATA_DIR / "events.json"
CSV_FILE = DATA_DIR / "events.csv"

CLP_EXPLANATION = (
    "A CLP (Cultural Life Program) is Furman University's program that "
    "encourages students to attend a variety of high-quality cultural, "
    "artistic, and intellectual events. Students are required to earn a "
    "set number of CLP credits to graduate, exposing them to diverse "
    "perspectives and enriching experiences outside the classroom."
)

CHAR_MAP = {
    "\u00a0": " ",   # non-breaking space
    "\u2013": "-",   # en dash
    "\u2014": "-",   # em dash
    "\u2018": "'",   # left single quote
    "\u2019": "'",   # right single quote / apostrophe
    "\u201c": '"',   # left double quote
    "\u201d": '"',   # right double quote
    "\u2026": "...",
    "\u00e1": "a",   # á
    "\u00e9": "e",   # é
    "\u00ed": "i",   # í
    "\u00f3": "o",   # ó
    "\u00fa": "u",   # ú
    "\u00f1": "n",   # ñ
    "\u00c1": "A",
    "\u00c9": "E",
    "\u00cd": "I",
    "\u00d3": "O",
    "\u00da": "U",
    "\u00d1": "N",
}


def normalize(text: str) -> str:
    for old, new in CHAR_MAP.items():
        text = text.replace(old, new)
    return text


def main() -> None:
    events = json.loads(JSON_FILE.read_text(encoding="utf-8"))
    with CSV_FILE.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Name", "Date", "Description"])
        writer.writerow(["About CLPs", "", CLP_EXPLANATION])
        for ev in events:
            writer.writerow([
                normalize(ev.get("name", "")),
                normalize(ev.get("date", "")),
                normalize(ev.get("description", "")),
            ])
    print(f"Wrote {len(events)} events + 1 info row to {CSV_FILE}")


if __name__ == "__main__":
    main()
