from __future__ import annotations

import csv
import shutil
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from filethat.config import Config

LABELS = {
    "fr": {
        "title": "filethat — Documents",
        "total": "Total",
        "success": "Succès",
        "errors": "Erreurs",
        "low_confidence": "Faible confiance",
        "all": "Tous",
        "filter_success": "Succès",
        "filter_errors": "Erreurs",
        "filter_low": "Faible confiance",
        "col_id": "ID",
        "col_date": "Date traitée",
        "col_status": "Statut",
        "col_type": "Type",
        "col_correspondent": "Correspondant",
        "col_doc_date": "Date doc.",
        "col_title": "Titre",
        "col_confidence": "Confiance",
        "col_actions": "Actions",
        "btn_reprocess": "Retraiter",
        "no_documents": "Aucun document.",
    },
    "en": {
        "title": "filethat — Documents",
        "total": "Total",
        "success": "Success",
        "errors": "Errors",
        "low_confidence": "Low confidence",
        "all": "All",
        "filter_success": "Success",
        "filter_errors": "Errors",
        "filter_low": "Low confidence",
        "col_id": "ID",
        "col_date": "Processed",
        "col_status": "Status",
        "col_type": "Type",
        "col_correspondent": "Correspondent",
        "col_doc_date": "Doc date",
        "col_title": "Title",
        "col_confidence": "Confidence",
        "col_actions": "Actions",
        "btn_reprocess": "Reprocess",
        "no_documents": "No documents found.",
    },
}


def create_app(config: Config) -> FastAPI:
    app = FastAPI(title="filethat")

    templates_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))

    library_path = config.paths.library
    library_path.mkdir(parents=True, exist_ok=True)
    app.mount("/library", StaticFiles(directory=str(library_path)), name="library")

    def read_journal() -> list[dict]:
        path = config.paths.journal
        if not path.exists():
            return []
        with open(path, newline="") as f:
            return list(csv.DictReader(f))

    @app.get("/")
    async def index(request: Request, filter: Optional[str] = None):
        rows = read_journal()

        total = len(rows)
        success_count = sum(1 for r in rows if r["status"] == "success")
        error_count = sum(1 for r in rows if r["status"] == "error")
        low_conf_count = sum(
            1
            for r in rows
            if r["status"] == "success" and _conf(r) < 0.7
        )

        if filter == "success":
            rows = [r for r in rows if r["status"] == "success"]
        elif filter == "errors":
            rows = [r for r in rows if r["status"] == "error"]
        elif filter == "low_confidence":
            rows = [r for r in rows if r["status"] == "success" and _conf(r) < 0.7]

        rows = list(reversed(rows))

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "rows": rows,
                "total": total,
                "success_count": success_count,
                "error_count": error_count,
                "low_conf_count": low_conf_count,
                "current_filter": filter or "all",
                "labels": LABELS.get(config.language, LABELS["en"]),
            },
        )

    @app.get("/document/{doc_id}")
    async def serve_document(doc_id: str):
        rows = read_journal()
        row = next(
            (r for r in rows if r["id"] == doc_id and r["status"] == "success"), None
        )
        if not row:
            raise HTTPException(status_code=404, detail="Document not found")

        target_path = Path(row["target_path"])
        if not target_path.exists():
            raise HTTPException(status_code=404, detail="File not found on disk")

        return FileResponse(str(target_path), media_type="application/pdf")

    @app.post("/api/reprocess/{doc_id}")
    async def reprocess(doc_id: str):
        rows = read_journal()
        row = next(
            (r for r in rows if r["id"] == doc_id and r["status"] == "error"), None
        )
        if not row:
            raise HTTPException(status_code=404, detail="Error entry not found")

        source_filename = row["source_filename"]

        failed_dir = next(
            (d for d in config.paths.failed.iterdir() if d.name.startswith(doc_id)),
            None,
        )
        if not failed_dir:
            raise HTTPException(status_code=404, detail="Failed directory not found")

        source_file = failed_dir / source_filename
        if not source_file.exists():
            candidates = [
                f
                for f in failed_dir.iterdir()
                if f.name not in ("error.json",) and not f.name.endswith("_ocr.pdf")
            ]
            if not candidates:
                raise HTTPException(status_code=404, detail="Source file not found")
            source_file = candidates[0]

        dest = config.paths.inbox / source_file.name
        shutil.copy2(str(source_file), str(dest))

        return JSONResponse({"status": "ok", "moved_to_inbox": source_file.name})

    return app


def _conf(row: dict) -> float:
    try:
        return float(row.get("confidence") or 1.0)
    except (ValueError, TypeError):
        return 1.0
