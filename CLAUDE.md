# filethat — Development guidelines

## Code style
- Python 3.12, type hints everywhere, `from __future__ import annotations` at top of every module
- Format with `ruff format`, lint with `ruff check`
- Max line 100
- Prefer pure functions; side effects isolated in `pipeline.py` and `cli.py`
- Use `pathlib.Path`, never `os.path`
- Use `logging` (not `print`) with structured extras

## Architecture rules
- No database. Journal is CSV. State lives on filesystem.
- No queue, no worker, no async except where FastAPI requires it
- One file = one responsibility; keep modules under ~200 lines
- No framework beyond FastAPI. No LangChain, no Celery, no SQLAlchemy.
- All config via `config.yaml` + `.env`. No hardcoded values.

## LLM rules
- Always use tool use / function calling with strict schema. Never parse free text.
- Retry transient errors (network, 429, 5xx) with exponential backoff via `tenacity`
- Never retry on 4xx other than 429
- Truncate inputs aggressively: 5 pages / 15k chars default

## Pipeline invariants
- `inbox/` only contains unprocessed files
- Every processed file appears in `journal.csv` exactly once per hash
- `library/` is immutable at the file level (never overwrite; suffix on collision)
- Failures never lose data: source → `failed/<id>/`; intermediate OCR preserved if produced

## Adding a document type
1. Add entry to `config.yaml` under `referential.document_types` (key + fr + en labels)
2. No code change required

## Adding an LLM provider
1. Implement `Classifier` protocol in `classify.py`
2. Add to factory in `get_classifier()`
3. Document env var in `.env.example`

## Testing philosophy
- Unit tests only. No integration tests with real LLM calls.
- Keep fixtures small and representative.
- Run: `make test`
