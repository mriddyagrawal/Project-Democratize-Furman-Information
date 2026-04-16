"""Stage 2: Fetch document manifests for all organizations."""

import json
import time
from pathlib import Path

import httpx

DRIVE_URL = "https://furman.campuslabs.com/engage/legacy/webapi/drive"
HERE = Path(__file__).parent
ORGS_FILE = HERE / "data" / "orgs.json"
OUTPUT_FILE = HERE / "data" / "doc_manifests.json"
PAGE_SIZE = 100


def fetch_docs_for_org(client: httpx.Client, slug: str) -> list[dict]:
    docs = []
    page = 1
    while True:
        resp = client.get(
            DRIVE_URL,
            params={"page": str(page), "pageSize": str(PAGE_SIZE)},
            headers={"groupKey": slug},
        )
        resp.raise_for_status()
        items = resp.json()
        if not items:
            break

        for item in items:
            if item.get("DocumentType", {}).get("Name") == "Folder":
                continue
            links = item.get("Links", [])
            href = links[0]["Href"] if links else None
            docs.append({
                "doc_id": item["Id"],
                "title": item.get("Title", ""),
                "description": item.get("Description", ""),
                "doc_type": item.get("DocumentType", {}).get("Name", ""),
                "upload_date": item.get("UploadDate", ""),
                "content_type": links[0].get("Type", "") if links else "",
                "view_href": href,
                "access": item.get("RestrictedAccessType", ""),
            })

        pagination = resp.headers.get("X-Pagination")
        if pagination:
            pag = json.loads(pagination)
            if pag.get("Next") is None:
                break
        else:
            break
        page += 1

    return docs


def main():
    with open(ORGS_FILE) as f:
        orgs = json.load(f)

    print(f"Stage 2: Fetching document manifests for {len(orgs)} organizations...")
    manifests = {}
    total_docs = 0

    with httpx.Client(timeout=30) as client:
        for i, org in enumerate(orgs):
            slug = org["slug"]
            try:
                docs = fetch_docs_for_org(client, slug)
                manifests[slug] = {
                    "org_name": org["name"],
                    "org_id": org["id"],
                    "status": org["status"],
                    "documents": docs,
                }
                total_docs += len(docs)
                if docs:
                    print(f"  [{i+1}/{len(orgs)}] {org['name']}: {len(docs)} docs")
                time.sleep(0.3)
            except Exception as e:
                print(f"  [{i+1}/{len(orgs)}] ERROR {org['name']}: {e}")
                manifests[slug] = {
                    "org_name": org["name"],
                    "org_id": org["id"],
                    "status": org["status"],
                    "documents": [],
                    "error": str(e),
                }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(manifests, f, indent=2)

    orgs_with_docs = sum(1 for m in manifests.values() if m["documents"])
    print(f"\nDone. {total_docs} documents across {orgs_with_docs} organizations.")
    print(f"Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
