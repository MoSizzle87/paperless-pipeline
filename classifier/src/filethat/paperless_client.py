"""HTTP client for the Paperless-ngx REST API."""

import logging
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from filethat.schemas import (
    PaperlessCorrespondent,
    PaperlessDocument,
    PaperlessDocumentType,
    PaperlessTag,
)

logger = logging.getLogger(__name__)


class PaperlessClient:
    """Minimal wrapper around the Paperless-ngx REST API."""

    def __init__(self, base_url: str, token: str) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Token {token}"},
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PaperlessClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ─────────────────────────────────────────────────────────────── Tags

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def list_tags(self) -> list[PaperlessTag]:
        return [PaperlessTag.model_validate(t) for t in self._paginate("/tags/")]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def create_tag(self, name: str, color: str = "#808080") -> PaperlessTag:
        r = self._client.post("/tags/", json={"name": name, "color": color})
        r.raise_for_status()
        return PaperlessTag.model_validate(r.json())

    # ───────────────────────────────────────────────────────── Correspondents

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def list_correspondents(self) -> list[PaperlessCorrespondent]:
        return [
            PaperlessCorrespondent.model_validate(c) for c in self._paginate("/correspondents/")
        ]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def create_correspondent(self, name: str) -> PaperlessCorrespondent:
        r = self._client.post("/correspondents/", json={"name": name})
        r.raise_for_status()
        return PaperlessCorrespondent.model_validate(r.json())

    # ──────────────────────────────────────────────────────── Document types

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def list_document_types(self) -> list[PaperlessDocumentType]:
        return [PaperlessDocumentType.model_validate(t) for t in self._paginate("/document_types/")]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def create_document_type(self, name: str) -> PaperlessDocumentType:
        r = self._client.post("/document_types/", json={"name": name})
        r.raise_for_status()
        return PaperlessDocumentType.model_validate(r.json())

    # ─────────────────────────────────────────────────────────── Documents

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def list_documents_without_tags(self, excluded_tag_ids: list[int]) -> list[PaperlessDocument]:
        """Return documents that have NONE of the given tags.

        Used by the poller to fetch documents not yet classified.
        Paperless uses tags__id__none to filter out documents with any of the given tags.
        """
        params: dict[str, Any] = {
            "tags__id__none": ",".join(str(i) for i in excluded_tag_ids),
            "ordering": "added",  # oldest first
        }
        return [PaperlessDocument.model_validate(d) for d in self._paginate("/documents/", params)]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def list_documents_with_tag(self, tag_id: int) -> list[PaperlessDocument]:
        """Return documents that have the given tag (used for reprocessing)."""
        params: dict[str, Any] = {"tags__id__all": str(tag_id)}
        return [PaperlessDocument.model_validate(d) for d in self._paginate("/documents/", params)]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def get_document(self, doc_id: int) -> PaperlessDocument:
        r = self._client.get(f"/documents/{doc_id}/")
        r.raise_for_status()
        return PaperlessDocument.model_validate(r.json())

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def patch_document(self, doc_id: int, payload: dict[str, Any]) -> None:
        r = self._client.patch(f"/documents/{doc_id}/", json=payload)
        r.raise_for_status()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def download_document(self, doc_id: int) -> bytes:
        """Download the original PDF of a document from Paperless."""
        r = self._client.get(f"/documents/{doc_id}/download/", params={"original": "true"})
        r.raise_for_status()
        return r.content

    def add_tag(self, doc_id: int, tag_id: int) -> None:
        """Add a tag to a document without affecting other existing tags."""
        doc = self.get_document(doc_id)
        if tag_id not in doc.tags:
            self.patch_document(doc_id, {"tags": [*doc.tags, tag_id]})

    def remove_tag(self, doc_id: int, tag_id: int) -> None:
        """Remove a tag from a document (used for reprocessing)."""
        doc = self.get_document(doc_id)
        if tag_id in doc.tags:
            self.patch_document(doc_id, {"tags": [t for t in doc.tags if t != tag_id]})

    # ──────────────────────────────────────────────────────────── Private

    def _paginate(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Iterate over all pages of a paginated Paperless endpoint."""
        params = {**(params or {}), "page_size": 100, "page": 1}
        results: list[dict[str, Any]] = []
        while True:
            r = self._client.get(path, params=params)
            r.raise_for_status()
            data = r.json()
            results.extend(data.get("results", []))
            if not data.get("next"):
                break
            params["page"] += 1  # type: ignore[operator]
        return results
