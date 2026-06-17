"""Technical document fragment entity."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from uuid import UUID, uuid4

from via.bounded_contexts.document_management.domain.value_objects import DocumentDomainError, ensure_non_empty_text, normalize_crop_tags


@dataclass(frozen=True)
class DocumentFragment:
    """A traceable text fragment associated with a technical document."""

    document_id: UUID
    text: str
    page_ref: int | None
    crop_tags: list[str]
    token_count: int
    chunk_index: int
    id: UUID = field(default_factory=uuid4)
    embedding: object | None = None

    def __post_init__(self) -> None:
        """Validate fragment invariants."""

        object.__setattr__(self, "text", ensure_non_empty_text(self.text, "fragment text"))
        object.__setattr__(self, "crop_tags", normalize_crop_tags(self.crop_tags))
        if self.token_count <= 0:
            raise DocumentDomainError("fragment token_count must be positive")
        if self.chunk_index < 0:
            raise DocumentDomainError("fragment chunk_index must be >= 0")

    def with_embedding(self, embedding: Sequence[float]) -> DocumentFragment:
        """Return a copy of the fragment with an assigned embedding vector."""

        values = [float(value) for value in embedding]
        if not values:
            raise DocumentDomainError("fragment embedding must not be empty")
        return replace(self, embedding=values)
