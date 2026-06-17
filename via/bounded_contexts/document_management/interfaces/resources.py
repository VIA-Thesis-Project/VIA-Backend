"""HTTP resources for Document Management."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class DocumentFragmentCreateRequest(BaseModel):
    """Structured fragment supplied in JSON when registering a document."""

    text: str
    page_ref: int | None = None
    crop_tags: list[str] = Field(min_length=1)
    token_count: int = Field(gt=0)


class DocumentCreateRequest(BaseModel):
    """Structured request to register a technical document."""

    title: str
    format: str
    crop_tags: list[str] = Field(min_length=1)
    size_bytes: int = Field(gt=0)
    fragments: list[DocumentFragmentCreateRequest] = Field(default_factory=list)


class DocumentFragmentResponse(BaseModel):
    """Response for a stored technical document fragment."""

    id: UUID
    document_id: UUID
    text: str
    page_ref: int | None
    crop_tags: list[str]
    token_count: int


class DocumentResponse(BaseModel):
    """Response for a stored technical document."""

    id: UUID
    title: str
    format: str
    crop_tags: list[str]
    size_bytes: int
    status: str
    fragments: list[DocumentFragmentResponse] = Field(default_factory=list)


class DocumentFragmentSearchResponse(BaseModel):
    """Search result for a relevant technical fragment."""

    document_id: UUID
    fragment_id: UUID
    text: str
    page_ref: int | None
    crop_tags: list[str]
    score: float
