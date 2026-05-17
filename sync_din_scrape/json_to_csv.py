#!/usr/bin/env python3
"""Convert every .json under sync_din_scrape/data/ to a .csv next to it."""
import csv
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def flatten(value):
    if isinstance(value, list):
        return ";".join(flatten(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    return str(value)


def rows_from(payload):
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def write_csv(rows, out_path):
    fieldnames = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: flatten(row.get(k)) for k in fieldnames})


def main():
    json_files = sorted(DATA_DIR.rglob("*.json"))
    converted = skipped = 0
    for jf in json_files:
        try:
            payload = json.loads(jf.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"SKIP (bad json): {jf} — {e}")
            skipped += 1
            continue
        rows = rows_from(payload)
        if not rows:
            print(f"SKIP (empty): {jf}")
            skipped += 1
            continue
        out = jf.with_suffix(".csv")
        write_csv(rows, out)
        converted += 1
    print(f"Converted {converted} files, skipped {skipped}.")


if __name__ == "__main__":
    main()
