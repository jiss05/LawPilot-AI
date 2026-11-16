"""
End-to-end smoke test of the whole ingestion + retrieval stack (SCRUM-33).

It talks to a RUNNING backend over HTTP, exactly like the frontend will:

    1. GET  /api/v1/health/ready                 database + Qdrant reachable?
    2. POST /api/v1/auth/login                   as an ADMIN
    3. POST /api/v1/knowledge-sources            upload a PDF (a generated sample
                                                 Act, or your own with --file)
    4. GET  /api/v1/admin/documents/{id}/status  wait: extraction -> chunking ->
                                                 indexing -> activation
    5. POST /api/v1/research/search              the new text must be found
    6. GET  /api/v1/admin/audit-events           the upload must be audited

Usage (from backend/, venv active, backend running):
    python scripts/smoke_test.py --email admin@example.com --password "..."
    python scripts/smoke_test.py --base-url http://localhost:8000 --email ... --password ... \
        --file "C:/Users/me/Downloads/contract_act.pdf" --query "compensation for breach"

Exit code 0 = everything worked, 1 = a step failed (the reason is printed).
The FIRST run can take several minutes: the backend downloads the OCR and
embedding models.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid

import httpx

FINAL_OK = "completed"
FINAL_FAILED = {"empty", "corrupted", "extraction_failed", "chunking_failed",
                "indexing_failed", "activation_failed"}


def sample_pdf() -> bytes:
    """A small 2-page Act with a unique word, so the search check is exact."""
    import pymupdf

    marker = f"smoketest{uuid.uuid4().hex[:8]}"
    pages = [
        "CHAPTER I\nPRELIMINARY\n1. Short title. - This Act may be called the Smoke Test Act.\n"
        "2. Definitions. - In this Act, a contract means an agreement enforceable by law.",
        "CHAPTER II\nOF BREACH\n3. Compensation. - When a contract has been broken, the party who suffers "
        f"is entitled to receive compensation. The verification word is {marker}.",
    ]
    document = pymupdf.open()
    for text in pages:
        document.new_page().insert_textbox(pymupdf.Rect(60, 60, 540, 780), text, fontsize=11)
    data = document.tobytes()
    document.close()
    return data, marker


def step(number: int, text: str) -> None:
    print(f"\n[{number}] {text}")


def fail(message: str) -> None:
    print(f"    FAILED: {message}")
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="LawPilot end-to-end smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--email", required=True, help="an ADMIN user's email")
    parser.add_argument("--password", required=True)
    parser.add_argument("--file", help="PDF to upload (default: a generated sample Act)")
    parser.add_argument("--query", help="search text (default: the sample's unique word)")
    parser.add_argument("--timeout", type=int, default=900, help="seconds to wait for processing")
    args = parser.parse_args()

    api = httpx.Client(base_url=args.base_url, timeout=120)

    step(1, "Health check")
    health = api.get("/api/v1/health/ready")
    print(f"    {health.status_code} {health.json()}")
    if health.status_code != 200:
        fail("backend is not ready (see checks above)")

    step(2, "Log in as admin")
    login = api.post("/api/v1/auth/login", json={"email": args.email, "password": args.password})
    if login.status_code != 200:
        fail(f"login returned {login.status_code}: {login.text}")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}", "X-Request-ID": f"smoke-{uuid.uuid4().hex[:8]}"}
    print(f"    ok (request id {headers['X-Request-ID']})")

    step(3, "Upload a document")
    if args.file:
        with open(args.file, "rb") as handle:
            pdf, marker = handle.read(), None
        filename = args.file.replace("\\", "/").split("/")[-1]
    else:
        pdf, marker = sample_pdf()
        filename = "smoke_test_act.pdf"
    upload = api.post(
        "/api/v1/knowledge-sources",
        data={"title": f"Smoke test: {filename}", "source_type": "statute", "jurisdiction": "India",
              "trust_tier": "official", "version_label": "smoke test", "visibility": "public"},
        files={"file": (filename, pdf, "application/pdf")},
        headers=headers,
    )
    if upload.status_code != 201:
        fail(f"upload returned {upload.status_code}: {upload.text}")
    source_id = upload.json()["id"]
    documents = api.get(f"/api/v1/knowledge-sources/{source_id}/documents", headers=headers).json()
    document_id = documents[0]["id"]
    print(f"    source {source_id}\n    document {document_id}")

    step(4, "Wait for background processing")
    started, last = time.time(), None
    while True:
        status = api.get(f"/api/v1/admin/documents/{document_id}/status", headers=headers).json()
        if status["processing_status"] != last:
            last = status["processing_status"]
            print(f"    {time.time() - started:6.1f}s  {last}")
        if last == FINAL_OK or last in FINAL_FAILED:
            break
        if time.time() - started > args.timeout:
            fail(f"still '{last}' after {args.timeout}s")
        time.sleep(2)
    for job in status["jobs"]:
        print(f"    - {job['stage']:<16} {job['status']:<10} {job['duration_ms'] or 0:>7} ms  {job['error_summary'] or ''}")
    if last != FINAL_OK:
        fail(f"processing ended as '{last}'")
    print(f"    chunks={status['chunk_count']} vectors={status['vector_count']} "
          f"edition={status['version_status']} searchable={status['searchable']}")
    if not status["searchable"] or status["chunk_count"] != status["vector_count"]:
        fail("document is not searchable or chunk/vector counts differ")

    step(5, "Search")
    query = args.query or marker
    found = api.post("/api/v1/research/search", json={"query": query, "top_k": 5}, headers=headers).json()
    print(f"    query={query!r} vector={found['vector_candidates']} keyword={found['keyword_candidates']} "
          f"degraded={found['degraded']} took={found['took_ms']}ms")
    for result in found["results"][:5]:
        src = result["source"]
        print(f"    {result['score']:.4f} {','.join(result['channels']):<15} {src['source_title']} | {src['citation']}")
    if not any(r["source"]["document_id"] == document_id for r in found["results"]):
        fail("the uploaded document was not found by search")

    step(6, "Audit trail")
    events = api.get(f"/api/v1/admin/audit-events?target_id={source_id}", headers=headers).json()
    actions = [e["action"] for e in events["items"]]
    print(f"    {actions}")
    if "knowledge_source.created" not in actions:
        fail("upload was not audited")

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
