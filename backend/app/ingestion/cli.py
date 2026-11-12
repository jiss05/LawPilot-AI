"""
Command-line tool for trying text extraction by hand.

Run from the `backend` folder (with your virtual environment active):

  # 1) Extract any file - NO database needed. Prints a page summary.
  python -m app.ingestion.cli extract path\\to\\judgment.pdf

  #    ...also show the first 300 characters of every page
  python -m app.ingestion.cli extract path\\to\\judgment.pdf --show-text 300

  #    ...save the full page-by-page JSON
  python -m app.ingestion.cli extract scan.pdf --output scan.extracted.json

  #    ...skip OCR (fast check of the native text layer only)
  python -m app.ingestion.cli extract scan.pdf --no-ocr

  # 2) Run the real pipeline for a knowledge_documents row (needs Postgres
  #    and DATABASE_URL in backend/.env). Records the ingestion job.
  python -m app.ingestion.cli run <document_uuid> --user <admin_user_uuid>

Why `python -m app.ingestion.cli` and not `python app/ingestion/cli.py`?
`-m` runs the file as part of the `app` package, so imports such as
`from app.ingestion...` work.

Until the admin upload API exists (next story), this CLI is how a
Knowledge-Base Administrator triggers extraction.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from uuid import UUID

from app.ingestion.config import get_ingestion_settings
from app.ingestion.errors import ExtractionError
from app.ingestion.extractor import DocumentExtractor


def _print_result(result, show_text: int) -> None:
    summary = result.summary()
    print("\n=== Extraction summary ===")
    for key, value in summary.items():
        print(f"  {key:<22} {value}")

    print("\n=== Pages ===")
    print(f"  {'page':>5}  {'method':<7} {'chars':>7}  {'ocr_conf':>8}  warnings")
    for page in result.pages:
        number = page.page_number if page.page_number is not None else "-"
        conf = f"{page.ocr_confidence:.2f}" if page.ocr_confidence is not None else ""
        print(
            f"  {number:>5}  {page.method.value:<7} {page.char_count:>7}  "
            f"{conf:>8}  {', '.join(page.warnings)}"
        )
        if show_text:
            preview = page.text[:show_text].replace("\n", " ")
            print(f"         > {preview}")


def cmd_extract(args: argparse.Namespace) -> int:
    settings = get_ingestion_settings()
    if args.no_ocr:
        settings = settings.model_copy(update={"ocr_enabled": False})

    try:
        result = DocumentExtractor(settings).extract(Path(args.file))
    except ExtractionError as exc:
        # This is how failures look to an administrator.
        print(f"\nEXTRACTION FAILED: {exc}")
        if exc.details:
            print(f"details: {json.dumps(exc.details, indent=2, default=str)}")
        return 1

    _print_result(result, args.show_text)

    if args.output:
        Path(args.output).write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nSaved full result to {args.output}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    # Imported here because app.db.session needs DATABASE_URL at import
    # time; the `extract` command must work without a database.
    from app.db.session import SessionLocal
    import app.models  # noqa: F401  (registers every model for foreign keys)
    from app.ingestion.pipeline import JobStatus, run_extraction

    with SessionLocal() as db:
        job = run_extraction(db, UUID(args.document_id), UUID(args.user))
        print(f"Ingestion job {job.id}: {job.status}")
        if job.error_summary:
            print(f"Error: {job.error_summary}")
        print(json.dumps(job.counts, indent=2, default=str))
        return 0 if job.status == JobStatus.COMPLETED else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.ingestion.cli",
        description="LawPilot document text extraction tool",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="show debug logs")
    sub = parser.add_subparsers(dest="command", required=True)

    p_extract = sub.add_parser("extract", help="extract a local file (no database)")
    p_extract.add_argument("file")
    p_extract.add_argument("--no-ocr", action="store_true", help="disable OCR")
    p_extract.add_argument("--show-text", type=int, default=0, metavar="N",
                           help="print the first N characters of each page")
    p_extract.add_argument("--output", help="write the full JSON result here")
    p_extract.set_defaults(func=cmd_extract)

    p_run = sub.add_parser("run", help="run the pipeline for a knowledge_documents row")
    p_run.add_argument("document_id")
    p_run.add_argument("--user", required=True, help="UUID of the initiating admin")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
