"""Stage 3: Download all documents and build index.csv."""

import csv
import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

import httpx

BASE_URL = "https://furman.campuslabs.com/engage/legacy"
HERE = Path(__file__).parent
MANIFESTS_FILE = HERE / "data" / "doc_manifests.json"
DATA_DIR = HERE / "data" / "orgs"
INDEX_FILE = HERE / "data" / "index.csv"
CONCURRENT = 5


def slugify(text: str) -> str:
    text = re.sub(r'[^\w\s-]', '', text.lower())
    return re.sub(r'[\s]+', '_', text).strip('_')[:80]


def classify_doc(title: str, doc_type: str) -> str:
    combined = f"{title} {doc_type}".lower()
    if "constitution" in combined or "bylaws" in combined or "bylaw" in combined:
        return "constitution"
    return "other"


def ext_from_content_type(ct: str) -> str:
    mapping = {
        "application/pdf": ".pdf",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.ms-excel": ".xls",
        "text/csv": ".csv",
        "application/octet-stream": "",
    }
    return mapping.get(ct.split(";")[0].strip(), "")


def get_filename_from_headers(headers: dict) -> str | None:
    cd = headers.get("content-disposition", "")
    match = re.search(r'filename=[""]?([^""\r\n;]+)', cd)
    if match:
        return unquote(match.group(1)).strip()
    return None


def download_doc(client: httpx.Client, slug: str, doc: dict, org_dir: Path) -> dict | None:
    href = doc.get("view_href")
    if not href:
        return None

    download_url = BASE_URL + href
    upload_date = doc.get("upload_date", "")
    year = upload_date[:4] if upload_date else "unknown"
    doc_class = classify_doc(doc["title"], doc["doc_type"])

    year_dir = org_dir / "documents" / year
    year_dir.mkdir(parents=True, exist_ok=True)

    try:
        resp = client.get(download_url, follow_redirects=True, timeout=60)
        resp.raise_for_status()
    except Exception as e:
        return {"error": str(e), "doc_id": doc["doc_id"], "url": download_url}

    orig_filename = get_filename_from_headers(dict(resp.headers))
    ct = resp.headers.get("content-type", "")
    ext = ""
    if orig_filename:
        ext = Path(orig_filename).suffix
    if not ext:
        ext = ext_from_content_type(ct)
    if not ext:
        ext = ".bin"

    safe_title = slugify(doc["title"])
    filename = f"{doc_class}_{safe_title}_{doc['doc_id']}{ext}"
    filepath = year_dir / filename

    sha256 = hashlib.sha256(resp.content).hexdigest()

    if filepath.exists():
        existing_hash = hashlib.sha256(filepath.read_bytes()).hexdigest()
        if existing_hash == sha256:
            return {
                "org_slug": slug,
                "doc_id": doc["doc_id"],
                "title": doc["title"],
                "doc_type": doc_class,
                "year": year,
                "filename": str(filepath),
                "sha256": sha256,
                "source_url": download_url,
                "upload_date": upload_date,
                "content_type": ct,
                "original_filename": orig_filename or "",
                "skipped": True,
            }

    filepath.write_bytes(resp.content)

    return {
        "org_slug": slug,
        "doc_id": doc["doc_id"],
        "title": doc["title"],
        "doc_type": doc_class,
        "year": year,
        "filename": str(filepath),
        "sha256": sha256,
        "source_url": download_url,
        "upload_date": upload_date,
        "content_type": ct,
        "original_filename": orig_filename or "",
        "skipped": False,
    }


def main():
    with open(MANIFESTS_FILE) as f:
        manifests = json.load(f)

    print(f"Stage 3: Downloading documents for {len(manifests)} organizations...")

    index_rows = []
    downloaded = 0
    skipped = 0
    errors = 0

    with httpx.Client(timeout=60) as client:
        for i, (slug, manifest) in enumerate(manifests.items()):
            docs = manifest.get("documents", [])
            if not docs:
                continue

            org_dir = DATA_DIR / slug
            org_dir.mkdir(parents=True, exist_ok=True)

            profile = {
                "name": manifest["org_name"],
                "id": manifest["org_id"],
                "status": manifest["status"],
                "slug": slug,
            }
            profile_path = org_dir / "profile.json"
            profile_path.write_text(json.dumps(profile, indent=2))

            for doc in docs:
                result = download_doc(client, slug, doc, org_dir)
                if result is None:
                    continue
                if "error" in result:
                    errors += 1
                    print(f"  ERROR [{slug}] doc {doc['doc_id']}: {result['error']}")
                elif result.get("skipped"):
                    skipped += 1
                    index_rows.append(result)
                else:
                    downloaded += 1
                    index_rows.append(result)

                time.sleep(0.2)

            if (i + 1) % 20 == 0:
                print(f"  [{i+1}/{len(manifests)}] downloaded={downloaded} skipped={skipped} errors={errors}")

    fieldnames = [
        "org_slug", "doc_id", "title", "doc_type", "year", "filename",
        "sha256", "source_url", "upload_date", "content_type", "original_filename",
    ]
    with open(INDEX_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(index_rows)

    print(f"\nDone. Downloaded: {downloaded}, Skipped: {skipped}, Errors: {errors}")
    print(f"Index saved to {INDEX_FILE}")
    print(f"Files saved under {DATA_DIR}/")


if __name__ == "__main__":
    main()
