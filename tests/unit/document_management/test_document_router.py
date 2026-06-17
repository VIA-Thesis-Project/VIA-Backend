"""Interface tests for Document Management 9C API."""

from __future__ import annotations

import ast
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from via.bounded_contexts.document_management.application.command_service import DocumentCommandService
from via.bounded_contexts.document_management.application.ports import DocumentSearchResult
from via.bounded_contexts.document_management.application.query_service import (
    DocumentQueryService,
    DocumentSearchService,
)
from via.bounded_contexts.document_management.domain.document import TechnicalDocument
from via.bounded_contexts.document_management.interfaces import document_router
from via.bounded_contexts.document_management.interfaces.resources import DocumentCreateRequest
from via.bounded_contexts.iam.domain.role import Role
from via.bounded_contexts.iam.domain.user import User
from via.main import create_app


ROOT = Path(__file__).resolve().parents[3]
DOMAIN = ROOT / "via" / "bounded_contexts" / "document_management" / "domain"


def test_register_valid_document_with_fragments() -> None:
    store = InMemoryDocumentStore()
    user = _admin_user()

    response = document_router.create_document(
        DocumentCreateRequest(
            title="Manual cacao",
            format="PDF",
            crop_tags=["cacao"],
            size_bytes=1024,
            fragments=[
                {"text": "manejo tecnico", "page_ref": 2, "crop_tags": ["cacao"], "token_count": 20}
            ],
        ),
        current_user=user,
        command_service=DocumentCommandService(store),
    )

    assert response.title == "Manual cacao"
    assert response.fragments[0].text == "manejo tecnico"
    assert response.fragments[0].page_ref == 2


def test_reject_document_without_crop_tags() -> None:
    with pytest.raises(ValidationError):
        DocumentCreateRequest(title="Manual", format="PDF", crop_tags=[], size_bytes=1024, fragments=[])


def test_reject_fragment_without_text() -> None:
    with pytest.raises(HTTPException) as exc_info:
        document_router.create_document(
            DocumentCreateRequest(
                title="Manual",
                format="PDF",
                crop_tags=["cacao"],
                size_bytes=1024,
                fragments=[{"text": "", "page_ref": 1, "crop_tags": ["cacao"], "token_count": 10}],
            ),
            current_user=_admin_user(),
            command_service=DocumentCommandService(InMemoryDocumentStore()),
        )

    assert exc_info.value.status_code == 422
    assert "fragment text" in exc_info.value.detail


def test_get_registered_document() -> None:
    store = InMemoryDocumentStore()
    document = _stored_document(store)

    response = document_router.get_document(
        document.id,
        current_user=_admin_user(),
        query_service=DocumentQueryService(store),
    )

    assert response.id == document.id
    assert response.crop_tags == ["cacao"]


def test_list_document_fragments() -> None:
    store = InMemoryDocumentStore()
    document = _stored_document(store)

    response = document_router.list_document_fragments(
        document.id,
        current_user=_admin_user(),
        query_service=DocumentQueryService(store),
    )

    assert len(response) == 1
    assert response[0].document_id == document.id
    assert response[0].text == "fragmento cacao"


def test_search_fragments_by_crop_and_limit_results() -> None:
    store = InMemoryDocumentStore()
    document = _stored_document(store)
    second = document.add_fragment("fragmento secundario", page_ref=5, crop_tags=["cacao"], token_count=11)
    store.search_results = [
        DocumentSearchResult(second.id, document.id, second.page_ref, second.text, second.crop_tags, 0.7),
        DocumentSearchResult(document.fragments[0].id, document.id, 1, "fragmento cacao", ["cacao"], 0.9),
    ]
    provider = FakeEmbeddingProvider()

    response = document_router.search_fragments(
        crop_tag="cacao",
        query="riego",
        limit=1,
        min_score=None,
        current_user=_admin_user(),
        search_service=DocumentSearchService(provider, store),
    )

    assert len(response) == 1
    assert response[0].score == 0.9
    assert response[0].document_id == document.id
    assert response[0].text == "fragmento cacao"
    assert provider.calls == ["riego"]
    assert provider.external_calls == 0


def test_document_router_is_registered_in_main_app() -> None:
    paths = {route.path for route in create_app().routes}

    assert "/documentos" in paths
    assert "/documentos/fragmentos/buscar" in paths
    assert "/documentos/{document_id}" in paths
    assert "/documentos/{document_id}/fragmentos" in paths


def test_domain_without_forbidden_imports() -> None:
    forbidden_prefixes = (
        "sqlalchemy",
        "fastapi",
        "via.bounded_contexts.document_management.infrastructure",
        "via.bounded_contexts.document_management.interfaces",
        "via.bounded_contexts.recommendation",
        "via.bounded_contexts.viability_evaluation",
        "via.bounded_contexts.agroenv_extraction",
    )
    offenders: list[str] = []
    for path in DOMAIN.rglob("*.py"):
        for imported_name in _imports_from(path):
            if any(imported_name == prefix or imported_name.startswith(prefix + ".") for prefix in forbidden_prefixes):
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {imported_name}")

    assert offenders == []


def test_only_main_registers_document_router_outside_document_management() -> None:
    main_text = (ROOT / "via" / "main.py").read_text(encoding="utf-8")

    assert "document_management.interfaces.document_router" in main_text
    assert "recommendation.interfaces.recommendation_router" in main_text


class InMemoryDocumentStore:
    """Small in-memory port implementation for router tests."""

    def __init__(self) -> None:
        """Create an empty document store."""

        self.documents: dict[UUID, TechnicalDocument] = {}
        self.search_results: list[DocumentSearchResult] = []

    def save(self, document: TechnicalDocument) -> None:
        """Persist a document in memory."""

        self.documents[document.id] = document

    def get_document(self, document_id: UUID) -> TechnicalDocument | None:
        """Return one document."""

        return self.documents.get(document_id)

    def list_fragments(self, document_id: UUID):
        """Return fragments for one document."""

        document = self.documents[document_id]
        return document.fragments

    def search_fragments(self, query_embedding: list[float], crop_tags: list[str], max_results: int):
        """Return configured search results ordered and limited."""

        tags = {tag.lower() for tag in crop_tags}
        results = [result for result in self.search_results if tags.intersection({tag.lower() for tag in result.crop_tags})]
        results.sort(key=lambda result: -result.score)
        return results[:max_results]


class FakeEmbeddingProvider:
    """Fake provider used by router tests."""

    def __init__(self) -> None:
        """Create a fake provider with no external calls."""

        self.calls: list[str] = []
        self.external_calls = 0

    def generate_embedding(self, text: str) -> list[float]:
        """Return a deterministic embedding."""

        self.calls.append(text)
        return [1.0, 0.0]


def _admin_user() -> User:
    return User(id=uuid4(), email="admin@example.com", hashed_password="hash", role=Role.ADMINISTRADOR)


def _stored_document(store: InMemoryDocumentStore) -> TechnicalDocument:
    document = TechnicalDocument.create("Manual cacao", "PDF", ["cacao"], 1024)
    document.add_fragment("fragmento cacao", page_ref=1, crop_tags=["cacao"], token_count=10)
    store.save(document)
    return document


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
