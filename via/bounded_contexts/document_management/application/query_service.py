"""Application services for document embeddings and fragment search."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from via.bounded_contexts.document_management.application.ports import (
    DocumentSearchResult,
    IDocumentReadRepository,
    IDocumentSearchRepository,
    IEmbeddingProvider,
    IFragmentEmbeddingRepository,
)
from via.bounded_contexts.document_management.domain.document import TechnicalDocument
from via.bounded_contexts.document_management.domain.fragment import DocumentFragment
from via.bounded_contexts.document_management.domain.value_objects import DocumentDomainError, normalize_crop_tags


@dataclass(frozen=True)
class AssignFragmentEmbeddingsCommand:
    """Command to generate embeddings for selected or pending fragments."""

    fragment_ids: list[UUID] | None = None


@dataclass(frozen=True)
class SearchDocumentFragmentsQuery:
    """Query for retrieving relevant documental fragments."""

    text: str
    crop_tags: list[str]
    max_results: int = 10


class DocumentNotFoundError(Exception):
    """Raised when a technical document cannot be found."""


class DocumentEmbeddingService:
    """Generate embeddings through an injected provider and persist them."""

    def __init__(self, provider: IEmbeddingProvider, repository: IFragmentEmbeddingRepository) -> None:
        """Create the service with provider and repository ports."""

        self._provider = provider
        self._repository = repository

    def assign_embeddings(self, command: AssignFragmentEmbeddingsCommand) -> int:
        """Generate and save embeddings for stored fragments."""

        fragments = self._repository.get_fragments_for_embedding(command.fragment_ids)
        for fragment in fragments:
            embedding = self._provider.generate_embedding(fragment.text)
            self._repository.save_fragment_embedding(fragment.id, embedding)
        return len(fragments)

    def assign_embeddings_to_document(self, document: TechnicalDocument) -> TechnicalDocument:
        """Assign embeddings to a new aggregate before it is persisted."""

        embedded_fragments: list[DocumentFragment] = []
        for fragment in document.fragments:
            embedding = self._provider.generate_embedding(fragment.text)
            embedded_fragments.append(fragment.with_embedding(embedding))
        document.fragments = embedded_fragments
        return document


class DocumentSearchService:
    """Search technical fragments without calling external providers directly."""

    def __init__(self, provider: IEmbeddingProvider, repository: IDocumentSearchRepository) -> None:
        """Create the service with embedding and search ports."""

        self._provider = provider
        self._repository = repository

    def search(self, query: SearchDocumentFragmentsQuery) -> list[DocumentSearchResult]:
        """Generate the query embedding and return matching fragments."""

        text = query.text.strip()
        if not text:
            raise DocumentDomainError("search text must not be empty")
        if query.max_results <= 0:
            raise DocumentDomainError("max_results must be positive")

        crop_tags = normalize_crop_tags(query.crop_tags)
        query_embedding = self._provider.generate_embedding(text)
        return self._repository.search_fragments(query_embedding, crop_tags, query.max_results)


class DocumentQueryService:
    """Read technical documents and fragments."""

    def __init__(self, repository: IDocumentReadRepository) -> None:
        """Create the query service with a read repository."""

        self._repository = repository

    def get_document(self, document_id: UUID) -> TechnicalDocument:
        """Return one technical document or raise when it does not exist."""

        document = self._repository.get_document(document_id)
        if document is None:
            raise DocumentNotFoundError(f"document not found: {document_id}")
        return document

    def list_fragments(self, document_id: UUID) -> list[DocumentFragment]:
        """Return all fragments for one technical document."""

        if self._repository.get_document(document_id) is None:
            raise DocumentNotFoundError(f"document not found: {document_id}")
        return self._repository.list_fragments(document_id)
