# Contributing

Thank you for your interest in filethat. This document explains how to set up
a development environment, the conventions we follow, and how to extend the
project.

## Development setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for dependency management
- Docker + Colima (or any Docker-compatible runtime) for integration testing
- A Paperless-ngx instance (provided by `docker compose up`)

### Local setup

```bash
git clone https://github.com/<your-fork>/filethat.git
cd filethat/classifier
uv sync --dev
```

### Running the stack locally

```bash
cp .env.example .env
# Fill in PAPERLESS_API_TOKEN and LLM_API_KEY in .env
make up
make init-referential
```

### Running tests

```bash
cd classifier
uv run pytest tests/ -v
```

### Linting and formatting

```bash
cd classifier
uv run ruff check src/        # lint
uv run ruff check src/ --fix  # auto-fix
uv run ruff format src/       # format
uv run mypy src/filethat/     # type check
```

Or via Make (requires the stack to be running):

```bash
make lint
make format
make test
```

## Code conventions

### Python style

- Type annotations on all public functions and methods
- Docstrings on all public classes and non-trivial functions
- English only: variable names, comments, docstrings, log messages
- Line length: 100 characters (enforced by ruff)
- `except Exception` is allowed only with `log.exception()` to preserve the
  full traceback — never silently swallow errors

### Naming

- Modules: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Functions and variables: `snake_case`

### Commits

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(llm): add Mistral provider implementation
fix(referential): handle empty alias list in canonical YAML
docs(readme): update quick start instructions
test(normalizer): add edge case for empty string input
```

## Pull request process

1. Fork the repository and create a branch from `main`
2. Make your changes with tests where applicable
3. Run `ruff check`, `ruff format --check` and `pytest` — all must pass
4. Open a PR against `main` with a clear description of what changed and why
5. Link any related issues

PRs that introduce new features without tests will not be merged.

## Adding a new LLM provider

1. Create `classifier/src/filethat/llm/<provider>_client.py`
2. Implement a class that satisfies the `LLMClient` Protocol:
```python
   class MyProviderClient:
       def classify(self, ocr_text: str) -> LLMResult:
           ...
```
3. Add pricing constants in the client file (USD per million tokens)
4. Add a case to `llm/factory.py`:
```python
   case "myprovider":
       return MyProviderClient(api_key=api_key, model=model, ...)
```
5. Update `.env.example` with the new `LLM_PROVIDER` value and a link to
   where users can find their API key
6. Add a brief entry in `ARCHITECTURE.md` under "Extension points"

## Adding a new language preset

A preset is a directory under `config/` containing three YAML files that define
the document types, correspondents and tags for a specific country or context.

### Step 1 — Create the directory

```bash
mkdir config/<country>-admin/
```

### Step 2 — Create the YAML files

Copy `config/fr-admin/` as a starting point and adapt:

**`document_types.yaml`** — add or rename types relevant to your country.
Keep the `id` values stable (they are used internally by the LLM):

```yaml
- id: "invoice"
  labels:
    fr: "Facture"
    en: "Invoice"
    de: "Rechnung"
  priority: 18
```

**`correspondents.yaml`** — add national organisations for your country:

```yaml
- canonical: "HMRC"
  aliases: ["Her Majesty's Revenue and Customs", "HM Revenue & Customs"]
  category: "admin"
```

**`tags.yaml`** — keep the system tags unchanged, adapt business tags:

```yaml
system:
  - id: "ai:processed"
    color: "#2ecc71"
  - id: "ai:to-check"
    color: "#f39c12"
  - id: "ai:failed"
    color: "#e74c3c"
  - id: "workflow:exported"
    color: "#3498db"
business:
  - id: "tax"
    labels:
      en: "tax"
    color: "#c0392b"
```

### Step 3 — Add a system prompt (optional)

If you want the LLM to reason in your language, create:

```
classifier/src/filethat/prompts/system_<lang>.md
```

The prompt will be loaded automatically when `PROMPT_LANGUAGE=<lang>` is set.
If no prompt exists for the requested language, the English prompt is used as
fallback.

### Step 4 — Configure

In `.env`:

```bash
REFERENTIALS_DIR=/app/config/<country>-admin
LANGUAGE=<lang>
```

### Step 5 — Submit

Open a PR with your preset. Include a brief description of the country/context
and any notable decisions (e.g. why certain document types were added or renamed).

## Project structure

```
filethat/
├── classifier/
│   ├── src/filethat/     Python package
│   ├── scripts/          Operational scripts (export, archive, mark)
│   └── tests/            Unit tests
├── config/
│   └── fr-admin/         French administrative preset
├── examples/
│   └── export-workflow/  Export workflow documentation and example
├── .github/workflows/    CI configuration
├── ARCHITECTURE.md       Design decisions
├── CONTRIBUTING.md       This file
└── LICENSE               MIT
```

## Reporting issues

Open a GitHub issue with:

- A clear description of the problem or feature request
- Steps to reproduce (for bugs)
- Your environment: OS, Python version, Docker version, LLM provider
- Relevant logs from `docker compose logs classifier`

## Questions

For questions that are not bugs or feature requests, open a GitHub Discussion.
