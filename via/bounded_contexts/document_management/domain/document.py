"""Technical document aggregate."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from via.bounded_contexts.document_management.domain.fragment import DocumentFragment
from via.bounded_contexts.document_management.domain.value_objects import (
    DocumentDomainError,
    DocumentFormat,
    DocumentStatus,
    ensure_non_empty_text,
    normalize_crop_tags,
)


@dataclass
class TechnicalDocument:
    """Technical document aggregate persisted in the documental schema."""

    title: str
    format: DocumentFormat
    crop_tags: list[str]
    size_bytes: int
    status: DocumentStatus = DocumentStatus.ACTIVE
    id: UUID = field(default_factory=uuid4)
    fragments: list[DocumentFragment] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate document invariants."""

        self.title = ensure_non_empty_text(self.title, "document title")
        self.crop_tags = normalize_crop_tags(self.crop_tags)
        if self.size_bytes <= 0:
            raise DocumentDomainError("document size_bytes must be positive")
        self.format = DocumentFormat(self.format)
        self.status = DocumentStatus(self.status)

    @classmethod
    def create(
        cls,
        title: str,
        format: str | DocumentFormat,
        crop_tags: list[str],
        size_bytes: int,
        status: str | DocumentStatus = DocumentStatus.ACTIVE,
    ) -> "TechnicalDocument":
        """Create a validated technical document."""

        return cls(title=title, format=DocumentFormat(format), crop_tags=crop_tags, size_bytes=size_bytes, status=DocumentStatus(status))

    def add_fragment(self, text: str, page_ref: int | None, crop_tags: list[str], token_count: int) -> DocumentFragment:
        """Add a traceable fragment to the document."""

        fragment = DocumentFragment(
            document_id=self.id,
            text=text,
            page_ref=page_ref,
            crop_tags=crop_tags,
            token_count=token_count,
            chunk_index=len(self.fragments),
            embedding=None,
        )
        self.fragments.append(fragment)
        return fragment
