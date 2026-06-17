"""SQLAlchemy repository for technical documents."""

from __future__ import annotations

import math
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from via.bounded_contexts.document_management.application.ports import (
    DocumentSearchResult,
    EmbeddableFragment,
    IDocumentReadRepository,
    IDocumentRepository,
    IDocumentSearchRepository,
    IFragmentEmbeddingRepository,
)
from via.bounded_contexts.document_management.domain.document import TechnicalDocument
from via.bounded_contexts.document_management.domain.fragment import DocumentFragment
from via.bounded_contexts.document_management.domain.value_objects import DocumentFormat, DocumentStatus
from via.bounded_contexts.document_management.infrastructure.orm_models import DocumentFragmentModel, DocumentModel


class SQLAlchemyDocumentRepository(
    IDocumentRepository,
    IDocumentReadRepository,
    IFragmentEmbeddingRepository,
    IDocumentSearchRepository,
):
    """Persist technical documents only in the documental schema."""

    def __init__(self, session: Session) -> None:
        """Create the repository bound to a synchronous SQLAlchemy session."""

        self._session = session

    def save(self, document: TechnicalDocument) -> None:
        """Persist a document and all of its fragments without committing."""

        self._session.add(_document_to_model(document))
        for fragment in document.fragments:
            self._session.add(_fragment_to_model(fragment))

    def get_document(self, document_id: UUID) -> TechnicalDocument | None:
        """Return one document aggregate from the documental schema."""

        document_model = self._session.get(DocumentModel, document_id)
        if document_model is None:
            return None
        return document_from_model(document_model, self._fragment_models_for_document(document_id))

    def list_fragments(self, document_id: UUID) -> list[DocumentFragment]:
        """Return fragments for one document from the documental schema."""

        return [
            _fragment_from_model(fragment, index)
            for index, fragment in enumerate(self._fragment_models_for_document(document_id))
        ]

    def get_fragments_for_embedding(self, fragment_ids: list[UUID] | None = None) -> list[EmbeddableFragment]:
        """Return stored fragments without embeddings, optionally narrowed by id."""

        statement = select(DocumentFragmentModel).where(DocumentFragmentModel.embedding.is_(None))
        if fragment_ids is not None:
            statement = statement.where(DocumentFragmentModel.id.in_(fragment_ids))
        rows = self._session.execute(statement).scalars().all()
        return [EmbeddableFragment(id=row.id, text=row.text) for row in rows]

    def save_fragment_embedding(self, fragment_id: UUID, embedding: list[float]) -> None:
        """Assign an embedding to a stored fragment without committing."""

        fragment = self._session.get(DocumentFragmentModel, fragment_id)
        if fragment is None:
            raise LookupError(f"document fragment not found: {fragment_id}")
        fragment.embedding = [float(value) for value in embedding]

    def search_fragments(
        self,
        query_embedding: list[float],
        crop_tags: list[str],
        max_results: int,
    ) -> list[DocumentSearchResult]:
        """Search documental fragments by crop tag and cosine similarity.

        The current schema has a pgvector column and ANN index, but the local
        lightweight Vector type intentionally does not expose pgvector operators.
        This repository therefore keeps the contract compatible by fetching only
        documental rows and ranking their stored vectors in Python.
        """

        rows = (
            self._session.execute(
                select(DocumentFragmentModel).where(DocumentFragmentModel.embedding.is_not(None))
            )
            .scalars()
            .all()
        )
        return rank_fragment_models(rows, query_embedding, crop_tags, max_results)

    def _fragment_models_for_document(self, document_id: UUID) -> list[DocumentFragmentModel]:
        rows = (
            self._session.execute(
                select(DocumentFragmentModel).where(DocumentFragmentModel.document_id == document_id)
            )
            .scalars()
            .all()
        )
        return list(rows)


def _document_to_model(document: TechnicalDocument) -> DocumentModel:
    return DocumentModel(
        id=document.id,
        title=document.title,
        format=document.format.value,
        crop_tags=document.crop_tags,
        size_bytes=document.size_bytes,
        status=document.status.value,
    )


def _fragment_to_model(fragment: DocumentFragment) -> DocumentFragmentModel:
    return DocumentFragmentModel(
        id=fragment.id,
        document_id=fragment.document_id,
        text=fragment.text,
        page_ref=fragment.page_ref,
        crop_tags=fragment.crop_tags,
        token_count=fragment.token_count,
        embedding=fragment.embedding,
    )


def document_from_model(model: DocumentModel, fragments: list[DocumentFragmentModel] | None = None) -> TechnicalDocument:
    """Map ORM rows back to the 9A domain aggregate."""

    document = TechnicalDocument(
        id=model.id,
        title=model.title,
        format=DocumentFormat(model.format),
        crop_tags=list(model.crop_tags),
        size_bytes=int(model.size_bytes),
        status=DocumentStatus(model.status),
    )
    for index, fragment in enumerate(fragments or []):
        document.fragments.append(_fragment_from_model(fragment, index))
    return document


def _fragment_from_model(fragment: DocumentFragmentModel, index: int) -> DocumentFragment:
    return DocumentFragment(
        id=fragment.id,
        document_id=fragment.document_id,
        text=fragment.text,
        page_ref=fragment.page_ref,
        crop_tags=list(fragment.crop_tags),
        token_count=int(fragment.token_count),
        chunk_index=index,
        embedding=fragment.embedding,
    )


def rank_fragment_models(
    fragments: Sequence[DocumentFragmentModel],
    query_embedding: Sequence[float],
    crop_tags: Sequence[str],
    max_results: int,
) -> list[DocumentSearchResult]:
    """Rank fragment ORM rows by crop tag overlap and cosine similarity."""

    requested_tags = {tag.strip().lower() for tag in crop_tags if tag.strip()}
    ranked: list[DocumentSearchResult] = []
    for fragment in fragments:
        fragment_tags = {str(tag).strip().lower() for tag in fragment.crop_tags if str(tag).strip()}
        if requested_tags and requested_tags.isdisjoint(fragment_tags):
            continue
        if fragment.embedding is None:
            continue
        score = cosine_similarity(query_embedding, fragment.embedding)
        ranked.append(
            DocumentSearchResult(
                fragment_id=fragment.id,
                document_id=fragment.document_id,
                page_ref=fragment.page_ref,
                text=fragment.text,
                crop_tags=list(fragment.crop_tags),
                score=score,
            )
        )

    ranked.sort(key=lambda result: (-result.score, str(result.fragment_id)))
    return ranked[:max_results]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Calculate cosine similarity for two embedding vectors."""

    left_values = [float(value) for value in left]
    right_values = [float(value) for value in right]
    if len(left_values) != len(right_values) or not left_values:
        raise ValueError("embedding vectors must have the same non-zero dimension")

    dot = sum(a * b for a, b in zip(left_values, right_values, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left_values))
    right_norm = math.sqrt(sum(value * value for value in right_values))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)
