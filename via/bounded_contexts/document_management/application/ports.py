"""Application ports for Document Management."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from via.bounded_contexts.document_management.domain.document import TechnicalDocument
from via.bounded_contexts.document_management.domain.fragment import DocumentFragment


@dataclass(frozen=True)
class EmbeddableFragment:
    """Fragment data required to generate an embedding."""

    id: UUID
    text: str


@dataclass(frozen=True)
class DocumentSearchResult:
    """Relevant documental fragment returned by a search query."""

    fragment_id: UUID
    document_id: UUID
    page_ref: int | None
    text: str
    crop_tags: list[str]
    score: float


class IDocumentRepository(Protocol):
    """Persistence port for technical documents and fragments."""

    def save(self, document: TechnicalDocument) -> None:
        """Persist a technical document and its fragments."""


class IDocumentReadRepository(Protocol):
    """Read port for technical documents and fragments."""

    def get_document(self, document_id: UUID) -> TechnicalDocument | None:
        """Return one technical document or None when it does not exist."""

    def list_fragments(self, document_id: UUID) -> list[DocumentFragment]:
        """Return fragments associated with one technical document."""


class IEmbeddingProvider(Protocol):
    """Port for generating embedding vectors from text."""

    def generate_embedding(self, text: str) -> list[float]:
        """Return an embedding vector for the supplied text."""


class IFragmentEmbeddingRepository(Protocol):
    """Persistence port for assigning embeddings to stored fragments."""

    def get_fragments_for_embedding(self, fragment_ids: list[UUID] | None = None) -> list[EmbeddableFragment]:
        """Return fragments whose embedding should be generated."""

    def save_fragment_embedding(self, fragment_id: UUID, embedding: list[float]) -> None:
        """Persist the embedding for a fragment without committing."""


class IDocumentSearchRepository(Protocol):
    """Read port for searching fragments stored in the documental schema."""

    def search_fragments(
        self,
        query_embedding: list[float],
        crop_tags: list[str],
        max_results: int,
    ) -> list[DocumentSearchResult]:
        """Return relevant fragments ordered by descending score."""
