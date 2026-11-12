"""
Format-specific loaders.

Each loader knows how to read ONE file format and returns a list of
`PageText` objects. Loaders do NOT decide about OCR; that decision lives
in `app/ingestion/extractor.py`, which keeps each loader small and easy
to test on its own.

    pdf_loader.py    - PyMuPDF: native text per page + render a page to PNG
    docx_loader.py   - python-docx: paragraphs and tables, in document order
    txt_loader.py    - plain text with encoding detection
    image_loader.py  - PNG/JPEG/TIFF: split into page images for OCR
"""
