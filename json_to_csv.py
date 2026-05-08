#!/usr/bin/env python3
"""Convert all data JSON files in this project to CSV, then delete the originals.

Walks known data roots (sync_din_scrape/data, clp_scrape/data, Course Catalog,
furman_directory/data) and emits a sibling .csv for each .json. Skips settings
and live auth state.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

DATA_ROOTS = [
    ROOT / "sync_din_scrape" / "data",
    ROOT / "clp_scrape" / "data",
    ROOT / "Course Catalog",
    ROOT / "furman_directory" / "data",
]

EXCLUDE_DIRS = {
    ROOT / ".claude",
    ROOT / "sync_din_scrape" / "auth_session",
    ROOT / ".venv",
    ROOT / "node_modules",
    ROOT / ".git",
}


def is_excluded(path: Path) -> bool:
    for ex in EXCLUDE_DIRS:
        try:
            path.relative_to(ex)
            return True
        except ValueError:
            continue
    return False


def flatten_value(v):
    if isinstance(v, (list, tuple)):
        return "; ".join("" if x is None else str(x) for x in v)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    if v is None:
        return ""
    return v


def write_csv(rows: list[dict], out_path: Path) -> None:
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for k in row.keys():
            if k not in seen:
                seen.add(k)
                fields.append(k)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: flatten_value(row.get(k)) for k in fields})


def convert(json_path: Path) -> Path | None:
    try:
        with json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"  skip (unreadable): {json_path} — {e}", file=sys.stderr)
        return None

    csv_path = json_path.with_suffix(".csv")

    if isinstance(data, list):
        if not data:
            rows = []
        elif all(isinstance(x, dict) for x in data):
            rows = data
        else:
            rows = [{"value": flatten_value(x)} for x in data]
    elif isinstance(data, dict):
        rows = [data]
    else:
        rows = [{"value": flatten_value(data)}]

    write_csv(rows, csv_path)
    return csv_path


def main() -> int:
    json_files: list[Path] = []
    for root in DATA_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*.json"):
            if is_excluded(p):
                continue
            json_files.append(p)

    print(f"Found {len(json_files)} JSON files to convert.")
    converted = 0
    failed: list[Path] = []
    for jp in json_files:
        out = convert(jp)
        if out is None:
            failed.append(jp)
            continue
        converted += 1

    print(f"Converted: {converted}/{len(json_files)}")
    if failed:
        print(f"Failed: {len(failed)} (kept .json on disk)")
        for f in failed:
            print(f"  {f}")

    deleted = 0
    for jp in json_files:
        if jp in failed:
            continue
        try:
            jp.unlink()
            deleted += 1
        except OSError as e:
            print(f"  delete failed: {jp} — {e}", file=sys.stderr)
    print(f"Deleted: {deleted} JSON files.")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
