from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _has_pdfs() -> bool:
    return any(FIXTURES.glob("*.pdf"))


def _has_images() -> bool:
    exts = ["*.jpg", "*.jpeg", "*.png"]
    return any(f for ext in exts for f in FIXTURES.glob(ext))


@pytest.mark.skipif(not _has_pdfs(), reason="No PDF fixtures in tests/fixtures/")
def test_pdf_produces_text_layer(tmp_path):
    import pypdf

    from filethat.config import Config
    from filethat.normalize import normalize

    config = Config.model_validate(
        {"ocr": {"languages": ["fra", "eng"], "force_reocr": False, "output_type": "pdf"}}
    )

    pdf_files = list(FIXTURES.glob("*.pdf"))
    ocr_pdf, _ = normalize(pdf_files[0], config, tmp_path)

    assert ocr_pdf.exists()
    assert ocr_pdf.suffix == ".pdf"

    reader = pypdf.PdfReader(str(ocr_pdf))
    assert len(reader.pages) > 0
    text = "".join(p.extract_text() or "" for p in reader.pages)
    assert len(text) > 0, "OCR'd PDF should have a text layer"


@pytest.mark.skipif(not _has_images(), reason="No image fixtures in tests/fixtures/")
def test_image_converts_to_pdf_with_text_layer(tmp_path):
    import pypdf

    from filethat.config import Config
    from filethat.normalize import normalize

    config = Config.model_validate(
        {"ocr": {"languages": ["fra", "eng"], "force_reocr": False, "output_type": "pdf"}}
    )

    image_files = [f for ext in ["*.jpg", "*.jpeg", "*.png"] for f in FIXTURES.glob(ext)]
    ocr_pdf, _ = normalize(image_files[0], config, tmp_path)

    assert ocr_pdf.exists()
    assert ocr_pdf.suffix == ".pdf"

    reader = pypdf.PdfReader(str(ocr_pdf))
    assert len(reader.pages) > 0
    text = "".join(p.extract_text() or "" for p in reader.pages)
    assert len(text) > 0, "Image→OCR PDF should have a text layer"


@pytest.mark.skipif(not (_has_pdfs() or _has_images()), reason="No fixtures present")
def test_normalize_returns_tuple(tmp_path):
    from filethat.config import Config
    from filethat.normalize import normalize

    config = Config.model_validate(
        {"ocr": {"languages": ["fra", "eng"], "force_reocr": False, "output_type": "pdf"}}
    )

    candidates = list(FIXTURES.glob("*.pdf")) + list(FIXTURES.glob("*.jpg"))
    ocr_pdf, ocr_skipped = normalize(candidates[0], config, tmp_path)

    assert isinstance(ocr_pdf, Path)
    assert isinstance(ocr_skipped, bool)
