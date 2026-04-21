# filethat

**Turn your document chaos into a structured archive — powered by LLMs.**

filethat is an open-source pipeline that classifies administrative documents
automatically. It connects to [Paperless-ngx](https://docs.paperless-ngx.com/),
reads OCR-extracted text, calls an LLM to extract structured metadata, and
writes it back — so every document gets a title, a date, a correspondent, and
a type, without you lifting a finger.

[![CI](https://github.com/mogassama/filethat/actions/workflows/ci.yml/badge.svg)](https://github.com/mogassama/filethat/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## Quick start

```bash
git clone https://github.com/mogassama/filethat.git
cd filethat
cp .env.example .env        # fill in your API keys
make up                     # start Paperless-ngx + classifier
make init-referential       # create document types, tags and correspondents
```

Open http://localhost:8000, drop a PDF into the consume folder, and watch it
get classified automatically.

---

## Features

- **Multi-LLM** — works with Anthropic Claude and OpenAI GPT out of the box.
  Add any provider by implementing a single interface.
- **Multilingual** — ships with French and English system prompts. Configure
  prompt language and export language independently.
- **Structured output** — uses tool use / function calling to enforce a strict
  JSON schema. No prompt hacks, no fragile parsing.
- **Prompt caching** — Anthropic prompt caching cuts input token costs by ~90%
  on large batches.
- **Hybrid entity resolution** — canonical whitelist (Class A) for known
  organisations + Levenshtein auto-creation (Class B) for new ones.
- **Idempotent** — every script and operation is safe to re-run.
- **Preset-based config** — swap country or domain by pointing to a different
  YAML directory. `config/fr-admin/` ships with the project.
- **Export workflow** — export classified documents to a structured folder
  hierarchy, mark them as exported, and archive them in one command.

---

## Architecture

```
┌─────────────────┐     OCR text      ┌─────────────────┐     tool use / fn call
│  Paperless-ngx  │ ────────────────► │    filethat     │ ──────────────────────►  LLM
│  (webserver)    │                   │   (classifier)  │
│                 │ ◄──────────────── │                 │ ◄──────────────────────
└─────────────────┘   PATCH metadata  └─────────────────┘     structured output
```

The classifier polls Paperless-ngx every 60 seconds, fetches documents that
have not been processed yet, and classifies them one by one. Each document gets:

- a **title** (`Invoice EDF January 2024`)
- a **date** (ISO format, extracted from the document)
- a **correspondent** (issuing organisation)
- a **document type** (one of 23 stable categories)
- **tags** (thematic labels)
- a **confidence score** (≥ 0.7 → `ai:processed`, < 0.7 → `ai:to-check`)

See [ARCHITECTURE.md](ARCHITECTURE.md) for a detailed explanation of every
design decision.

---

## Installation

### Prerequisites

- Docker + Colima (or any Docker-compatible runtime)
- An API key for Anthropic or OpenAI

### Setup

```bash
git clone https://github.com/mogassama/filethat.git
cd filethat
cp .env.example .env
```

Edit `.env` and fill in:

```bash
PAPERLESS_ADMIN_USER=admin
PAPERLESS_ADMIN_PASSWORD=<your password>
PAPERLESS_SECRET_KEY=<openssl rand -base64 48>
POSTGRES_PASSWORD=<openssl rand -base64 24>
PAPERLESS_API_TOKEN=<retrieved after first startup — see below>
LLM_PROVIDER=anthropic          # or: openai
LLM_MODEL=claude-sonnet-4-6     # or: gpt-4o
LLM_API_KEY=<your API key>
```

Start the stack:

```bash
make up
```

Retrieve your Paperless API token at http://localhost:8000 → user profile →
Auth Token → Generate or http://localhost:8000/admin/authtoken/tokenproxy/
— click your token entry to view or regenerate it. Add it to `.env`, then:

```bash
docker compose restart classifier
make init-referential
```

---

## Configuration

All configuration is done via environment variables. The full list is in
`.env.example`.

### LLM provider

```bash
LLM_PROVIDER=anthropic          # anthropic | openai
LLM_MODEL=claude-sonnet-4-6
LLM_API_KEY=sk-ant-...
```

### Language

```bash
LANGUAGE=fr                     # main language (default: fr)
PROMPT_LANGUAGE=fr              # override prompt language (default: LANGUAGE)
EXPORT_LANGUAGE=en              # override export folder names (default: LANGUAGE)
```

### Referentials

```bash
REFERENTIALS_DIR=/app/config/fr-admin   # path to YAML preset inside the container
```

To use a different preset, create `config/<your-preset>/` with the three YAML
files (`document_types.yaml`, `correspondents.yaml`, `tags.yaml`) and point
`REFERENTIALS_DIR` to it.

### Tuning

```bash
CONFIDENCE_THRESHOLD=0.7        # below this → ai:to-check
POLL_INTERVAL_SECONDS=60
LEVENSHTEIN_THRESHOLD=0.85      # fuzzy match sensitivity for correspondents
```

---

## Usage

### Daily workflow

```bash
make up                         # start the stack
# drop PDFs into data/consume/
# filethat classifies them automatically
make stats                      # view classification statistics
```

### Reprocessing

```bash
make reprocess-review           # reprocess documents tagged ai:to-check
make reprocess-failed           # reprocess documents tagged ai:failed
```

### Export workflow

```bash
make export                     # export ai:processed documents to data/export/
make export-all                 # same + include ai:to-check documents
make mark-exported              # tag exported documents as workflow:exported
make archive                    # move export to archive/<timestamp>/
make archive-and-mark           # mark + archive in one command
```

See [examples/export-workflow/README.md](examples/export-workflow/README.md)
for a complete walkthrough.

### All available commands

```bash
make help
```

---

## Presets

A preset is a directory under `config/` containing three YAML files that define
the document types, correspondents and tags for a specific country or context.

| Preset | Language | Status |
|---|---|---|
| `fr-admin` | French administrative documents | Included |
| `en-admin` | English administrative documents | Contributions welcome |
| `de-admin` | German administrative documents | Contributions welcome |

To create your own preset, see [CONTRIBUTING.md](CONTRIBUTING.md).

### Personal correspondents

Add your own correspondents (landlord, employer, local providers) without
modifying the shared preset:

```bash
cp config/fr-admin/correspondents.local.yaml.example \
   config/fr-admin/correspondents.local.yaml
# edit correspondents.local.yaml — it is gitignored
```

---

## Development

```bash
cd classifier
uv sync --dev
uv run pytest tests/ -v
uv run ruff check src/
uv run mypy src/filethat/
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

---

## License

MIT — see [LICENSE](LICENSE).
