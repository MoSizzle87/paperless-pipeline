# Test Fixtures

Place sample documents here to enable integration tests for `normalize.py`.

## Supported formats

- `*.pdf` — any PDF (with or without existing text layer)
- `*.jpg` / `*.jpeg` — JPEG images
- `*.png` — PNG images
- `*.tiff` / `*.tif` — TIFF images
- `*.heic` / `*.heif` — Apple HEIC images (requires `pillow-heif`)

## What the tests verify

- PDF input → OCR'd PDF with a text layer
- Image input → PDF with a text layer
- `normalize()` returns `(Path, bool)` tuple

## Notes

- Keep fixtures small (< 1 MB). A one-page scan is ideal.
- Fixtures are not committed to the repository (`.gitignore` excludes non-`.gitkeep` files here).
- Run `make test` inside the container to exercise these tests with all system dependencies available.
