"""
Plain-text loader.

THE ONLY HARD PART: ENCODINGS
-----------------------------
A .txt file is just bytes; the same bytes mean different characters in
different encodings. Files we may receive:
  * UTF-8 (modern default; may start with a "BOM" on Windows)
  * UTF-16 (Windows Notepad "Unicode")
  * Windows-1252 / cp1252 (older Windows files, e.g. "§" or curly quotes)

We try the strict decoders first and fall back step by step. `latin-1`
can decode ANY byte sequence, so it is the final safety net; if we need
it, we add a warning because some characters may be wrong.

PAGES IN TEXT FILES
-------------------
Plain text normally has no pages. Tools such as `pdftotext` insert a
form-feed character ("\f") between pages, so if we see "\f" we split on
it and number the pages. Otherwise page_number is None.
"""

from __future__ import annotations

from pathlib import Path

from app.ingestion.extraction_types import ExtractionMethod, PageText

FORM_FEED = "\f"


def decode_text(raw: bytes) -> tuple[str, str]:
    """Return (text, encoding_used)."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16"
    for encoding in ("utf-8-sig", "cp1252"):  # utf-8-sig also strips a BOM
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1"


def extract_txt_pages(path: Path) -> tuple[list[PageText], bool, list[str]]:
    """
    Return (pages, page_numbers_found, document_warnings).
    """
    text, encoding = decode_text(path.read_bytes())
    warnings: list[str] = []
    if encoding not in ("utf-8-sig", "utf-16"):
        warnings.append(f"decoded_as_{encoding.replace('-', '_')}")

    # Normalise Windows (\r\n) and old Mac (\r) line endings to \n.
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    if FORM_FEED in text:
        parts = text.split(FORM_FEED)
        # A trailing form feed creates an empty last "page"; drop it.
        if parts and not parts[-1].strip():
            parts = parts[:-1]
        pages = [
            PageText(number, part, ExtractionMethod.NATIVE)
            for number, part in enumerate(parts, start=1)
        ]
        return pages, True, warnings

    return [PageText(None, text, ExtractionMethod.NATIVE)], False, warnings
