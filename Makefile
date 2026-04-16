.PHONY: help up down logs build init-referential reprocess-failed reprocess-review stats shell backup clean

help:
	@echo "Cibles disponibles :"
	@echo "  up                 Démarre le stack"
	@echo "  down               Arrête le stack (volumes préservés)"
	@echo "  clean              Arrête le stack et supprime les volumes (DESTRUCTIF)"
	@echo "  build              Rebuild l'image classifier"
	@echo "  logs               Tail des logs du classifier"
	@echo "  init-referential   Crée correspondants/types/tags dans Paperless (one-shot)"
	@echo "  reprocess-failed   Relance les docs taggés ai:failed"
	@echo "  reprocess-review   Relance les docs taggés ai:a-verifier"
	@echo "  stats              Résumé depuis le JSONL (coût, confidence, volumes)"
	@echo "  shell              Ouvre un shell dans le container classifier"
	@echo "  backup             Export natif Paperless-ngx des docs+métadonnées"

up:
	docker compose up -d
	@echo "✅ Stack démarré sur http://localhost:8000"

down:
	docker compose down
	@echo "🛑 Stack arrêté (volumes préservés)"

clean:
	@echo "⚠️  Cette action supprime TOUTES les données Paperless."
	@read -p "Confirmer avec 'yes' : " confirm && [ "$$confirm" = "yes" ] || (echo "Annulé." && exit 1)
	docker compose down -v
	rm -rf ./data
	@echo "🧹 Stack et données supprimés"

build:
	docker compose build classifier

logs:
	docker compose logs -f classifier

init-referential:
	docker compose exec classifier python scripts/init_referential.py

reprocess-failed:
	docker compose exec classifier python -m pipeline.cli reprocess --tag ai:failed

reprocess-review:
	docker compose exec classifier python -m pipeline.cli reprocess --tag ai:a-verifier

stats:
	docker compose exec classifier python -m pipeline.cli stats

shell:
	docker compose exec classifier bash

backup:
	docker compose exec webserver document_exporter /usr/src/paperless/export/ --no-thumbnails
	@echo "📦 Backup dans ./data/export/"
