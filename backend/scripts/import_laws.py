"""
Bulk-import Indian Acts into the LawPilot knowledge base.

For every Act in scripts/law_manifest.json this script:
  1. skips it if the knowledge base already has it (same title, or same PDF),
  2. downloads the official English PDF (India Code first, then the listed
     official fallbacks) and keeps a copy in storage/law_downloads/,
  3. registers it as a legal source exactly like an admin upload does,
  4. runs the real pipeline in this process: extraction -> cleaning and
     chunking -> embeddings -> Qdrant + PostgreSQL -> activation,
  5. prints whether the Act is now searchable, and records everything in
     the audit log under the admin account.

Run from backend/ with the virtual environment active, the Docker PC
(PostgreSQL + Qdrant) on, and internet access:

    python scripts/import_laws.py --list                 # what would be imported
    python scripts/import_laws.py                        # import everything missing
    python scripts/import_laws.py --only bnss bsa        # just these
    python scripts/import_laws.py --download-only        # fetch PDFs, import nothing

If a site refuses the download, put the PDF yourself in
backend/storage/law_downloads/<slug>.pdf and run the script again.
Imported Acts can be removed with the Delete button on Admin -> Legal Sources.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

MANIFEST = Path(__file__).with_name("law_manifest.json")
DOWNLOADS = BACKEND / "storage" / "law_downloads"
MAX_BYTES = 20 * 1024 * 1024
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 LawPilot-importer",
    "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
}
_PDF_HREF = re.compile(r'href="([^"]*?/bitstream/[^"]+?\.pdf)[^"]*"', re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def norm(text: str) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower().replace("-", " "))
    words = [w for w in text.split() if w not in {"the", "of", "and"}]
    return " ".join(words)


def same_act(a: str, b: str) -> bool:
    """'Indian Contract Act, 1872' == 'indian-contract-act'; years must agree when both have one."""
    na, nb = norm(a), norm(b)
    ya, yb = re.findall(r"\b(1[89]\d\d|20\d\d)\b", na), re.findall(r"\b(1[89]\d\d|20\d\d)\b", nb)
    if ya and yb and set(ya).isdisjoint(yb):
        return False
    wa = {w for w in na.split() if not w.isdigit()}
    wb = {w for w in nb.split() if not w.isdigit()}
    return bool(wa) and bool(wb) and (wa <= wb or wb <= wa)


def encode_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=quote(parts.path, safe="/%"), query=parts.query))


def looks_english(pdf: bytes, title: str) -> tuple[bool, str]:
    """The PDF has a text layer, is mostly Latin script and names the Act."""
    import fitz  # PyMuPDF, already a backend dependency

    try:
        doc = fitz.open(stream=pdf, filetype="pdf")
    except Exception as exc:
        return False, f"not a readable PDF ({type(exc).__name__})"
    sample = "".join(doc[i].get_text() for i in range(min(6, doc.page_count)))
    letters = [c for c in sample if c.isalpha()]
    if len(letters) < 300:
        return False, "no text layer (scanned) in the first pages"
    latin = sum(1 for c in letters if c.isascii()) / len(letters)
    if latin < 0.7:
        return False, "mostly non-English text (probably the Hindi edition)"
    key = [w for w in norm(title).split() if not w.isdigit()][:3]
    if not all(w in norm(sample) for w in key):
        return False, "the first pages do not name this Act"
    return True, f"{doc.page_count} pages"


class Fetcher:
    def __init__(self, insecure: bool) -> None:
        import httpx

        self.client = httpx.Client(headers=HEADERS, follow_redirects=True, timeout=90, verify=not insecure)

    def get(self, url: str) -> bytes | None:
        try:
            response = self.client.get(encode_url(url))
        except Exception as exc:
            print(f"      x {url[:90]} ({type(exc).__name__})")
            return None
        if response.status_code != 200:
            print(f"      x {url[:90]} (HTTP {response.status_code})")
            return None
        return response.content

    def candidates_from_handle(self, handle: str) -> list[str]:
        page = self.get(handle)
        if not page:
            return []
        hrefs = list(dict.fromkeys(_PDF_HREF.findall(page.decode("utf-8", "ignore"))))
        handle_id = handle.rstrip("/").split("/")[-1]

        def rank(href: str) -> tuple:
            name = href.rsplit("/", 1)[-1]
            return (
                f"/{handle_id}/" not in href,              # this Act's own files first
                name[:1] in "Hh",                          # Hindi editions last
                not name[:1] in "Aa",                      # 'A1996-26.pdf' style = English Act text
                len(name),
            )

        return [urljoin(handle, h) for h in sorted(hrefs, key=rank)]


def obtain_pdf(act: dict, fetcher: Fetcher) -> tuple[bytes | None, str]:
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    cached = DOWNLOADS / f"{act['slug']}.pdf"
    if cached.exists():
        data = cached.read_bytes()
        ok, why = looks_english(data, act["title"])
        if ok:
            return data, f"local file {cached.name} ({why})"
        print(f"      x local {cached.name}: {why}")

    urls = list(act.get("pdf_urls") or [])
    if act.get("handle"):
        print(f"    - looking up {act['handle']}")
        urls = fetcher.candidates_from_handle(act["handle"])[:6] + urls
    for url in dict.fromkeys(urls):
        data = fetcher.get(url)
        if not data:
            continue
        if not data.startswith(b"%PDF-"):
            print(f"      x {url[:90]} (not a PDF)")
            continue
        if len(data) > MAX_BYTES:
            print(f"      x {url[:90]} (larger than 20 MB)")
            continue
        ok, why = looks_english(data, act["title"])
        if not ok:
            print(f"      x {url[:90]} ({why})")
            continue
        cached.write_bytes(data)
        return data, f"{url} ({why})"
    return None, "no usable PDF found"


# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="+", metavar="SLUG", help="import only these (see --list)")
    parser.add_argument("--list", action="store_true", help="show the Acts and whether each is already imported")
    parser.add_argument("--download-only", action="store_true", help="download the PDFs but import nothing")
    parser.add_argument("--admin-email", help="admin account recorded as uploader (default: first admin)")
    parser.add_argument("--visibility", default="public", choices=["public", "internal"])
    parser.add_argument("--insecure", action="store_true", help="skip TLS certificate checks (only if a government site's certificate is broken)")
    args = parser.parse_args()

    acts = json.loads(MANIFEST.read_text(encoding="utf-8"))["acts"]
    if args.only:
        wanted = {s.lower() for s in args.only}
        unknown = wanted - {a["slug"] for a in acts}
        if unknown:
            print(f"Unknown slug(s): {', '.join(sorted(unknown))}. Use --list.")
            return 2
        acts = [a for a in acts if a["slug"] in wanted]

    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.knowledge_document import KnowledgeDocument
    from app.models.knowledge_source import KnowledgeSource
    from app.models.role import Role
    from app.models.user import User
    from app.models.user_role import UserRole

    with SessionLocal() as db:
        existing = {s.id: s.title for s in db.scalars(select(KnowledgeSource)).all()}
        hashes = set(db.scalars(select(KnowledgeDocument.sha256)).all())
        query = select(User).join(UserRole, UserRole.user_id == User.id).join(Role, Role.id == UserRole.role_id) \
            .where(Role.code == "ADMIN", User.is_active.is_(True))
        if args.admin_email:
            query = query.where(User.email == args.admin_email.lower())
        admin = db.scalars(query.order_by(User.created_at)).first()

    def already(act):
        return next((t for t in existing.values() if same_act(act["title"], t)), None)

    if args.list:
        print(f"{'slug':<12} {'status':<22} title")
        for act in acts:
            hit = already(act)
            print(f"{act['slug']:<12} {('have: ' + hit[:15]) if hit else 'to import':<22} {act['title']}")
        return 0

    if admin is None and not args.download_only:
        print("No active ADMIN account found. Create one with python scripts/create_admin.py, or pass --admin-email.")
        return 1

    fetcher = Fetcher(args.insecure)
    summary: list[tuple[str, str]] = []

    from app.ingestion.tasks import process_uploaded_document
    from app.services.knowledge_source_service import register_legal_source

    for number, act in enumerate(acts, 1):
        print(f"\n[{number}/{len(acts)}] {act['title']}")
        hit = already(act)
        if hit:
            print(f"    = already in the knowledge base as '{hit}', skipped")
            summary.append((act["slug"], "skipped (already present)"))
            continue

        pdf, origin = obtain_pdf(act, fetcher)
        if pdf is None:
            print(f"    ! {origin}. Download it by hand from {act['handle']} and save it as "
                  f"{DOWNLOADS / (act['slug'] + '.pdf')}, then run again.")
            summary.append((act["slug"], "FAILED: no PDF"))
            continue
        print(f"    + PDF: {origin}")

        import hashlib

        if hashlib.sha256(pdf).hexdigest() in hashes:
            print("    = this exact PDF is already in the knowledge base, skipped")
            summary.append((act["slug"], "skipped (same PDF already present)"))
            continue
        if args.download_only:
            summary.append((act["slug"], "downloaded"))
            continue

        started = time.time()
        with SessionLocal() as db:
            source, document = register_legal_source(
                db,
                title=act["title"],
                source_type="statute",
                jurisdiction="India",
                trust_tier="official",
                publisher="Legislative Department, Ministry of Law and Justice, Government of India",
                canonical_url=act.get("handle"),
                version_label=f"{act.get('act', '')}; India Code text downloaded {date.today():%d %b %Y}".strip("; "),
                published_at=date.fromisoformat(act["enacted"]) if act.get("enacted") else None,
                original_filename=f"{act['slug']}.pdf",
                file_content=pdf,
                uploaded_by=admin.id,
                visibility=args.visibility,
                request_id=f"import-laws-{act['slug']}",
            )
            document_id, source_id = document.id, source.id
        existing[source_id] = act["title"]
        print("    > processing: extraction -> chunking -> embeddings -> Qdrant -> activation ...")
        process_uploaded_document(document_id, admin.id)

        with SessionLocal() as db:
            from app.models.document_chunk import DocumentChunk
            from sqlalchemy import func

            doc = db.get(KnowledgeDocument, document_id)
            chunks = db.scalar(select(func.count()).select_from(DocumentChunk)
                               .where(DocumentChunk.knowledge_document_id == document_id))
            status = doc.processing_status if doc else "missing"
        took = time.time() - started
        ok = status in ("indexed", "ready", "completed")
        print(f"    {'OK' if ok else '!!'} status={status}, {chunks} chunks, {took:.0f} s")
        summary.append((act["slug"], f"{'imported' if ok else 'PROBLEM'}: {status}, {chunks} chunks"))

    print("\n=== Summary ===")
    for slug, result in summary:
        print(f"  {slug:<12} {result}")
    print("\nCheck Admin -> Monitoring -> Ingestion for details of any problem.")
    return 0 if all(not r.startswith(("FAILED", "PROBLEM")) for _, r in summary) else 1


if __name__ == "__main__":
    sys.exit(main())
