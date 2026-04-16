"""Fetch document lists and download files for all organizations.

Replaces the old fetch_docs + download stages. Runs orgs concurrently
in batches using asyncio + httpx.AsyncClient.

Now recursively crawls into folders (which requires auth cookies).
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
FOLDER_CONTENTS_URL = "https://furman.campuslabs.com/engage/legacy/webapi/drive/folder/{folder_id}/contents"
DOWNLOAD_BASE = "https://furman.campuslabs.com/engage/legacy"
HERE = Path(__file__).parent
ORGS_FILE = HERE / "data" / "orgs.json"
DATA_DIR = HERE / "data" / "orgs"
SESSION_FILE = HERE / "auth_session" / "state.json"
BATCH_SIZE = 10
MAX_FOLDER_DEPTH = 10


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


def _load_auth_cookies() -> dict[str, str]:
    """Load cookies from the saved Playwright auth session."""
    if not SESSION_FILE.exists():
        return {}
    with open(SESSION_FILE) as f:
        state = json.load(f)
    return {c["name"]: c["value"] for c in state.get("cookies", [])}


async def _fetch_page_items(
    client: httpx.AsyncClient, url: str, slug: str,
    auth_client: httpx.AsyncClient | None = None, page: int = 1,
) -> tuple[list[dict], bool]:
    """Fetch one page of items. Returns (items, has_next).

    Tries unauthenticated first. If that gets a permission-denied or
    login redirect, retries with auth_client (which carries cookies).
    """
    params = {"page": str(page), "pageSize": "100"}
    headers = {"groupKey": slug}

    resp = await async_request_with_retry(
        client, "GET", url, params=params, headers=headers,
    )

    # If unauthenticated fails, escalate to auth
    needs_auth = (
        resp.status_code == 302
        or "permission denied" in resp.text.lower()
        or "login" in resp.headers.get("location", "").lower()
    )
    if needs_auth and auth_client is not None:
        resp = await async_request_with_retry(
            auth_client, "GET", url, params=params, headers=headers,
        )

    try:
        items = resp.json()
    except Exception:
        return [], False

    if not items or isinstance(items, str):
        return [], False

    pag_header = resp.headers.get("X-Pagination")
    has_next = False
    if pag_header:
        pag = json.loads(pag_header)
        has_next = pag.get("Next") is not None

    return items, has_next


async def _fetch_doc_list(
    client: httpx.AsyncClient, slug: str,
    auth_client: httpx.AsyncClient | None = None,
    folder_path: str = "",
    folder_id: int | None = None, depth: int = 0,
) -> list[dict]:
    """Get documents for one org, recursively entering folders.

    Tries unauthenticated first; escalates to auth_client if needed.
    """
    if depth > MAX_FOLDER_DEPTH:
        return []

    url = FOLDER_CONTENTS_URL.format(folder_id=folder_id) if folder_id else DRIVE_URL
    docs = []
    page = 1

    while True:
        items, has_next = await _fetch_page_items(client, url, slug, auth_client, page)
        if not items:
            break

        for item in items:
            doc_type = (item.get("DocumentType") or {}).get("Name", "")

            if doc_type == "Folder":
                # Recurse into this folder
                sub_path = f"{folder_path}/{item['Title']}" if folder_path else item["Title"]
                sub_docs = await _fetch_doc_list(
                    client, slug,
                    auth_client=auth_client,
                    folder_path=sub_path,
                    folder_id=item["Id"],
                    depth=depth + 1,
                )
                docs.extend(sub_docs)
                continue

            links = item.get("Links", [])
            href = links[0]["Href"] if links else None
            docs.append({
                "doc_id": item["Id"],
                "title": item.get("Title", ""),
                "doc_type": doc_type,
                "upload_date": item.get("UploadDate", ""),
                "view_href": href,
                "folder_path": folder_path,
            })

        if not has_next:
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

    folder_path = doc.get("folder_path", "")
    if folder_path:
        # Preserve the original folder hierarchy
        safe_folder = Path(*[_slugify(p) for p in folder_path.split("/")])
        dest_dir = org_dir / "documents" / "folders" / safe_folder
    else:
        dest_dir = org_dir / "documents" / year
    dest_dir.mkdir(parents=True, exist_ok=True)

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
    filepath = dest_dir / filename

    new_hash = hashlib.sha256(resp.content).hexdigest()
    if filepath.exists():
        if hashlib.sha256(filepath.read_bytes()).hexdigest() == new_hash:
            return "skipped"

    filepath.write_bytes(resp.content)
    return "downloaded"


async def _process_org(
    client: httpx.AsyncClient, sem: asyncio.Semaphore,
    org: dict, counter: dict, total: int,
    auth_client: httpx.AsyncClient | None = None,
):
    """Fetch doc list + download all docs for one org."""
    async with sem:
        slug = org["slug"]
        try:
            docs = await _fetch_doc_list(
                client, slug, auth_client=auth_client,
            )
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

    # Use auth cookies when available for extra access, fall back to anonymous
    cookies = _load_auth_cookies()
    if cookies:
        print(f"Loaded auth session ({len(cookies)} cookies) — will use for extra access")
    else:
        print("No auth session — running unauthenticated (public docs only)")

    print(f"Fetching & downloading docs for {total} organizations (batch={BATCH_SIZE})...")

    counter: dict = {"orgs_done": 0, "downloaded": 0, "skipped": 0, "errors": 0}
    sem = asyncio.Semaphore(BATCH_SIZE)

    auth_client = httpx.AsyncClient(timeout=60, cookies=cookies) if cookies else None

    async with httpx.AsyncClient(timeout=60) as client:
        tasks = [
            _process_org(client, sem, org, counter, total, auth_client)
            for org in orgs
        ]
        await asyncio.gather(*tasks)

    if auth_client:
        await auth_client.aclose()

    print(f"\nDone. {counter.get('downloaded', 0)} downloaded, "
          f"{counter.get('skipped', 0)} skipped, {counter.get('errors', 0)} errors.")


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
