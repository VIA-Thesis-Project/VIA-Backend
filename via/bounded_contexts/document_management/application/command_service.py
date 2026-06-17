"""Application service for registering technical documents."""

from __future__ import annotations

from dataclasses import dataclass, field

from via.bounded_contexts.document_management.application.ports import IDocumentRepository
from via.bounded_contexts.document_management.domain.document import TechnicalDocument


@dataclass(frozen=True)
class RegisterFragmentCommand:
    """Fragment payload supplied by a caller after external parsing/chunking."""

    text: str
    page_ref: int | None
    crop_tags: list[str]
    token_count: int


@dataclass(frozen=True)
class RegisterDocumentCommand:
    """Command to register a technical document and its fragments."""

    title: str
    format: str
    crop_tags: list[str]
    size_bytes: int
    fragments: list[RegisterFragmentCommand] = field(default_factory=list)


class DocumentCommandService:
    """Register technical documents without later-stage adapters or endpoints."""

    def __init__(self, repository: IDocumentRepository) -> None:
        """Create the service with a document repository port."""

        self._repository = repository

    def register_document(self, command: RegisterDocumentCommand) -> TechnicalDocument:
        """Validate and persist a technical document with supplied fragments."""

        document = TechnicalDocument.create(
            title=command.title,
            format=command.format,
            crop_tags=command.crop_tags,
            size_bytes=command.size_bytes,
        )
        for fragment in command.fragments:
            document.add_fragment(
                text=fragment.text,
                page_ref=fragment.page_ref,
                crop_tags=fragment.crop_tags,
                token_count=fragment.token_count,
            )
        self._repository.save(document)
        return document
