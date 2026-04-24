from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

import img2pdf
import ocrmypdf

from filethat.config import Config

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".heic", ".heif", ".webp"}
HEIC_EXTENSIONS = {".heic", ".heif"}


def _detect_type(path: Path) -> str:
    with open(path, "rb") as f:
        header = f.read(12)

    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "webp"
    if header[:4] == b"%PDF":
        return "pdf"
    if header[:2] == b"\xff\xd8":
        return "jpeg"
    if header[:4] == b"\x89PNG":
        return "png"
    if header[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"

    ext = path.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    return "unknown"


def _to_pdf(path: Path, tmp_dir: Path) -> Path:
    ext = path.suffix.lower()

    if ext in HEIC_EXTENSIONS:
        import pillow_heif
        from PIL import Image

        pillow_heif.register_heif_opener()
        img = Image.open(path)
        png_path = tmp_dir / (path.stem + "_heic.png")
        img.save(png_path, "PNG")
        source = png_path
    else:
        source = path

    pdf_path = tmp_dir / (path.stem + "_img.pdf")
    with open(pdf_path, "wb") as f:
        f.write(img2pdf.convert(str(source)))
    return pdf_path


def _run_ocr(
    input_pdf: Path,
    output_pdf: Path,
    config: Config,
    *,
    force_ocr: bool = False,
    skip_text: bool = False,
    image_dpi: Optional[int] = None,
) -> None:
    lang = "+".join(config.ocr.languages)

    kwargs: dict = {
        "language": lang,
        "deskew": True,
        "clean": True,
        "optimize": 2,
        "rotate_pages": True,
        "rotate_pages_threshold": 12,
        "quiet": True,
        "output_type": config.ocr.output_type,
    }

    if skip_text:
        kwargs["skip_text"] = True
    elif force_ocr or config.ocr.force_reocr:
        kwargs["force_ocr"] = True
    else:
        kwargs["skip_text"] = True  # default: don't re-OCR existing text

    if image_dpi:
        kwargs["image_dpi"] = image_dpi

    ocrmypdf.ocr(str(input_pdf), str(output_pdf), **kwargs)


def _decrypt_pdf(path: Path, tmp_dir: Path) -> Path:
    decrypted = tmp_dir / (path.stem + "_decrypted.pdf")
    subprocess.run(
        ["qpdf", "--decrypt", str(path), str(decrypted)],
        check=True,
        capture_output=True,
    )
    return decrypted


def normalize(source: Path, config: Config, tmp_dir: Path) -> tuple[Path, bool]:
    """
    Normalize source to an OCR'd PDF.
    Returns (ocr_pdf_path, ocr_skipped).
    """
    ftype = _detect_type(source)
    ext = source.suffix.lower()

    if ext in IMAGE_EXTENSIONS or ftype in ("jpeg", "png", "tiff", "webp", "image"):
        logger.info("Converting image to PDF", extra={"source": str(source)})
        input_pdf = _to_pdf(source, tmp_dir)
    elif ftype == "pdf" or ext == ".pdf":
        input_pdf = source
    else:
        raise ValueError(f"Unsupported file type: {source.suffix!r}")

    output_pdf = tmp_dir / (source.stem + "_ocr.pdf")
    ocr_skipped = False

    try:
        _run_ocr(input_pdf, output_pdf, config)
    except ocrmypdf.exceptions.PriorOcrFoundError:
        logger.warning("Prior OCR found, retrying with skip-text", extra={"source": str(source)})
        _run_ocr(input_pdf, output_pdf, config, skip_text=True)
        ocr_skipped = True
    except ocrmypdf.exceptions.EncryptedPdfError:
        logger.warning("Encrypted PDF, decrypting first", extra={"source": str(source)})
        input_pdf = _decrypt_pdf(input_pdf, tmp_dir)
        _run_ocr(input_pdf, output_pdf, config)
    except Exception as exc:
        exc_name = type(exc).__name__
        if "DpiError" in exc_name or "dpi" in str(exc).lower():
            logger.warning("DPI issue, retrying with image-dpi 300", extra={"source": str(source)})
            _run_ocr(input_pdf, output_pdf, config, image_dpi=300)
        else:
            raise

    return output_pdf, ocr_skipped
