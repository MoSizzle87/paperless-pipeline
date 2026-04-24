from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from filethat.classify import ClassificationResult
from filethat.config import Config
from filethat.journal import Journal, JournalEntry
from filethat.organize import organize

_SUFFIX = ".suggestion.json"


def _load_review_items(review_dir: Path) -> list[dict]:
    items = []
    if not review_dir.exists():
        return items
    for sfile in sorted(review_dir.glob(f"*.pdf{_SUFFIX}")):
        pdf_name = sfile.name[: -len(_SUFFIX)]
        pdf_path = review_dir / pdf_name
        if pdf_path.exists():
            try:
                data = json.loads(sfile.read_text())
                items.append({"pdf_name": pdf_name, "suggestion": data})
            except Exception:
                pass
    return items


def _log_feedback(feedback_path: Path, entry: dict) -> None:
    with open(feedback_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


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
        "search_placeholder": "Rechercher dans les documents…",
        "search_btn": "Rechercher",
        "search_clear": "Effacer",
        "search_hint": "Conseil : lancez make reindex pour activer la recherche plein-texte.",
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
        "search_placeholder": "Search documents…",
        "search_btn": "Search",
        "search_clear": "Clear",
        "search_hint": "Tip: run make reindex to enable full-text search.",
    },
}


