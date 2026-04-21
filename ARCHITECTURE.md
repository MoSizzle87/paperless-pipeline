# Architecture

## Overview

filethat is a document classification pipeline that sits alongside Paperless-ngx.
It polls for unclassified documents, sends their OCR text to an LLM, and writes
structured metadata back to Paperless via its REST API.

```
┌─────────────────┐     OCR text      ┌─────────────────┐     tool use / fn call
│  Paperless-ngx  │ ────────────────► │    filethat     │ ──────────────────────►  LLM
│  (webserver)    │                   │   (classifier)  │
│                 │ ◄──────────────── │                 │ ◄──────────────────────
└─────────────────┘   PATCH metadata  └─────────────────┘     structured output
```

## Component map

```
classifier/src/filethat/
├── cli.py               Entry point — wires all components together
├── config.py            Settings loaded from environment variables
├── poller.py            Polling loop — fetches unclassified docs every N seconds
├── classifier.py        Per-document orchestrator
├── llm/
│   ├── base.py          LLMClient Protocol + shared types (LLMResult)
│   ├── anthropic_client.py  Claude implementation (tool use + prompt caching)
│   ├── openai_client.py     GPT implementation (function calling)
│   └── factory.py       build_llm_client(provider, model, api_key)
├── prompt.py            Tool schema + dynamic prompt loader
├── prompts/
│   ├── system_fr.md     French system prompt
│   └── system_en.md     English system prompt
├── referential.py       Entity resolution (Class A / Class B)
├── normalizer.py        Slugification + Levenshtein fuzzy matching
├── paperless_client.py  Paperless-ngx REST API wrapper
├── schemas.py           Pydantic models
├── logging_setup.py     Console + rotating JSONL audit log
└── config/
config/
└── fr-admin/            French administrative document preset
    ├── document_types.yaml
    ├── correspondents.yaml
    └── tags.yaml
```

## Key design decisions

### Why tool use / function calling instead of plain text output?

Structured output via tool use (Anthropic) or function calling (OpenAI) enforces
a strict JSON schema at the API level. The LLM cannot return malformed output —
the API rejects it before it reaches our code. This eliminates an entire class of
parsing errors and removes the need for prompt engineering tricks to produce
consistent JSON.

### Why prompt caching?

The system prompt is large (~3KB) and identical across every document in a
session. Anthropic's prompt caching writes it to a cache on the first call and
reads it on subsequent ones at 10x lower cost. On a batch of 300 documents,
this reduces input token costs by roughly 90%.

### Why a hybrid Class A / Class B correspondent resolution?

Two failure modes exist when matching correspondent names from OCR text:

- OCR errors distort known entity names ("E0F" instead of "EDF")
- New entities appear that were never anticipated

Class A (canonical whitelist) handles the first case with exact slug matching
plus alias expansion. Class B (Levenshtein auto-creation) handles the second
case by creating new Paperless correspondents on the fly, with a similarity
guard to avoid near-duplicate entries.

### Why external YAML referentials instead of hardcoded values?

Document types, correspondents and tags are domain-specific and change over time.
Externalising them to YAML means users can adapt filethat to their country,
language or document set without touching Python code. The `config/fr-admin/`
preset ships with the project; users can create `config/en-admin/` or any other
preset by following the same structure.

### Why a LLMClient Protocol abstraction?

Coupling the classifier directly to the Anthropic SDK would make it impossible
to switch providers without rewriting core logic. The Protocol defines a single
method (`classify(ocr_text) -> LLMResult`) that any provider must implement.
Adding a new provider (Ollama, Mistral, etc.) requires creating one new file
that satisfies this interface — nothing else changes.

### Why stable IDs in the tool schema instead of language-specific labels?

The LLM returns `"invoice"` rather than `"Facture"` or `"Invoice"`. This
decouples the classification output from the display language. The same
classification result can be rendered in French, English, or any future language
without reprocessing documents. IDs are stable across schema versions; labels
can change freely.

### Why i18n at two levels (prompt language vs export language)?

A French user processing French documents wants the LLM to reason in French
(`PROMPT_LANGUAGE=fr`) but may want export folder names in English
(`EXPORT_LANGUAGE=en`) for compatibility with an English-language storage
service. Separating the two gives precise control without forcing a single
language choice.

## Data flow

```
Paperless-ngx
    │
    │  GET /documents/?tags__id__none=<processed,review,failed>
    ▼
Poller (every 60s)
    │
    │  doc.content (OCR text)
    ▼
DocumentClassifier
    │
    ├─► LLMClient.classify(ocr_text)
    │       │
    │       │  system prompt (fr or en)
    │       │  CLASSIFY_TOOL schema (stable IDs)
    │       ▼
    │   Anthropic / OpenAI API
    │       │
    │       │  LLMClassification (title, correspondent, document_type ID, tags, confidence)
    │       ▼
    │   LLMResult
    │
    ├─► ReferentialManager.resolve_correspondent()   → Paperless correspondent ID
    ├─► ReferentialManager.resolve_document_type()   → Paperless document type ID
    ├─► ReferentialManager.resolve_tags()            → Paperless tag IDs
    │
    │  PATCH /documents/<id>/
    ▼
Paperless-ngx (document updated with structured metadata)
```

## Idempotency

All scripts (`export.py`, `archive.py`, `mark_exported.py`) and
`init_referential.py` are idempotent. Re-running them produces the same result
as running them once. Specifically:

- `init_referential.py` skips entities that already exist in Paperless
- `export.py` skips files that already exist at the destination path
- `mark_exported.py` skips documents already tagged `workflow:exported`
- `archive.py` always creates a new timestamped directory, so re-runs are safe

## Extension points

### Adding a new LLM provider

1. Create `classifier/src/filethat/llm/<provider>_client.py`
2. Implement the `classify(ocr_text: str) -> LLMResult` method
3. Add a case to `llm/factory.py`
4. Document pricing in the client file

See `CONTRIBUTING.md` for details.

### Adding a new language preset

1. Create `config/<language>-admin/` with the three YAML files
2. Set `REFERENTIALS_DIR` to point to the new directory
3. Add prompt files `filethat/prompts/system_<lang>.md` if needed

See `CONTRIBUTING.md` for details.
