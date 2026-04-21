.PHONY: help up down logs build init-referential reprocess-failed reprocess-review \
        export export-all archive mark-exported archive-and-mark trash-archives \
        stats shell backup clean lint format test

help:
	@echo "Available targets:"
	@echo ""
	@echo "  Stack & maintenance:"
	@echo "    up                   Start the stack"
	@echo "    down                 Stop the stack (volumes preserved)"
	@echo "    clean                Stop the stack and delete all volumes (DESTRUCTIVE)"
	@echo "    build                Rebuild the classifier image"
	@echo "    logs                 Tail classifier logs"
	@echo "    shell                Open a shell in the classifier container"
	@echo "    init-referential     Create correspondents/types/tags in Paperless (idempotent)"
	@echo "    backup               Native Paperless-ngx export of docs + metadata"
	@echo "    stats                Summary from JSONL log (cost, confidence, volumes)"
	@echo ""
	@echo "  Reprocessing:"
	@echo "    reprocess-failed     Reprocess documents tagged ai:failed"
	@echo "    reprocess-review     Reprocess documents tagged ai:to-check"
	@echo ""
	@echo "  Export workflow:"
	@echo "    export               Export ai:processed documents to data/export/"
	@echo "    export-all           Same + includes ai:to-check documents"
	@echo "    mark-exported        Tag exported documents as exported"
	@echo "    archive              Move exported documents to archive/<timestamp>/"
	@echo "    archive-and-mark     Mark then archive in one command"
	@echo "    trash-archives       Delete all archives (with confirmation)"
	@echo ""
	@echo "  Quality:"
	@echo "    lint                 Run ruff linter"
	@echo "    format               Run ruff formatter"
	@echo "    test                 Run pytest"

up:
	docker compose up -d
	@echo "Stack started on http://localhost:8000"

down:
	docker compose down
	@echo "Stack stopped (volumes preserved)"

clean:
	@echo "WARNING: This will delete ALL Paperless data."
	@read -p "Confirm by typing 'yes': " confirm && [ "$$confirm" = "yes" ] || (echo "Cancelled." && exit 1)
	docker compose down -v
	rm -rf ./data
	@echo "Stack and data deleted"

build:
	docker compose build classifier

logs:
	docker compose logs -f classifier

init-referential:
	docker compose exec classifier python scripts/init_referential.py

reprocess-failed:
	docker compose exec classifier python -m filethat.cli reprocess --tag ai:failed

reprocess-review:
	docker compose exec classifier python -m filethat.cli reprocess --tag ai:to-check

export:
	docker compose exec classifier python scripts/export.py

export-all:
	docker compose exec classifier python scripts/export.py --include-review

mark-exported:
	docker compose exec classifier python scripts/mark_exported.py

archive:
	docker compose exec classifier python scripts/archive.py

archive-and-mark:
	@echo "Step 1/2: marking exported documents..."
	docker compose exec classifier python scripts/mark_exported.py
	@echo ""
	@echo "Step 2/2: archiving..."
	docker compose exec classifier python scripts/archive.py

trash-archives:
	@echo "WARNING: This will permanently delete all archives."
	@if [ -d "./data/export/archive" ]; then \
		count=$$(find ./data/export/archive -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' '); \
		size=$$(du -sh ./data/export/archive 2>/dev/null | cut -f1); \
		echo "   Archives found: $$count ($$size)"; \
	else \
		echo "   No archives found, nothing to delete."; \
		exit 0; \
	fi
	@read -p "Confirm by typing 'yes': " confirm && [ "$$confirm" = "yes" ] || (echo "Cancelled." && exit 1)
	rm -rf ./data/export/archive
	@echo "Archives deleted"

stats:
	docker compose exec classifier python -m filethat.cli stats

shell:
	docker compose exec classifier bash

backup:
	docker compose exec webserver document_exporter /usr/src/paperless/export/ --no-thumbnails
	@echo "Backup saved to ./data/export/"

lint:
	docker compose exec classifier uv run ruff check src/

format:
	docker compose exec classifier uv run ruff format src/

test:
	docker compose exec classifier uv run pytest tests/ -v
