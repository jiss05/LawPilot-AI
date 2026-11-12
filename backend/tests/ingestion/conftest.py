"""
Shared pytest fixtures for the ingestion tests.

* `settings`  - IngestionSettings pointing at a fresh temporary folder
* `fake_ocr`  - FakeOcrEngine instead of EasyOCR. Real OCR is slow and
                needs a 100 MB model download; the fake answers instantly
                and counts its calls, so tests can check WHEN OCR runs.
                (test_ingestion_real_ocr.py optionally uses real EasyOCR.)

pytest loads `conftest.py` automatically; tests never import it directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ingestion.config import IngestionSettings

from .helpers import FakeOcrEngine


@pytest.fixture
def settings(tmp_path: Path) -> IngestionSettings:
    # `_env_file=None` ignores any real backend/.env on the developer's PC,
    # so the tests behave the same on every machine.
    return IngestionSettings(
        _env_file=None,
        storage_dir=tmp_path / "documents",
        extracted_dir=tmp_path / "extracted",
        ocr_dpi=72,  # small images = fast tests
    )


@pytest.fixture
def fake_ocr() -> FakeOcrEngine:
    return FakeOcrEngine()
