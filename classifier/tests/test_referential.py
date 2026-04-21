"""Unit tests for filethat.referential."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from filethat.referential import (
    CanonicalCorrespondents,
    DocumentTypeRegistry,
    ReferentialManager,
    TagRegistry,
)
from filethat.schemas import PaperlessCorrespondent, PaperlessDocumentType, PaperlessTag

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def document_types_yaml(tmp_path: Path) -> Path:
    data = [
        {"id": "invoice", "labels": {"fr": "Facture", "en": "Invoice"}, "priority": 1},
        {"id": "payslip", "labels": {"fr": "Bulletin de paie", "en": "Payslip"}, "priority": 2},
        {"id": "contract", "labels": {"fr": "Contrat", "en": "Contract"}, "priority": 3},
        {"id": "other", "labels": {"fr": "Autre", "en": "Other"}, "priority": 99},
    ]
    path = tmp_path / "document_types.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


@pytest.fixture
def correspondents_yaml(tmp_path: Path) -> Path:
    data = [
        {"canonical": "EDF", "aliases": ["Électricité de France", "EDF SA"], "category": "energy"},
        {"canonical": "CAF", "aliases": ["Caisse d'Allocations Familiales"], "category": "admin"},
        {"canonical": "URSSAF", "aliases": [], "category": "admin"},
    ]
    path = tmp_path / "correspondents.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


@pytest.fixture
def tags_yaml(tmp_path: Path) -> Path:
    data = {
        "system": [
            {"id": "ai:processed", "color": "#2ecc71"},
            {"id": "ai:to-check", "color": "#f39c12"},
            {"id": "ai:failed", "color": "#e74c3c"},
            {"id": "workflow:exported", "color": "#3498db"},
        ],
        "business": [
            {"id": "energie", "labels": {"fr": "energie", "en": "energy"}, "color": "#3498db"},
            {"id": "banque", "labels": {"fr": "banque", "en": "banking"}, "color": "#16a085"},
        ],
    }
    path = tmp_path / "tags.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


@pytest.fixture
def mock_paperless() -> MagicMock:
    client = MagicMock()
    client.list_correspondents.return_value = [
        PaperlessCorrespondent(id=1, name="EDF"),
        PaperlessCorrespondent(id=2, name="CAF"),
    ]
    client.list_tags.return_value = [
        PaperlessTag(id=10, name="ai:processed"),
        PaperlessTag(id=11, name="ai:to-check"),
        PaperlessTag(id=12, name="ai:failed"),
        PaperlessTag(id=13, name="workflow:exported"),
    ]
    client.list_document_types.return_value = [
        PaperlessDocumentType(id=20, name="Facture"),
        PaperlessDocumentType(id=21, name="Bulletin de paie"),
    ]
    return client


# ── DocumentTypeRegistry ──────────────────────────────────────────────────────


class TestDocumentTypeRegistry:
    def test_label_fr(self, document_types_yaml: Path) -> None:
        registry = DocumentTypeRegistry(document_types_yaml, language="fr")
        assert registry.label("invoice") == "Facture"
        assert registry.label("payslip") == "Bulletin de paie"

    def test_label_en(self, document_types_yaml: Path) -> None:
        registry = DocumentTypeRegistry(document_types_yaml, language="en")
        assert registry.label("invoice") == "Invoice"
        assert registry.label("payslip") == "Payslip"

    def test_fallback_to_fr_for_unknown_language(self, document_types_yaml: Path) -> None:
        registry = DocumentTypeRegistry(document_types_yaml, language="de")
        assert registry.label("invoice") == "Facture"

    def test_ids_ordered_by_priority(self, document_types_yaml: Path) -> None:
        registry = DocumentTypeRegistry(document_types_yaml, language="fr")
        assert registry.ids == ["invoice", "payslip", "contract", "other"]

    def test_unknown_id_raises(self, document_types_yaml: Path) -> None:
        registry = DocumentTypeRegistry(document_types_yaml, language="fr")
        with pytest.raises(KeyError, match="unknown-type"):
            registry.label("unknown-type")


# ── CanonicalCorrespondents ───────────────────────────────────────────────────


class TestCanonicalCorrespondents:
    def test_exact_canonical_match(self, correspondents_yaml: Path) -> None:
        cc = CanonicalCorrespondents(correspondents_yaml)
        assert cc.resolve_to_canonical("EDF") == "EDF"

    def test_alias_match(self, correspondents_yaml: Path) -> None:
        cc = CanonicalCorrespondents(correspondents_yaml)
        assert cc.resolve_to_canonical("EDF SA") == "EDF"
        assert cc.resolve_to_canonical("Électricité de France") == "EDF"

    def test_alias_case_insensitive(self, correspondents_yaml: Path) -> None:
        cc = CanonicalCorrespondents(correspondents_yaml)
        assert cc.resolve_to_canonical("edf sa") == "EDF"

    def test_unknown_returns_none(self, correspondents_yaml: Path) -> None:
        cc = CanonicalCorrespondents(correspondents_yaml)
        assert cc.resolve_to_canonical("inconnu-xyz") is None

    def test_canonical_names(self, correspondents_yaml: Path) -> None:
        cc = CanonicalCorrespondents(correspondents_yaml)
        assert "EDF" in cc.canonical_names
        assert "CAF" in cc.canonical_names

    def test_local_yaml_merged(self, correspondents_yaml: Path, tmp_path: Path) -> None:
        local = tmp_path / "correspondents.local.yaml"
        local.write_text(
            yaml.dump([{"canonical": "MyLandlord", "aliases": [], "category": "housing"}]),
            encoding="utf-8",
        )
        cc = CanonicalCorrespondents(correspondents_yaml)
        assert cc.resolve_to_canonical("MyLandlord") == "MyLandlord"


# ── TagRegistry ───────────────────────────────────────────────────────────────


class TestTagRegistry:
    def test_system_tag_label_equals_id(self, tags_yaml: Path) -> None:
        registry = TagRegistry(tags_yaml, language="fr")
        assert registry.label("ai:processed") == "ai:processed"
        assert registry.label("workflow:exported") == "workflow:exported"

    def test_business_tag_label_fr(self, tags_yaml: Path) -> None:
        registry = TagRegistry(tags_yaml, language="fr")
        assert registry.label("energie") == "energie"

    def test_business_tag_label_en(self, tags_yaml: Path) -> None:
        registry = TagRegistry(tags_yaml, language="en")
        assert registry.label("energie") == "energy"

    def test_unknown_tag_returns_id(self, tags_yaml: Path) -> None:
        registry = TagRegistry(tags_yaml, language="fr")
        assert registry.label("free-tag") == "free-tag"

    def test_all_ids(self, tags_yaml: Path) -> None:
        registry = TagRegistry(tags_yaml, language="fr")
        assert "ai:processed" in registry.all_ids
        assert "energie" in registry.all_ids


# ── ReferentialManager ────────────────────────────────────────────────────────


class TestReferentialManager:
    def _make_manager(
        self,
        mock_paperless: MagicMock,
        document_types_yaml: Path,
        correspondents_yaml: Path,
        tags_yaml: Path,
    ) -> ReferentialManager:
        from filethat.referential import CanonicalCorrespondents, DocumentTypeRegistry, TagRegistry

        return ReferentialManager(
            client=mock_paperless,
            canonical_correspondents=CanonicalCorrespondents(correspondents_yaml),
            document_type_registry=DocumentTypeRegistry(document_types_yaml, language="fr"),
            tag_registry=TagRegistry(tags_yaml, language="fr"),
            levenshtein_threshold=0.85,
        )

    def test_resolve_correspondent_class_a(
        self,
        mock_paperless: MagicMock,
        document_types_yaml: Path,
        correspondents_yaml: Path,
        tags_yaml: Path,
    ) -> None:
        manager = self._make_manager(
            mock_paperless, document_types_yaml, correspondents_yaml, tags_yaml
        )
        doc_id, was_created = manager.resolve_correspondent("EDF SA")
        assert doc_id == 1
        assert was_created is False

    def test_resolve_correspondent_class_b_creates(
        self,
        mock_paperless: MagicMock,
        document_types_yaml: Path,
        correspondents_yaml: Path,
        tags_yaml: Path,
    ) -> None:
        mock_paperless.create_correspondent.return_value = PaperlessCorrespondent(
            id=99, name="NewCorp"
        )
        manager = self._make_manager(
            mock_paperless, document_types_yaml, correspondents_yaml, tags_yaml
        )
        doc_id, was_created = manager.resolve_correspondent("NewCorp")
        assert doc_id == 99
        assert was_created is True
        mock_paperless.create_correspondent.assert_called_once_with("NewCorp")

    def test_resolve_document_type_existing(
        self,
        mock_paperless: MagicMock,
        document_types_yaml: Path,
        correspondents_yaml: Path,
        tags_yaml: Path,
    ) -> None:
        manager = self._make_manager(
            mock_paperless, document_types_yaml, correspondents_yaml, tags_yaml
        )
        assert manager.resolve_document_type("invoice") == 20

    def test_resolve_document_type_creates(
        self,
        mock_paperless: MagicMock,
        document_types_yaml: Path,
        correspondents_yaml: Path,
        tags_yaml: Path,
    ) -> None:
        mock_paperless.create_document_type.return_value = PaperlessDocumentType(
            id=30, name="Contrat"
        )
        manager = self._make_manager(
            mock_paperless, document_types_yaml, correspondents_yaml, tags_yaml
        )
        result = manager.resolve_document_type("contract")
        assert result == 30
        mock_paperless.create_document_type.assert_called_once_with("Contrat")

    def test_tag_id_system_tag(
        self,
        mock_paperless: MagicMock,
        document_types_yaml: Path,
        correspondents_yaml: Path,
        tags_yaml: Path,
    ) -> None:
        manager = self._make_manager(
            mock_paperless, document_types_yaml, correspondents_yaml, tags_yaml
        )
        assert manager.tag_id("ai:processed") == 10
        assert manager.tag_id("ai:failed") == 12

    def test_tag_id_missing_raises(
        self,
        mock_paperless: MagicMock,
        document_types_yaml: Path,
        correspondents_yaml: Path,
        tags_yaml: Path,
    ) -> None:
        manager = self._make_manager(
            mock_paperless, document_types_yaml, correspondents_yaml, tags_yaml
        )
        with pytest.raises(RuntimeError, match="init-referential"):
            manager.tag_id("nonexistent:tag")

    def test_resolve_tags(
        self,
        mock_paperless: MagicMock,
        document_types_yaml: Path,
        correspondents_yaml: Path,
        tags_yaml: Path,
    ) -> None:
        mock_paperless.create_tag.return_value = PaperlessTag(id=50, name="energie")
        manager = self._make_manager(
            mock_paperless, document_types_yaml, correspondents_yaml, tags_yaml
        )
        ids = manager.resolve_tags(["ai:processed", "ai:failed"])
        assert ids == [10, 12]
