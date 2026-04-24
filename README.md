# filethat

A single-container document classification pipeline. Drop files in, run one command, get a named and organized archive.

**What it does:** OCRs documents, classifies them with an LLM (Anthropic or OpenAI), and moves them to `data/library/<Type>/YYYY-MM_Type_Correspondent_title.pdf`. Every run is logged to `data/journal.csv`.

## Quick start

```bash
git clone https://github.com/your-org/filethat.git
cd filethat
cp .env.example .env          # add your ANTHROPIC_API_KEY or OPENAI_API_KEY
make install                  # builds the Docker image (~2 min first time)
# drop a PDF or image into data/inbox/
make scan
```

That's it. Check `data/library/` for the result and `data/journal.csv` for the log.

## Commands

| Command | Description |
|---|---|
| `make install` | Build Docker image |
| `make scan` | Process all files in `data/inbox/` |
| `make ui` | Launch web dashboard at http://localhost:8000 |
| `make stats` | Print journal summary (total, success, errors, low-confidence) |
| `make archive` | Move `data/library/` into `data/archive/<timestamp>/` |
| `make delete-archive` | Delete all archives (prompts for confirmation) |
| `make clean-failed` | Delete all failed entries (prompts for confirmation) |
| `make reset` | Wipe everything — inbox, library, failed, archive, journal (double confirmation) |
| `make shell` | Open a shell inside the container |
| `make test` | Run test suite |
| `make logs` | Tail last 100 lines of `data/filethat.log` |

## Supported input formats

- PDF (with or without existing text layer)
- JPEG, PNG, TIFF
- HEIC/HEIF (Apple photos)
- WebP

## Configuration

Edit `config.yaml` (mounted read-only into the container):

```yaml
language: fr        # fr | en — folder names and UI language
llm:
  provider: anthropic   # anthropic | openai
  model: claude-sonnet-4-6
ocr:
  languages: [fra, eng]
  force_reocr: false
```

Set secrets in `.env` (not committed):

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...        # only needed if provider: openai
LOG_LEVEL=INFO
```

## Adding document types

Add an entry to `referential.document_types` in `config.yaml`:

```yaml
- key: contract
  fr: Contrat
  en: Contract
```

No code change needed.

## Adding correspondents

Add a string to `referential.correspondents` in `config.yaml`. The LLM will prefer these values but can also identify new ones automatically (flagged as `new_correspondent: true` in the journal).

## File naming

`{YYYY-MM}_{TypeLabel}_{Correspondent}_{title-slug}.pdf`

- `TypeLabel` uses the label matching `config.language` (e.g. `Facture` for `fr`, `Invoice` for `en`)
- If no date found: prefix is `nodate`
- Collisions get a `_2`, `_3`, … suffix

## Troubleshooting

**`PriorOcrFoundError`** — The PDF already has a text layer. The pipeline retries automatically with `--skip-text`. If you want to force re-OCR, set `ocr.force_reocr: true` in `config.yaml`.

**`EncryptedPdfError`** — The PDF is password-protected. The pipeline attempts `qpdf --decrypt` automatically. If it still fails, decrypt the file manually before dropping it in `inbox/`.

**DPI warnings** — Low-resolution scans may trigger a retry with `--image-dpi 300`. Very degraded scans may produce poor OCR quality regardless.

**LLM 429 / rate limit** — `tenacity` retries up to 3 times with exponential backoff (2s, 4s, 8s). If the API is consistently unavailable, the file lands in `data/failed/` with an `error.json`.

**File stuck in `failed/`** — Check `data/failed/<id>_<timestamp>/error.json` for the stage and traceback. Fix the root cause, then use the web UI "Reprocess" button or manually move the file back to `inbox/`.

## Web UI

```bash
make ui   # http://localhost:8000
```

Shows all processed documents with filter buttons (All / Success / Errors / Low confidence). Click a document title to view the PDF. Use the "Reprocess" button on error rows to move the original back to `inbox/`.

## License

MIT
