"""
Image loader for scanned documents (PNG, JPEG, TIFF).

Images have no text layer, so EVERY page must go through OCR. This loader
only prepares the page images; `extractor.py` sends them to the OCR engine.

Multi-page TIFF is the classic format for scanned court records: one file,
many "frames", one frame per page. Pillow's `ImageSequence` walks the
frames, and the frame index + 1 becomes the page number.

Pillow is installed automatically with EasyOCR (pip install pillow
otherwise).
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageSequence, UnidentifiedImageError

from app.ingestion.errors import ExtractionError, ExtractionErrorCode


def load_page_images(path: Path, max_pages: int) -> list[bytes]:
    """
    Return one grayscale PNG (as bytes) per page/frame.

    Raises CORRUPTED_FILE if Pillow cannot decode the image.
    """
    try:
        # First pass: `verify()` checks the file structure without decoding
        # every pixel. After verify() the image object is unusable, so we
        # open the file a second time to actually read it.
        with Image.open(path) as probe:
            probe.verify()

        page_images: list[bytes] = []
        with Image.open(path) as image:
            for index, frame in enumerate(ImageSequence.Iterator(image)):
                if index >= max_pages:
                    raise ExtractionError(
                        ExtractionErrorCode.TOO_MANY_PAGES,
                        f"The image has more than {max_pages} pages.",
                        details={"limit": max_pages},
                    )
                buffer = io.BytesIO()
                frame.convert("L").save(buffer, format="PNG")  # "L" = grayscale
                page_images.append(buffer.getvalue())
    except ExtractionError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        # Pillow raises different exception types for different kinds of
        # damage (truncated data, bad header, ...); all mean "corrupted".
        raise ExtractionError(
            ExtractionErrorCode.CORRUPTED_FILE,
            "The image could not be decoded; it may be damaged.",
            details={"reason": str(exc)},
        ) from exc

    return page_images
