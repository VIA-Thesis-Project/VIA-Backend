"""Unit tests for Document Management 9B embeddings and search."""

from __future__ import annotations

import ast
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from via.bounded_contexts.document_management.application.ports import EmbeddableFragment
from via.bounded_contexts.document_management.application.query_service import (
    AssignFragmentEmbeddingsCommand,
    DocumentEmbeddingService,
    DocumentSearchService,
    SearchDocumentFragmentsQuery,
)
from via.bounded_contexts.document_management.domain.document import TechnicalDocument
from via.bounded_contexts.document_management.infrastructure.document_repository import (
    SQLAlchemyDocumentRepository,
    cosine_similarity,
    rank_fragment_models,
)
from via.bounded_contexts.document_management.infrastructure.orm_models import DocumentFragmentModel
from via.shared.database.base import DOCUMENTAL_SCHEMA
from via.shared.database.types import Vector


ROOT = Path(__file__).resolve().parents[3]
DOMAIN = ROOT / "via" / "bounded_contexts" / "document_management" / "domain"
MIGRATION = ROOT / "migrations" / "versions" / "20260614_0002_initial_tables.py"


def test_generate_embedding_with_fake_provider_and_save_it_on_existing_fragment() -> None:
    provider = FakeEmbeddingProvider({"fragmento cacao": [1.0, 0.0, 0.0]})
    repository = FakeEmbeddingRepository([EmbeddableFragment(uuid4(), "fragmento cacao")])
    service = DocumentEmbeddingService(provider, repository)

    count = service.assign_embeddings(AssignFragmentEmbeddingsCommand())

    assert count == 1
    assert provider.calls == ["fragmento cacao"]
    assert repository.saved_embeddings == {repository.fragments[0].id: [1.0, 0.0, 0.0]}


def test_assign_embedding_to_new_document_fragment_before_persistence() -> None:
    provider = FakeEmbeddingProvider({"contenido tecnico": [0.0, 1.0]})
    service = DocumentEmbeddingService(provider, FakeEmbeddingRepository([]))
    document = TechnicalDocument.create("Manual", "PDF", ["cacao"], 100)
    document.add_fragment("contenido tecnico", page_ref=4, crop_tags=["cacao"], token_count=12)

    embedded = service.assign_embeddings_to_document(document)

    assert embedded.fragments[0].embedding == [0.0, 1.0]
    assert provider.calls == ["contenido tecnico"]


def test_repository_save_preserves_fragment_embedding() -> None:
    session = FakeSession()
    document = TechnicalDocument.create("Manual", "PDF", ["cacao"], 100)
    fragment = document.add_fragment("contenido tecnico", page_ref=2, crop_tags=["cacao"], token_count=10)
    document.fragments = [fragment.with_embedding([0.25, 0.75])]

    SQLAlchemyDocumentRepository(session).save(document)

    stored_fragment = next(model for model in session.added if isinstance(model, DocumentFragmentModel))
    assert stored_fragment.embedding == [0.25, 0.75]


def test_repository_updates_existing_fragment_embedding_without_commit() -> None:
    fragment_id = uuid4()
    fragment = _fragment_model(fragment_id, uuid4(), "texto", ["cacao"], [0.0, 1.0])
    session = FakeSession(stored={fragment_id: fragment})

    SQLAlchemyDocumentRepository(session).save_fragment_embedding(fragment_id, [1.0, 0.0])

    assert fragment.embedding == [1.0, 0.0]
    assert session.committed is False


def test_search_fragments_by_crop_tags_and_fake_similarity_ordered_by_score() -> None:
    document_id = uuid4()
    query_embedding = [1.0, 0.0]
    fragments = [
        _fragment_model(uuid4(), document_id, "muy relevante", ["cacao"], [1.0, 0.0], page_ref=1),
        _fragment_model(uuid4(), document_id, "menos relevante", ["cacao"], [0.5, 0.5], page_ref=2),
        _fragment_model(uuid4(), document_id, "otro cultivo", ["maiz"], [1.0, 0.0], page_ref=3),
    ]

    results = rank_fragment_models(fragments, query_embedding, ["cacao"], max_results=5)

    assert [result.text for result in results] == ["muy relevante", "menos relevante"]
    assert results[0].score > results[1].score
    assert results[0].document_id == document_id
    assert results[0].page_ref == 1
    assert results[0].crop_tags == ["cacao"]


def test_search_returns_max_n_fragments() -> None:
    fragments = [
        _fragment_model(uuid4(), uuid4(), "uno", ["cacao"], [1.0, 0.0]),
        _fragment_model(uuid4(), uuid4(), "dos", ["cacao"], [0.8, 0.2]),
        _fragment_model(uuid4(), uuid4(), "tres", ["cacao"], [0.7, 0.3]),
    ]

    results = rank_fragment_models(fragments, [1.0, 0.0], ["cacao"], max_results=2)

    assert len(results) == 2
    assert [result.text for result in results] == ["uno", "dos"]


def test_search_returns_empty_list_without_crop_tag_matches() -> None:
    fragments = [_fragment_model(uuid4(), uuid4(), "maiz", ["maiz"], [1.0, 0.0])]

    assert rank_fragment_models(fragments, [1.0, 0.0], ["cacao"], max_results=5) == []


