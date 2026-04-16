"""Gestion des référentiels : whitelist canonique (Classe A) + création auto (Classe B)."""

import logging
from pathlib import Path

import yaml

from pipeline.normalizer import fuzzy_match, slugify
from pipeline.paperless_client import PaperlessClient
from pipeline.schemas import PaperlessCorrespondent, PaperlessDocumentType, PaperlessTag

logger = logging.getLogger(__name__)


class CanonicalCorrespondents:
    """Whitelist canonique des correspondants (Classe A), chargée depuis YAML."""

    def __init__(self, yaml_path: Path):
        with yaml_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        # Map slug(alias) → nom canonique
        self._alias_to_canonical: dict[str, str] = {}
        self._canonicals: list[str] = []
        for entry in data:
            canonical: str = entry["canonical"]
            self._canonicals.append(canonical)
            self._alias_to_canonical[slugify(canonical)] = canonical
            for alias in entry.get("aliases", []):
                self._alias_to_canonical[slugify(alias)] = canonical

    @property
    def canonical_names(self) -> list[str]:
        return list(self._canonicals)

    def resolve_to_canonical(self, raw_name: str) -> str | None:
        """Si raw_name matche un alias connu (exact sur slug), retourne le canonical.

        Sinon None, ce qui signifie "pas dans la Classe A, à traiter en Classe B".
        """
        return self._alias_to_canonical.get(slugify(raw_name))


class ReferentialManager:
    """Orchestre la résolution des correspondants/tags/types Paperless.

    - Classe A : match exact sur whitelist YAML → renvoie l'ID Paperless canonique
    - Classe B : création automatique avec garde-fou Levenshtein contre les existants
    """

    def __init__(
        self,
        client: PaperlessClient,
        canonical_correspondents: CanonicalCorrespondents,
        levenshtein_threshold: float,
    ):
        self._client = client
        self._canonical = canonical_correspondents
        self._threshold = levenshtein_threshold
        self._refresh_caches()

    def _refresh_caches(self) -> None:
        """Recharge les correspondants/tags/types depuis Paperless."""
        self._correspondents: dict[str, PaperlessCorrespondent] = {
            c.name: c for c in self._client.list_correspondents()
        }
        self._tags: dict[str, PaperlessTag] = {t.name: t for t in self._client.list_tags()}
        self._doc_types: dict[str, PaperlessDocumentType] = {
            t.name: t for t in self._client.list_document_types()
        }

    # --------------------------------------------------------- Correspondents

    def resolve_correspondent(self, raw_name: str) -> tuple[int, bool]:
        """Résout un correspondant vers son ID Paperless.

        Returns:
            (id, was_created): was_created=True si on a créé une nouvelle entrée.
        """
        # 1. Classe A : match sur whitelist canonique
        canonical = self._canonical.resolve_to_canonical(raw_name)
        if canonical is not None:
            if canonical in self._correspondents:
                return self._correspondents[canonical].id, False
            # Premier usage d'un canonical jamais créé dans Paperless : on le crée
            new = self._client.create_correspondent(canonical)
            self._correspondents[canonical] = new
            logger.info("Correspondant canonique créé : %s", canonical)
            return new.id, True

        # 2. Classe B : garde-fou Levenshtein contre l'existant Paperless
        existing_match = fuzzy_match(raw_name, list(self._correspondents.keys()), self._threshold)
        if existing_match is not None:
            if existing_match != raw_name:
                logger.info("Correspondant fuzzy-matché : '%s' → '%s'", raw_name, existing_match)
            return self._correspondents[existing_match].id, False

        # 3. Création nouvelle entrée Classe B
        new = self._client.create_correspondent(raw_name)
        self._correspondents[raw_name] = new
        logger.info("Nouveau correspondant créé (Classe B) : %s", raw_name)
        return new.id, True

    # ----------------------------------------------------------------- Tags

    def resolve_tag(self, name: str) -> int:
        """Résout un tag existant. Lève KeyError si pas dans Paperless (doit être pré-créé)."""
        if name not in self._tags:
            # Les tags doivent tous être pré-créés via init_referential.
            # Si on arrive ici, c'est un tag libre renvoyé par le LLM.
            # On le crée à la volée avec une couleur par défaut.
            new = self._client.create_tag(name)
            self._tags[name] = new
            logger.info("Nouveau tag créé à la volée : %s", name)
        return self._tags[name].id

    def resolve_tags(self, names: list[str]) -> list[int]:
        return [self.resolve_tag(n) for n in names]

    def tag_id(self, name: str) -> int:
        """Résout un tag qui DOIT exister (utilisé pour les tags système ai:*)."""
        if name not in self._tags:
            raise RuntimeError(f"Tag '{name}' introuvable. Lance `make init-referential` d'abord.")
        return self._tags[name].id

    # ------------------------------------------------------ Document types

    def resolve_document_type(self, name: str) -> int:
        """Résout un type de document. Doit exister (pré-créé via init_referential)."""
        if name not in self._doc_types:
            raise RuntimeError(
                f"Type de document '{name}' introuvable. Lance `make init-referential` d'abord."
            )
        return self._doc_types[name].id
