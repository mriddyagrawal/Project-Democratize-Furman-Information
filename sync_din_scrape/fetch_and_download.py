"""Fetch document lists and download files for all organizations.

Replaces the old fetch_docs + download stages. Runs orgs concurrently
in batches using asyncio + httpx.AsyncClient.
"""

import asyncio
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote

import httpx

from shared.rate_limit import async_request_with_retry

DRIVE_URL = "https://furman.campuslabs.com/engage/legacy/webapi/drive"
DOWNLOAD_BASE = "https://furman.campuslabs.com/engage/legacy"
HERE = Path(__file__).parent
ORGS_FILE = HERE / "data" / "orgs.json"
DATA_DIR = HERE / "data" / "orgs"
BATCH_SIZE = 10


def _slugify(text: str) -> str:
    text = re.sub(r'[^\w\s-]', '', text.lower())
    return re.sub(r'[\s]+', '_', text).strip('_')[:80]


def _classify(title: str, doc_type: str) -> str:
    combined = f"{title} {doc_type}".lower()
    if "constitution" in combined or "bylaws" in combined or "bylaw" in combined:
        return "constitution"
    return "other"


def _ext_from_content_type(ct: str) -> str:
    mapping = {
        "application/pdf": ".pdf",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.ms-excel": ".xls",
        "text/csv": ".csv",
    }
    return mapping.get(ct.split(";")[0].strip(), "")


def _filename_from_headers(headers: httpx.Headers) -> str | None:
    cd = headers.get("content-disposition", "")
    match = re.search(r'filename=[""]?([^""\r\n;]+)', cd)
    if match:
        return unquote(match.group(1)).strip()
    return None


async def _fetch_doc_list(client: httpx.AsyncClient, slug: str) -> list[dict]:
    """Get the document list for one org."""
    docs = []
    page = 1
    while True:
        resp = await async_request_with_retry(
            client, "GET", DRIVE_URL,
            params={"page": str(page), "pageSize": "100"},
            headers={"groupKey": slug},
        )
        items = resp.json()
        if not items:
            break

        for item in items:
            if (item.get("DocumentType") or {}).get("Name") == "Folder":
                continue
            links = item.get("Links", [])
            href = links[0]["Href"] if links else None
            docs.append({
                "doc_id": item["Id"],
                "title": item.get("Title", ""),
                "doc_type": (item.get("DocumentType") or {}).get("Name", ""),
                "upload_date": item.get("UploadDate", ""),
                "view_href": href,
            })

        pag_header = resp.headers.get("X-Pagination")
        if pag_header:
            pag = json.loads(pag_header)
            if pag.get("Next") is None:
                break
        else:
            break
        page += 1

    return docs


async def _download_file(
    client: httpx.AsyncClient, slug: str, doc: dict, org_dir: Path,
) -> str:
    """Download a single document file. Returns 'downloaded', 'skipped', or 'error'."""
    href = doc.get("view_href")
    if not href:
        return "skipped"

    upload_date = doc.get("upload_date", "")
    year = upload_date[:4] if upload_date else "unknown"
    doc_class = _classify(doc["title"], doc["doc_type"])
    safe_title = _slugify(doc["title"])

    year_dir = org_dir / "documents" / year
    year_dir.mkdir(parents=True, exist_ok=True)

    download_url = DOWNLOAD_BASE + href

    try:
        resp = await async_request_with_retry(
            client, "GET", download_url,
            follow_redirects=True,
        )
    except Exception as e:
        print(f"  ERROR [{slug}] doc {doc['doc_id']}: {e}")
        return "error"

    orig_filename = _filename_from_headers(resp.headers)
    ct = resp.headers.get("content-type", "")
    ext = Path(orig_filename).suffix if orig_filename else ""
    if not ext:
        ext = _ext_from_content_type(ct)
    if not ext:
        ext = ".bin"

    filename = f"{doc_class}_{safe_title}_{doc['doc_id']}{ext}"
    filepath = year_dir / filename

    new_hash = hashlib.sha256(resp.content).hexdigest()
    if filepath.exists():
        if hashlib.sha256(filepath.read_bytes()).hexdigest() == new_hash:
            return "skipped"

    filepath.write_bytes(resp.content)
    return "downloaded"


async def _process_org(
    client: httpx.AsyncClient, sem: asyncio.Semaphore,
    org: dict, counter: dict, total: int,
):
    """Fetch doc list + download all docs for one org."""
    async with sem:
        slug = org["slug"]
        try:
            docs = await _fetch_doc_list(client, slug)
        except Exception as e:
            print(f"  ERROR [{slug}] listing docs: {e}")
            counter["errors"] += 1
            return

        if not docs:
            return

        org_dir = DATA_DIR / slug
        org_dir.mkdir(parents=True, exist_ok=True)

        for doc in docs:
            result = await _download_file(client, slug, doc, org_dir)
            counter[result] = counter.get(result, 0) + 1

        counter["orgs_done"] += 1
        done = counter["orgs_done"]
        dl = counter.get("downloaded", 0)
        sk = counter.get("skipped", 0)
        er = counter.get("errors", 0)
        print(f"  [{done}/{total}] {org['name']}: {len(docs)} docs  (total: {dl} new, {sk} skipped, {er} errors)")


async def run():
    with open(ORGS_FILE) as f:
        orgs = json.load(f)

    total = len(orgs)
    print(f"Fetching & downloading docs for {total} organizations (batch={BATCH_SIZE})...")

    counter: dict = {"orgs_done": 0, "downloaded": 0, "skipped": 0, "errors": 0}
    sem = asyncio.Semaphore(BATCH_SIZE)

    async with httpx.AsyncClient(timeout=60) as client:
        tasks = [_process_org(client, sem, org, counter, total) for org in orgs]
        await asyncio.gather(*tasks)

    print(f"\nDone. {counter.get('downloaded', 0)} downloaded, "
          f"{counter.get('skipped', 0)} skipped, {counter.get('errors', 0)} errors.")


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