def create_app(config: Config) -> FastAPI:
    app = FastAPI(title="filethat")

    templates_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))

    library_path = config.paths.library
    library_path.mkdir(parents=True, exist_ok=True)
    app.mount("/library", StaticFiles(directory=str(library_path)), name="library")

    review_dir = config.paths.review
    review_dir.mkdir(parents=True, exist_ok=True)
    feedback_path = config.paths.journal.parent / "review_feedback.jsonl"
    db_path = config.paths.journal.parent / "filethat.db"

    def read_journal() -> list[dict]:
        path = config.paths.journal
        if not path.exists():
            return []
        with open(path, newline="") as f:
            return list(csv.DictReader(f))

    def _make_journal() -> Journal:
        return Journal(config.paths.journal, db_path=db_path)

    @app.get("/")
    async def index(
        request: Request,
        filter: Optional[str] = None,
        q: Optional[str] = None,
        document_type: Optional[str] = None,
        correspondent: Optional[str] = None,
    ):
        labels = LABELS.get(config.language, LABELS["en"])

        if q or document_type or correspondent:
            # Full-text / metadata search via SQLite
            search_active = True
            db_available = db_path.exists()
            if db_available:
                from filethat.index import open_db, search as db_search

                with open_db(db_path) as conn:
                    rows = db_search(
                        conn,
                        q or "",
                        filters={
                            "document_type": document_type or "",
                            "correspondent": correspondent or "",
                        },
                    )
            else:
                # Graceful fallback: substring match on CSV data
                q_lower = (q or "").lower()
                all_rows = read_journal()
                rows = [
                    r
                    for r in all_rows
                    if q_lower in (
                        r.get("title", "")
                        + " "
                        + r.get("correspondent", "")
                        + " "
                        + r.get("source_filename", "")
                        + " "
                        + r.get("document_type", "")
                    ).lower()
                    and (not document_type or r.get("document_type") == document_type)
                    and (not correspondent or correspondent.lower() in r.get("correspondent", "").lower())
                ]
                rows = list(reversed(rows))

            all_rows_for_stats = read_journal()
            total = len(all_rows_for_stats)
            success_count = sum(1 for r in all_rows_for_stats if r["status"] == "success")
            error_count = sum(1 for r in all_rows_for_stats if r["status"] == "error")
            low_conf_count = sum(
                1 for r in all_rows_for_stats if r["status"] == "success" and _conf(r) < 0.7
            )

            return templates.TemplateResponse(
                request=request,
                name="index.html",
                context={
                    "rows": rows,
                    "total": total,
                    "success_count": success_count,
                    "error_count": error_count,
                    "low_conf_count": low_conf_count,
                    "current_filter": "all",
                    "labels": labels,
                    "q": q or "",
                    "search_active": True,
                    "db_available": db_path.exists(),
                },
            )

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
                "labels": labels,
                "q": "",
                "search_active": False,
                "db_available": db_path.exists(),
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

    @app.get("/review")
    async def review_page(request: Request):
        items = _load_review_items(review_dir)
        return templates.TemplateResponse(
            request=request,
            name="review.html",
            context={
                "items": items,
                "review_count": len(items),
                "labels": LABELS.get(config.language, LABELS["en"]),
            },
        )

    @app.get("/review/pdf/{filename:path}")
    async def serve_review_pdf(filename: str):
        pdf_path = review_dir / filename
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail="Review file not found")
        return FileResponse(str(pdf_path), media_type="application/pdf")

    @app.post("/api/review/accept/{filename:path}")
    async def review_accept(filename: str):
        sfile = review_dir / (filename + _SUFFIX)
        pdf_path = review_dir / filename
        if not sfile.exists() or not pdf_path.exists():
            raise HTTPException(status_code=404, detail="Review item not found")

        data = json.loads(sfile.read_text())
        result = ClassificationResult.model_validate(
            {k: data[k] for k in ClassificationResult.model_fields if k in data}
        )
        target = organize(pdf_path, result, config)
        sfile.unlink()

        journal = _make_journal()
        journal.append(
            JournalEntry(
                id=Journal.new_id(),
                hash_sha256=data.get("hash_sha256", ""),
                source_filename=data.get("source_filename", filename),
                source_size_bytes=int(data.get("source_size_bytes", 0)),
                processed_at=datetime.now(timezone.utc).isoformat(),
                status="success",
                document_type=result.document_type,
                correspondent=result.correspondent,
                document_date=result.document_date or "",
                title=result.title,
                target_path=str(target),
                llm_provider=data.get("llm_provider", ""),
                llm_model=data.get("llm_model", ""),
                confidence=result.confidence,
                language=result.language,
                new_correspondent=result.new_correspondent,
                ocr_skipped=bool(data.get("ocr_skipped", False)),
                processing_duration_seconds=float(data.get("processing_duration_seconds", 0)),
            )
        )
        _log_feedback(
            feedback_path,
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "id": data.get("id"),
                "source_filename": data.get("source_filename"),
                "original_suggestion": data,
                "user_action": "accept",
                "final_values": result.model_dump(),
            },
        )
        return JSONResponse({"status": "ok", "target": str(target)})

    @app.post("/api/review/edit/{filename:path}")
    async def review_edit(
        filename: str,
        document_type: str = Form(...),
        correspondent: str = Form(...),
        document_date: str = Form(""),
        title: str = Form(...),
        language: str = Form("fr"),
        new_correspondent: bool = Form(False),
    ):
        sfile = review_dir / (filename + _SUFFIX)
        pdf_path = review_dir / filename
        if not sfile.exists() or not pdf_path.exists():
            raise HTTPException(status_code=404, detail="Review item not found")

        data = json.loads(sfile.read_text())
        result = ClassificationResult.model_validate(
            {
                "document_type": document_type,
                "correspondent": correspondent,
                "document_date": document_date or None,
                "title": title,
                "language": language,
                "confidence": float(data.get("confidence", 0)),
                "reasoning": data.get("reasoning", ""),
                "new_correspondent": new_correspondent,
            }
        )
        target = organize(pdf_path, result, config)
        sfile.unlink()

        journal = _make_journal()
        journal.append(
            JournalEntry(
                id=Journal.new_id(),
                hash_sha256=data.get("hash_sha256", ""),
                source_filename=data.get("source_filename", filename),
                source_size_bytes=int(data.get("source_size_bytes", 0)),
                processed_at=datetime.now(timezone.utc).isoformat(),
                status="success",
                document_type=result.document_type,
                correspondent=result.correspondent,
                document_date=result.document_date or "",
                title=result.title,
                target_path=str(target),
                llm_provider=data.get("llm_provider", ""),
                llm_model=data.get("llm_model", ""),
                confidence=result.confidence,
                language=result.language,
                new_correspondent=result.new_correspondent,
                ocr_skipped=bool(data.get("ocr_skipped", False)),
                processing_duration_seconds=float(data.get("processing_duration_seconds", 0)),
            )
        )
        _log_feedback(
            feedback_path,
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "id": data.get("id"),
                "source_filename": data.get("source_filename"),
                "original_suggestion": data,
                "user_action": "edit",
                "final_values": result.model_dump(),
            },
        )
        return JSONResponse({"status": "ok", "target": str(target)})

    @app.post("/api/review/reject/{filename:path}")
    async def review_reject(filename: str):
        sfile = review_dir / (filename + _SUFFIX)
        pdf_path = review_dir / filename
        if not sfile.exists() or not pdf_path.exists():
            raise HTTPException(status_code=404, detail="Review item not found")

        data = json.loads(sfile.read_text())
        failed_dir = config.paths.failed / (data.get("id", "unknown") + "_rejected")
        failed_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(pdf_path), str(failed_dir / filename))
        (failed_dir / "error.json").write_text(
            json.dumps({"stage": "user_rejected", "reason": "User rejected review"}, indent=2)
        )
        sfile.unlink()

        _log_feedback(
            feedback_path,
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "id": data.get("id"),
                "source_filename": data.get("source_filename"),
                "original_suggestion": data,
                "user_action": "reject",
                "final_values": None,
            },
        )
        return JSONResponse({"status": "ok"})

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
