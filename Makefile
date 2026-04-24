.PHONY: help install scan ui ui-stop ui-logs stats archive delete-archive clean-failed reset reindex shell test logs

help:
	@echo "filethat — document classification pipeline"
	@echo ""
	@echo "  make install          Build Docker image"
	@echo "  make scan             Process files in data/inbox/"
	@echo "  make ui               Launch web UI (detached) on http://localhost:8000"
	@echo "  make ui-stop          Stop the UI service"
	@echo "  make ui-logs          Tail logs from the UI service"
	@echo "  make stats            Show journal summary"
	@echo "  make archive          Snapshot data/library/ into data/archive/<timestamp>/"
	@echo "  make delete-archive   Delete all archives (confirms)"
	@echo "  make clean-failed     Delete all failed entries (confirms)"
	@echo "  make reset            WIPE everything (double confirms)"
	@echo "  make reindex          Rebuild full-text search index from journal.csv"
	@echo "  make shell            Open shell inside container"
	@echo "  make test             Run tests"
	@echo "  make logs             Show last 100 log lines from latest run"

install:
	docker compose build

scan:
	docker compose run --rm filethat scan

ui:
	docker compose --profile ui up -d filethat-ui
	@echo "UI running at http://localhost:8000"

ui-stop:
	docker compose --profile ui down

ui-logs:
	docker compose --profile ui logs -f filethat-ui

stats:
	docker compose run --rm filethat stats

archive:
	docker compose run --rm filethat archive

delete-archive:
	docker compose run --rm filethat delete-archive

clean-failed:
	docker compose run --rm filethat clean-failed

reset:
	docker compose run --rm filethat reset

reindex:
	docker compose run --rm filethat reindex

shell:
	docker compose run --rm --entrypoint /bin/bash filethat

test:
	docker build --target test-builder -t filethat-test . && \
	docker run --rm filethat-test /app/.venv/bin/pytest tests/ -v

logs:
	@tail -n 100 data/filethat.log 2>/dev/null || echo "No logs yet."