def test_document_search_service_uses_fake_provider_and_repository() -> None:
    provider = FakeEmbeddingProvider({"consulta cacao": [1.0, 0.0]})
    repository = FakeSearchRepository(
        [
            _fragment_model(uuid4(), uuid4(), "fragmento cacao", ["cacao"], [1.0, 0.0]),
            _fragment_model(uuid4(), uuid4(), "fragmento bajo", ["cacao"], [0.0, 1.0]),
        ]
    )
    service = DocumentSearchService(provider, repository)

    results = service.search(SearchDocumentFragmentsQuery("consulta cacao", ["cacao"], max_results=1))

    assert provider.calls == ["consulta cacao"]
    assert len(results) == 1
    assert results[0].text == "fragmento cacao"
    assert repository.last_query_embedding == [1.0, 0.0]


def test_no_external_provider_is_called_by_tests() -> None:
    provider = FakeEmbeddingProvider({"texto": [0.1, 0.2]})

    assert provider.generate_embedding("texto") == [0.1, 0.2]
    assert provider.external_calls == 0


def test_cosine_similarity_validates_dimensions() -> None:
    with pytest.raises(ValueError, match="same non-zero dimension"):
        cosine_similarity([1.0, 0.0], [1.0])


def test_domain_without_forbidden_imports_and_orm_stays_aligned_with_migration() -> None:
    migration_text = MIGRATION.read_text(encoding="utf-8")
    forbidden_prefixes = (
        "sqlalchemy",
        "fastapi",
        "via.bounded_contexts.document_management.infrastructure",
        "via.bounded_contexts.document_management.interfaces",
        "via.bounded_contexts.recommendation",
    )
    offenders: list[str] = []
    for path in DOMAIN.rglob("*.py"):
        for imported_name in _imports_from(path):
            if any(imported_name == prefix or imported_name.startswith(prefix + ".") for prefix in forbidden_prefixes):
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {imported_name}")

    fragment_columns = set(DocumentFragmentModel.__table__.columns.keys())
    assert offenders == []
    assert DocumentFragmentModel.__table__.schema == DOCUMENTAL_SCHEMA
    assert fragment_columns == {
        "id",
        "document_id",
        "text",
        "page_ref",
        "crop_tags",
        "token_count",
        "embedding",
        "created_at",
    }
    assert isinstance(DocumentFragmentModel.__table__.columns["embedding"].type, Vector)
    assert "embedding VECTOR(1536)" in migration_text


class FakeEmbeddingProvider:
    """Deterministic embedding provider that never calls external services."""

    def __init__(self, embeddings: dict[str, list[float]]) -> None:
        """Create the fake with text-to-vector mappings."""

        self._embeddings = embeddings
        self.calls: list[str] = []
        self.external_calls = 0

    def generate_embedding(self, text: str) -> list[float]:
        """Return the configured embedding for text."""

        self.calls.append(text)
        return list(self._embeddings[text])


class FakeEmbeddingRepository:
    """Fake repository for embedding assignment tests."""

    def __init__(self, fragments: list[EmbeddableFragment]) -> None:
        """Create the fake with stored fragments."""

        self.fragments = fragments
        self.saved_embeddings: dict[UUID, list[float]] = {}

    def get_fragments_for_embedding(self, fragment_ids: list[UUID] | None = None) -> list[EmbeddableFragment]:
        """Return fragments, optionally filtered by id."""

        if fragment_ids is None:
            return self.fragments
        selected = set(fragment_ids)
        return [fragment for fragment in self.fragments if fragment.id in selected]

    def save_fragment_embedding(self, fragment_id: UUID, embedding: list[float]) -> None:
        """Record the saved embedding."""

        self.saved_embeddings[fragment_id] = embedding


class FakeSearchRepository:
    """Fake search repository that ranks in memory."""

    def __init__(self, fragments: list[DocumentFragmentModel]) -> None:
        """Create the fake repository with document fragments."""

        self._fragments = fragments
        self.last_query_embedding: list[float] | None = None

    def search_fragments(self, query_embedding: list[float], crop_tags: list[str], max_results: int):
        """Rank fragments by fake similarity."""

        self.last_query_embedding = query_embedding
        return rank_fragment_models(self._fragments, query_embedding, crop_tags, max_results)


class FakeSession:
    """Small session fake for repository tests."""

    def __init__(self, stored: dict[UUID, DocumentFragmentModel] | None = None) -> None:
        """Create a fake session with optional stored fragments."""

        self.added: list[object] = []
        self.stored = stored or {}
        self.committed = False

    def add(self, model: object) -> None:
        """Record models scheduled for persistence."""

        self.added.append(model)

    def get(self, model_class: object, identity: UUID) -> object | None:
        """Return a stored model by identity."""

        return self.stored.get(identity)


def _fragment_model(
    fragment_id: UUID,
    document_id: UUID,
    text: str,
    crop_tags: list[str],
    embedding: list[float] | None,
    page_ref: int | None = None,
) -> DocumentFragmentModel:
    return DocumentFragmentModel(
        id=fragment_id,
        document_id=document_id,
        text=text,
        page_ref=page_ref,
        crop_tags=crop_tags,
        token_count=10,
        embedding=embedding,
    )


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
