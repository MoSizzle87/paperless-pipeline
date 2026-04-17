.PHONY: help up down logs build init-referential reprocess-failed reprocess-review \
        export-digiposte export-digiposte-all archive-digiposte mark-uploaded \
        archive-and-mark trash-archives stats shell backup clean

help:
	@echo "Cibles disponibles :"
	@echo ""
	@echo "  Stack & maintenance :"
	@echo "    up                     Démarre le stack"
	@echo "    down                   Arrête le stack (volumes préservés)"
	@echo "    clean                  Arrête le stack et supprime les volumes (DESTRUCTIF)"
	@echo "    build                  Rebuild l'image classifier"
	@echo "    logs                   Tail des logs du classifier"
	@echo "    shell                  Ouvre un shell dans le container classifier"
	@echo "    init-referential       Crée correspondants/types/tags dans Paperless (one-shot)"
	@echo "    backup                 Export natif Paperless-ngx des docs+métadonnées"
	@echo "    stats                  Résumé depuis le JSONL (coût, confidence, volumes)"
	@echo ""
	@echo "  Reprocessing :"
	@echo "    reprocess-failed       Relance les docs taggés ai:failed"
	@echo "    reprocess-review       Relance les docs taggés ai:a-verifier"
	@echo ""
	@echo "  Export Digiposte :"
	@echo "    export-digiposte       Exporte les docs ai:processed vers data/export/digiposte/"
	@echo "    export-digiposte-all   Idem + inclut les docs ai:a-verifier"
	@echo "    mark-uploaded          Tagge digiposte:uploaded les docs présents dans digiposte/"
	@echo "    archive-digiposte      Déplace digiposte/* vers digiposte/archive/<timestamp>/"
	@echo "    archive-and-mark       Tagge puis archive en une seule commande"
	@echo "    trash-archives         Supprime toutes les archives (avec confirmation)"

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

export-digiposte:
	docker compose exec classifier python scripts/export_digiposte.py

export-digiposte-all:
	docker compose exec classifier python scripts/export_digiposte.py --include-review

mark-uploaded:
	docker compose exec classifier python scripts/mark_uploaded.py

archive-digiposte:
	docker compose exec classifier python scripts/archive_digiposte.py

archive-and-mark:
	@echo "🏷️  Étape 1/2 : tagging digiposte:uploaded..."
	docker compose exec classifier python scripts/mark_uploaded.py
	@echo ""
	@echo "📦 Étape 2/2 : archivage..."
	docker compose exec classifier python scripts/archive_digiposte.py

trash-archives:
	@echo "⚠️  Cette action supprime DÉFINITIVEMENT toutes les archives Digiposte."
	@if [ -d "./data/export/digiposte/archive" ]; then \
		count=$$(find ./data/export/digiposte/archive -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' '); \
		size=$$(du -sh ./data/export/digiposte/archive 2>/dev/null | cut -f1); \
		echo "   Archives présentes : $$count ($$size)"; \
	else \
		echo "   Aucune archive présente, rien à supprimer."; \
		exit 0; \
	fi
	@read -p "Confirmer avec 'yes' : " confirm && [ "$$confirm" = "yes" ] || (echo "Annulé." && exit 1)
	rm -rf ./data/export/digiposte/archive
	@echo "🗑️  Archives supprimées"

stats:
	docker compose exec classifier python -m pipeline.cli stats

shell:
	docker compose exec classifier bash

backup:
	docker compose exec webserver document_exporter /usr/src/paperless/export/ --no-thumbnails
	@echo "📦 Backup dans ./data/export/"
