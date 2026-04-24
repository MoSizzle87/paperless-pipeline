# DESIGN.md — filethat

This document describes the design decisions behind filethat. It is intended for readers who want to understand *why* the project is structured the way it is, not just *how* it works.

The format for each section is: **Problem → Decision → Alternatives considered → Status**.

## Table of contents

1. [Scope and non-goals](#1-scope-and-non-goals)
2. [Pipeline architecture](#2-pipeline-architecture)
3. [Why not Paperless-ngx](#3-why-not-paperless-ngx)
4. [Execution model — manual over continuous](#4-execution-model--manual-over-continuous)
5. [OCR strategy](#5-ocr-strategy)
6. [LLM classification](#6-llm-classification)
7. [Naming convention and collisions](#7-naming-convention-and-collisions)
8. [Idempotency and state](#8-idempotency-and-state)
9. [Concurrency and safety](#9-concurrency-and-safety)
10. [Human-in-the-loop review](#10-human-in-the-loop-review)
11. [Indexing strategy](#11-indexing-strategy)
12. [Quality measurement](#12-quality-measurement)
13. [Cost optimization](#13-cost-optimization)
14. [Extensibility](#14-extensibility)
15. [Deduplication](#15-deduplication)
16. [Retention policy](#16-retention-policy)
17. [Observability](#17-observability)
18. [Security and privacy](#18-security-and-privacy)

---

## 1. Scope and non-goals

**Problem.** Personal administrative documents accumulate over years in multiple formats (scanned PDFs, native PDFs, phone pictures, downloads from institutional portals). Finding a specific document months later requires either rigorous manual filing at ingestion time (which nobody sustains) or full-text search over a messy archive.

**Decision.** filethat is a one-shot command-line pipeline that takes a folder of unorganized documents and produces a folder tree organized by document type, with filenames that encode date, type, correspondent, and a short title. Every output file is a PDF/A with an embedded OCR text layer.

**Non-goals** (explicitly out of scope):
- Multi-user access, authentication, or sharing
- Cloud storage integration (S3, GCS, Drive) for the library
- Continuous watching of the inbox folder
- Full document management (tags, annotations, versioning)
- Re-classification of existing library files

The project deliberately stops at "file is correctly named and placed". Any downstream use (search, analytics, retention) consumes the filesystem layout or the journal.

**Status.** Implemented.

---

## 2. Pipeline architecture

The pipeline is a single linear flow, processed one file at a time:

```
inbox/<file>
   │
   ├─► hash check vs journal ─► skip if duplicate
   │
   ├─► normalize: image→PDF via img2pdf, else passthrough
   │
   ├─► OCR with ocrmypdf (PDF/A-2b output, text layer embedded)
   │
   ├─► text extraction via pypdf (first 5 pages, 15k chars max)
   │
   ├─► LLM classification with structured output (tool use)
   │
   ├─► path construction: library/<Type>/<YYYY-MM>_<Type>_<Correspondent>_<slug>.pdf
   │
   ├─► move OCR'd PDF to target path (collision-safe)
   │
   └─► append success row to journal.csv, delete source
```

On any failure, the source is moved to `data/failed/<id>/` with an `error.json` describing the stage and exception. The OCR intermediate is preserved when possible to avoid re-doing the expensive step on retry.

**Decision.** Linear, synchronous, one file at a time. No queues, no workers, no async.

**Alternatives considered.**
- Celery + Redis for async workers: rejected. Adds two containers and a broker for processing volumes that fit on a single thread (~10 seconds per document including LLM call).
- `asyncio` with an event loop: rejected. `ocrmypdf` and `pypdf` are CPU-bound and block the loop; the complexity isn't worth it for sequential document counts.
- Separate services for OCR and classification: rejected. Premature decomposition.

**Status.** Implemented.

---

## 3. Why not Paperless-ngx

Paperless-ngx is the reference open-source document management tool. filethat originally consumed it as a dependency. After using the combined stack on ~170 documents, three observations emerged:

1. **The Paperless abstractions didn't add value for this use case.** Tags, correspondents, and document types in Paperless were being overwritten on every run by the LLM output. Paperless was used as an OCR service and blob store, not as a DMS.
2. **Five containers for what is essentially a file-mover is disproportionate.** Postgres, Redis, the webserver, the consumer, and the custom classifier — all to end up with files on disk.
3. **The source of truth was ambiguous.** The filesystem under `library/` and Paperless's database held overlapping information, with neither being authoritative.

**Decision.** Collapse to a single container. Filesystem is the sole source of truth. `journal.csv` is append-only and reconstructible if lost.

**Alternatives considered.**
- Keep Paperless as the storage layer, filethat as an ingestion sidecar: rejected for operational complexity.
- Replace Paperless with a minimal Django app: rejected as reinventing the same abstractions.

**Status.** Implemented. The original filethat (Paperless-based) is archived in a separate branch.

---

## 4. Execution model — manual over continuous

**Problem.** How should the pipeline be triggered? Continuous folder watching, cron schedule, or manual command?

**Decision.** Manual, via `make scan`. No daemon, no watchdog, no scheduler.

**Rationale.**
- The user decides when to process. There is no SLA on personal document classification.
- No long-running process means no resource footprint between runs, no supervisor needed, no "did it crash silently?" concern.
- Errors are immediately visible in the terminal, not buried in a log file the user won't read.
- Idempotency of the pipeline means running it twice is harmless — removing the temptation to add "is this the right moment to process?" logic.

**Alternatives considered.**
- `watchdog` library on the inbox folder: rejected. Docker volume events on macOS/Colima are unreliable; partial-write race conditions require debounce logic that adds complexity without user-visible benefit.
- Cron schedule (e.g. every hour): rejected. Either the user is actively using the tool (and 10 seconds of manual latency doesn't matter) or they're not (and a scheduled run is noise).

**Status.** Implemented.

---

## 5. OCR strategy

**Problem.** Input documents fall in four categories:
- Native PDFs with a correct text layer (most institutional exports)
- Scanned PDFs without text (scanner output, fax archives)
- Images (phone pictures, screenshots)
- PDFs with partial or corrupted text layers

A single OCR approach doesn't fit all four.

**Decision.** Use [`ocrmypdf`](https://ocrmypdf.readthedocs.io/) as the single entry point for OCR. Its default behavior (`--skip-text`) preserves existing text layers and only OCRs pages that need it. For images, convert to PDF via `img2pdf` first.

Every output is PDF/A-2b with an embedded text layer, regardless of input.

**Why ocrmypdf over alternatives.**
- Wraps Tesseract, Ghostscript, qpdf, unpaper, pngquant in a pipeline that handles deskew, rotation, cleanup, and PDF/A conversion.
- Detects and handles prior OCR, encrypted PDFs, and low-DPI images explicitly.
- Produces archival-quality output (PDF/A-2b) as a single flag.

**Alternatives considered.**
- Tesseract directly: rejected. Requires reimplementing deskew, rotation, PDF merging, text-layer embedding, and PDF/A conversion — all already in ocrmypdf.
- LLM Vision APIs for OCR (Claude Vision, GPT-4V): rejected as primary OCR. Cost per page is 10–50× Tesseract, and accuracy on clean institutional documents is not meaningfully better. Reserved as potential fallback (see §14).
- Surya, docTR, PaddleOCR: rejected. Excellent accuracy but require PyTorch + GPU for reasonable performance. For administrative documents the quality gain over Tesseract doesn't justify the image size increase (several GB) and the CPU overhead.

**Multilingual support.** Tesseract is invoked with `--language fra+eng` by default, configurable in `config.yaml`. Both traineddata files are installed in the container image.

**Status.** Implemented.

---

## 6. LLM classification

**Problem.** Classification of an administrative document requires understanding context (is "Caisse d'Épargne" a bank statement or marketing?), dates (which date is the document's date among several mentioned?), and the issuing entity. Rule-based approaches (regex, keyword matching) fail on unseen formats.

**Decision.** Use a general-purpose LLM with a tool-use schema that forces structured output. Two providers supported: Anthropic Claude (default: `claude-sonnet-4-6`) and OpenAI GPT (default: `gpt-4o`).

**Schema.**

```python
class ClassificationResult(BaseModel):
    document_type: str       # key from config.referential.document_types
    correspondent: str       # organization name or "Unknown"
    document_date: str | None  # ISO YYYY-MM-DD
    title: str               # short descriptor, 3–8 words
    language: Literal["fr", "en", "other"]
    confidence: float        # 0.0–1.0, self-assessed
    reasoning: str           # 1–2 sentences
    new_correspondent: bool  # true if not in referential
```

**Why tool use and not JSON mode or free-text parsing.**
- Tool use enforces the schema at the API level; responses that don't match are rejected by the provider before reaching the code.
- It works identically on Anthropic and OpenAI with minor shape differences, enabling the multi-provider abstraction.
- Free-text + regex parsing was rejected: fragile, hard to version, hard to test.

**Why an open correspondent list.**
The `correspondents` list in `config.yaml` is a hint, not a constraint. The LLM can return a correspondent not in the list, in which case `new_correspondent: true` is set in the journal. This supports long-tail correspondents (doctors, small businesses, individuals) without requiring the user to pre-enroll every possible issuer.

**Alternatives considered.**
- Fine-tuned small model (e.g. DistilBERT on document classification): rejected. Requires a labeled dataset of thousands of documents, which is the problem the project is trying to avoid.
- Classification-only API (no free-form reasoning): rejected. Reasoning output is valuable for debugging low-confidence cases.
- Zero-shot embedding similarity against a reference set: considered as a complement for high-volume ingestion, not as primary. See §14.

**Status.** Implemented.

---

## 7. Naming convention and collisions

**Decision.** Files are named by joining non-empty segments with underscores:

```
{YYYY-MM}_{TypeLabel}_{Correspondent}_{title-slug}.pdf
```

Segments that are missing or unknown are **omitted entirely** — no placeholder tokens like `nodate` or `unknown`. The joining rule is: `"_".join([s for s in [date, type_label, correspondent, title_slug] if s])`.

**Segment rules.**
- **Date** (`YYYY-MM`): present if the LLM extracted a valid document date, omitted otherwise.
- **Type label**: always present. Falls back to the `Autre` (FR) or `Other` (EN) label if the LLM returns `other` as the document type.
- **Correspondent**: present if the LLM identified an issuer. Omitted if the returned value is `Unknown`, empty, or null.
- **Title slug**: always present. The LLM is instructed to always return a descriptive title, even under low confidence.

**Slugification.**
- Lowercase
- Accents removed via NFKD normalization
- Non-alphanumeric characters replaced with hyphens
- Consecutive hyphens collapsed to one
- Leading and trailing hyphens trimmed
- Truncated to 40 characters for `title-slug`

**Examples.**

| Case | Filename |
|---|---|
| All fields present | `2025-10_Facture_EDF_releve-mensuel-octobre.pdf` |
| No date | `Facture_EDF_releve-mensuel-octobre.pdf` |
| Unknown correspondent | `2025-10_Facture_releve-mensuel-octobre.pdf` |
| No date, unknown correspondent | `Facture_releve-mensuel-octobre.pdf` |
| Fallback type | `2025-10_Autre_carte-fidelite-boulangerie.pdf` |

**Collision handling.** If a target path already exists, a numeric suffix is appended before the extension: `_2`, `_3`, etc. No overwrites, no merges, ever.

**Target folder.** `library/{TypeLabel}/`, where `TypeLabel` is resolved from the `fr` or `en` column of the referential based on `config.language`.

**Rationale.**
- Omitting rather than placeholder-substituting keeps filenames shorter and removes visual noise on documents where metadata is genuinely incomplete.
- Always preserving type and title guarantees every file is at least identifiable — the two fields that matter most for retrieval.
- Placeholders like `nodate` or `unknown` were rejected because they appeared in ~15% of filenames during early testing and added no information: a file without a date prefix is self-evidently undated.

**Alternatives considered.**
- Hash-based filenames: rejected. Unreadable, requires always going through an index.
- Original filename preservation: rejected. Original filenames from scanner apps and downloads are unreliable (`scan_001.pdf`, `document (3).pdf`).
- Date-only structure (`YYYY/MM/<file>`): rejected. Document type is a more useful primary axis for retrieval than date.
- Placeholder tokens (`nodate`, `unknown`): rejected (see rationale above).

**Status.** Implemented.

---

## 8. Idempotency and state

**Problem.** Running `make scan` twice on the same inbox must not produce duplicates or lost files.

**Decision.** Every file is identified by SHA-256 of its bytes, computed before any processing. The journal (`data/journal.csv`) stores every hash that has been successfully processed. On each scan, hashes are loaded into an in-memory set; new files matching an existing hash are skipped with an info log.

The hash is computed on the **source** file, not the OCR'd intermediate. This means that a document dropped a second time (even as a re-scan with different metadata but the same bytes) is correctly skipped.

**Why CSV and not SQLite as the primary journal.**
- Human-readable, editable with any tool, no schema migrations.
- Append-only semantics are native to the format.
- Loss of the file can be reconstructed by walking `library/` and re-reading metadata (though this is slow and lossy for confidence scores).
- SQLite is added as a secondary, rebuildable index (see §11), not as the source of truth.

**Alternatives considered.**
- Content-defined chunking hash (BLAKE3 on normalized content): rejected as over-engineered for this volume.
- Filename-based deduplication: rejected, filenames are unreliable.
- Database with a uniqueness constraint: rejected, same reasons as CSV above.

**Status.** Implemented.

---

## 9. Concurrency and safety

**Problem.** Two concurrent `make scan` runs can race on the same inbox: both see a file, both try to OCR it, both try to delete it, one wins and the other fails with `FileNotFoundError`. Observed during early testing when a long-running scan was accidentally launched twice.

**Decision.** A `fcntl.flock` lock on `data/.filethat.lock` is acquired at the start of the `scan` subcommand and released in a `try/finally`. A second concurrent scan attempt gets `BlockingIOError`, prints a clear message ("Another scan is running, exiting"), and exits with code 1 — without touching any files.

Additionally, the pipeline checks `path.exists()` before each per-file operation and logs a warning rather than crashing if a file disappears between listing and processing.

**Why `fcntl.flock` and not a marker file.**
- A marker file survives a crash and requires manual cleanup.
- `flock` is released automatically by the OS when the process exits, including on hard kill.

**Alternatives considered.**
- Process-level mutex via Redis: rejected, requires adding Redis for one lock.
- Per-file locks: rejected, the sequential nature of the pipeline makes a global lock simpler and equivalent.

**Status.** Implemented.

---

## 10. Human-in-the-loop review

**Problem.** The LLM self-reports a confidence score. Documents with `confidence < 0.7` are disproportionately mis-classified (measured on the eval dataset — see §12). Trusting them silently erodes library quality over time.

**Decision.** Introduce a review gate. Documents with confidence below a configurable threshold (default 0.7) are routed to `data/review/` instead of `library/`, each accompanied by a `<filename>.suggestion.json` containing the LLM's full output. The web UI gains a "Review" tab listing these items, with a single-click "Accept" button that moves the file to `library/` using the suggestion, and an "Edit" option to override any field before accepting.

Rejected or incorrect classifications are captured as signal for future prompt improvements (logged separately to `data/review_feedback.jsonl`).

**Why a manual gate and not auto-retry.**
- Low confidence usually reflects genuine ambiguity (an unusual document type, poor OCR quality, or a correspondent the model has never seen). Re-querying with the same input produces the same uncertainty.
- Human judgment on the edge cases is the only reliable signal; automating it would move errors from visible to invisible.

**Alternatives considered.**
- Auto-classify then flag for post-hoc review: rejected. Once a file is in `library/`, users rarely re-check it.
- Run two LLM calls and require agreement: rejected as doubling cost for a problem that has a better solution (human review).

**Status.** Implemented.

---

## 11. Indexing strategy

**Problem.** As the library grows past a few hundred documents, questions like "show me all EDF invoices from 2024" or "find the document mentioning 'carte grise'" become slow to answer by filesystem traversal.

**Decision.** Alongside `journal.csv`, maintain a SQLite database (`data/filethat.db`) with a `documents` table mirroring the journal columns plus an FTS5 virtual table on OCR text. The database is **rebuildable from the filesystem** — it is an index, not a source of truth.

The web UI's search uses SQLite; the rest of the pipeline does not depend on it. A `make reindex` command rebuilds the database from scratch.

**Why SQLite specifically.**
- Zero-config, file-based, no server.
- FTS5 is built-in and excellent for document search.
- Standard Python stdlib (`sqlite3`), no added dependency.

**Alternatives considered.**
- Elasticsearch / Meilisearch: rejected. Excellent tools, wrong scale. A separate container for an index of <10k documents is waste.
- DuckDB: considered. SQLite chosen for FTS5 maturity and ubiquity; DuckDB is better for analytical queries, which aren't the primary use case here.
- No index, rely on `ripgrep` over the library: acceptable fallback for power users, not acceptable for a web UI.

**Status.** To implement. Tier 1 roadmap.

---

## 12. Quality measurement

**Problem.** Without measurement, claims about pipeline quality are subjective. A recruiter reading this project needs numbers, and the author needs an objective signal when iterating on prompts.

**Decision.** Build and maintain an evaluation dataset in `tests/eval/` containing:
- 20–30 anonymized real documents spanning all document types in the referential
- A `golden.json` file with the expected classification for each

A `make eval` command runs the pipeline on the dataset and produces a report:

```
Document type accuracy: 27/30 (90.0%)
Correspondent accuracy: 25/30 (83.3%)
Date extraction accuracy: 28/30 (93.3%)
Confidence calibration (ECE): 0.08

Confusion matrix on document_type:
                 predicted
                 Invoice  Admin  Banking  [...]
actual Invoice     12       0       0
       Admin        0       5       1
       Banking      0       0       6
       [...]

Average cost per document: $0.003
Average processing time: 8.4s (OCR: 5.2s, LLM: 2.1s, other: 1.1s)
```

The eval runs both Anthropic and OpenAI in separate columns to support provider comparison.

**Why a small hand-curated dataset and not a large synthetic one.**
- 30 well-chosen documents cover the distribution; thousands of synthetic documents don't reveal real-world failure modes.
- Maintainable by one person; anything larger would require tooling the project is trying to avoid.

**Alternatives considered.**
- Automated eval via LLM-as-judge: rejected as circular when the pipeline itself is LLM-based.
- Crowdsourced ground truth: rejected, privacy constraints on real administrative documents.

**Status.** To implement. Tier 1 roadmap.

---

## 13. Cost optimization

**Problem.** At default settings with Claude Sonnet, each document costs roughly $0.003–0.005 in LLM tokens (mostly input: system prompt + referential + OCR text). Processing an archive of 1000 documents is $3–5. Not prohibitive, but easily reducible.

**Decision.** Two optimizations, both opt-in via config.

**Prompt caching (Anthropic).** The system prompt — including instructions and the full referential — is identical across all calls. Marking it with `cache_control: {"type": "ephemeral"}` enables Anthropic's prompt caching. On the reference workload (173 documents in one session), this cuts input token cost by ~75% for cached tokens.

**Batch API (Anthropic Message Batches).** For bulk ingestion (>50 documents at once), the Message Batches API applies a 50% discount in exchange for asynchronous completion within 24 hours. A `make scan-batch` command submits all OCR'd inbox files as a single batch, polls for completion, and finalizes placement when results arrive.

**Alternatives considered.**
- Switch to a smaller model (Haiku): viable but degrades classification accuracy below the measured threshold of acceptable quality on the eval dataset.
- Local LLM (Llama 3, Mistral) via Ollama: rejected for current scope. Adds significant container complexity and GPU dependency for a cost already under $5 per archive.
- Output token reduction via shorter schema: marginal savings (output is <200 tokens), not worth the readability loss.

**Status.** Prompt caching implemented; Batch API to implement.

---

## 14. Extensibility

**Problem.** Users may want to extract document-specific fields beyond classification — invoice amounts, payslip periods, tax years — without a complete pipeline rewrite.

**Decision.** The `classify` stage is extended with an optional `extract` sub-schema keyed by `document_type`. For example:

```yaml
extraction:
  invoice:
    - amount_ttc: number
    - due_date: date
    - invoice_number: string
  payslip:
    - period: date
    - net_taxable: number
```

The LLM tool schema is dynamically augmented with the extraction fields for the detected type. Extracted values are stored as JSON in a new `extracted` column in the journal and indexed separately in SQLite.

This is deferred to post-MVP because the core pipeline works without it and adding extraction multiplies the edge cases in the prompt.

**Alternatives considered.**
- Separate extraction pass after classification: rejected, doubles the LLM calls and cost.
- Hardcoded per-type extractors in Python: rejected, requires code changes for every new type.

**Status.** Roadmap.

---

## 15. Deduplication

**Problem.** Current deduplication is exact-match SHA-256. Two scans of the same physical document produce different bytes (different compression, different OCR pass) and are classified as distinct documents. The library accumulates near-duplicates.

**Decision.** Add a secondary deduplication layer after classification. Candidate duplicates are flagged (not auto-merged) when **two** of the following match:
- First 500 OCR characters (normalized whitespace)
- Classified correspondent AND date
- Perceptual hash of the first rendered page

Flagged candidates are listed in the web UI's "Duplicates" view for manual resolution.

**Why not automatic merging.**
Auto-merging based on fuzzy match destroys data on false positives. Flag-and-review keeps the user in control.

**Alternatives considered.**
- TLSH or MinHash on full OCR text: more accurate but requires a vector index; deferred.
- Image-only pHash: insufficient, can't distinguish two similar invoice templates with different data.

**Status.** Roadmap.

---

## 16. Retention policy

**Problem.** Some document types have legal retention requirements (French tax documents: 3 years for income tax, 10 years for property; utility bills: 5 years; payslips: indefinite). Users may want old documents auto-archived without deletion.

**Decision.** Add a `retention` section in `config.yaml` mapping document types to durations:

```yaml
retention:
  invoice: 5y
  tax: 10y
  payslip: forever
  admin: 3y
```

A `make retention` command walks the library, identifies documents older than their type's retention, and moves them to `data/archive/<YYYY-MM-DD>_retention/<Type>/<file>`. The archive structure mirrors the library.

No automatic deletion. Ever.

**Status.** Roadmap.

---

## 17. Observability

**Decision.** Structured JSON logs to stdout (captured by Docker) and to `data/filethat.log`. Every log entry carries at minimum: `timestamp`, `level`, `module`, `message`. Per-file operations additionally carry `id` (short UUID) and `file` (basename).

**Why not Prometheus / Sentry / OpenTelemetry.**
Out of scope for a personal tool. Logs are sufficient for debugging; metrics are computed ad-hoc from `journal.csv` by the `make stats` command.

**Status.** Implemented.

---

## 18. Security and privacy

**Data handling.**
- Documents never leave the local filesystem except for the text payload sent to the LLM provider.
- The text payload is truncated to the first 5 pages / 15000 characters; full OCR text is not transmitted.
- API keys are read from environment variables only, never from `config.yaml`. `.env` is git-ignored.

**Implications of LLM use.**
Users must accept that document text (not images) is sent to a third-party API. This is stated explicitly in the README. For users for whom this is unacceptable, the provider abstraction makes it straightforward to plug in a local model (Ollama, llama.cpp) — not implemented, but the interface supports it.

**Status.** Implemented; local-model provider is roadmap.

---

## Document status

- **Last updated:** 2026-04-24
- **Reference implementation:** commit `HEAD` of `main`
- **Maintainer:** [@mogassama](https://github.com/mogassama)
