"""Unit tests for Document Management 9A base."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from via.bounded_contexts.document_management.application.command_service import (
    DocumentCommandService,
    RegisterDocumentCommand,
    RegisterFragmentCommand,
)
from via.bounded_contexts.document_management.domain.document import TechnicalDocument
from via.bounded_contexts.document_management.domain.value_objects import DocumentDomainError, DocumentStatus
from via.bounded_contexts.document_management.infrastructure.document_repository import (
    SQLAlchemyDocumentRepository,
    document_from_model,
)
from via.bounded_contexts.document_management.infrastructure.orm_models import DocumentFragmentModel, DocumentModel
from via.shared.database.base import DOCUMENTAL_SCHEMA
from via.shared.database.types import Vector


ROOT = Path(__file__).resolve().parents[3]
DOMAIN = ROOT / "via" / "bounded_contexts" / "document_management" / "domain"
MIGRATION = ROOT / "migrations" / "versions" / "20260614_0002_initial_tables.py"


def test_create_valid_technical_document() -> None:
    document = TechnicalDocument.create(
        title="Manual tecnico cacao",
        format="PDF",
        crop_tags=["cacao"],
        size_bytes=1024,
    )

    assert document.title == "Manual tecnico cacao"
    assert document.crop_tags == ["cacao"]
    assert document.status == DocumentStatus.ACTIVE


def test_reject_document_without_crop_tags() -> None:
    with pytest.raises(DocumentDomainError, match="crop tag"):
        TechnicalDocument.create(title="Manual", format="PDF", crop_tags=[], size_bytes=1024)


def test_create_fragments_associated_to_document_and_preserve_traceability() -> None:
    document = TechnicalDocument.create("Manual", "TXT", ["cacao"], 256)

    first = document.add_fragment("contenido tecnico", page_ref=7, crop_tags=["cacao"], token_count=42)
    second = document.add_fragment("otro contenido", page_ref=None, crop_tags=["cacao", "maiz"], token_count=12)

    assert first.document_id == document.id
    assert first.chunk_index == 0
    assert first.page_ref == 7
    assert first.crop_tags == ["cacao"]
    assert first.token_count == 42
    assert first.embedding is None
    assert second.chunk_index == 1
    assert second.crop_tags == ["cacao", "maiz"]


def test_reject_fragment_without_text_or_crop_tags() -> None:
    document = TechnicalDocument.create("Manual", "PDF", ["cacao"], 1024)

    with pytest.raises(DocumentDomainError, match="fragment text"):
        document.add_fragment("", page_ref=1, crop_tags=["cacao"], token_count=10)
    with pytest.raises(DocumentDomainError, match="crop tag"):
        document.add_fragment("contenido", page_ref=1, crop_tags=[], token_count=10)


def test_application_service_registers_document_and_fragments() -> None:
    repository = FakeDocumentRepository()
    service = DocumentCommandService(repository)
    command = RegisterDocumentCommand(
        title="Ficha tecnica",
        format="PDF",
        crop_tags=["cacao"],
        size_bytes=2048,
        fragments=[RegisterFragmentCommand(text="fragmento", page_ref=3, crop_tags=["cacao"], token_count=20)],
    )

    document = service.register_document(command)

    assert repository.saved == [document]
    assert document.fragments[0].page_ref == 3
    assert document.fragments[0].token_count == 20


def test_repository_saves_document_and_fragments_in_documental_schema() -> None:
    session = FakeSession()
    document = TechnicalDocument.create("Manual", "PDF", ["cacao"], 1024)
    document.add_fragment("fragmento trazable", page_ref=2, crop_tags=["cacao"], token_count=30)

    SQLAlchemyDocumentRepository(session).save(document)

    models = session.added
    assert isinstance(models[0], DocumentModel)
    assert isinstance(models[1], DocumentFragmentModel)
    assert DocumentModel.__table__.schema == DOCUMENTAL_SCHEMA
    assert DocumentFragmentModel.__table__.schema == DOCUMENTAL_SCHEMA
    assert models[0].crop_tags == ["cacao"]
    assert models[1].document_id == document.id
    assert models[1].page_ref == 2
    assert models[1].crop_tags == ["cacao"]
    assert models[1].token_count == 30
    assert models[1].embedding is None


def test_document_mapping_preserves_existing_columns_without_embedding() -> None:
    document = TechnicalDocument.create("Manual", "PDF", ["cacao"], 1024)
    fragment = document.add_fragment("fragmento", page_ref=1, crop_tags=["cacao"], token_count=15)
    doc_model = DocumentModel(
        id=document.id,
        title=document.title,
        format=document.format.value,
        crop_tags=document.crop_tags,
        size_bytes=document.size_bytes,
        status=document.status.value,
    )
    fragment_model = DocumentFragmentModel(
        id=fragment.id,
        document_id=document.id,
        text=fragment.text,
        page_ref=fragment.page_ref,
        crop_tags=fragment.crop_tags,
        token_count=fragment.token_count,
        embedding=None,
    )

    mapped = document_from_model(doc_model, [fragment_model])

    assert mapped.title == "Manual"
    assert mapped.fragments[0].page_ref == 1
    assert mapped.fragments[0].embedding is None


def test_orm_matches_initial_migration_documental_columns() -> None:
    migration_text = MIGRATION.read_text(encoding="utf-8")
    document_columns = set(DocumentModel.__table__.columns.keys())
    fragment_columns = set(DocumentFragmentModel.__table__.columns.keys())

    assert document_columns == {"id", "title", "format", "crop_tags", "size_bytes", "uploaded_at", "status"}
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
    assert "CREATE TABLE documental.documents" in migration_text
    assert "CREATE TABLE documental.document_fragments" in migration_text
    assert "source" not in document_columns
    assert "metadata" not in document_columns
    assert isinstance(DocumentFragmentModel.__table__.columns["embedding"].type, Vector)


def test_domain_does_not_import_forbidden_layers() -> None:
    offenders: list[str] = []
    forbidden_prefixes = (
        "sqlalchemy",
        "fastapi",
        "via.bounded_contexts.document_management.infrastructure",
        "via.bounded_contexts.document_management.interfaces",
        "via.bounded_contexts.iam",
        "via.bounded_contexts.parcel_management",
        "via.bounded_contexts.rulebook_management",
        "via.bounded_contexts.agroenv_extraction",
        "via.bounded_contexts.viability_evaluation",
        "via.bounded_contexts.recommendation",
    )
    for path in DOMAIN.rglob("*.py"):
        for imported_name in _imports_from(path):
            if any(imported_name == prefix or imported_name.startswith(prefix + ".") for prefix in forbidden_prefixes):
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {imported_name}")

    assert offenders == []


class FakeDocumentRepository:
    """Repository fake for application service tests."""

    def __init__(self) -> None:
        """Create an empty fake repository."""

        self.saved: list[TechnicalDocument] = []

    def save(self, document: TechnicalDocument) -> None:
        """Record saved documents."""

        self.saved.append(document)


class FakeSession:
    """Session fake for repository tests."""

    def __init__(self) -> None:
        """Create an empty fake session."""

        self.added: list[object] = []

    def add(self, model: object) -> None:
        """Record added ORM models."""

        self.added.append(model)


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
