"""Pydantic response schemas for recommendation API endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class EvidenceResponse(BaseModel):
    """Documentary evidence fragment referenced by a recommendation."""

    fragment_id: UUID
    document_id: UUID | None = None
    text: str | None = None
    crop_tags: list[str] = Field(default_factory=list)
    page_ref: int | None = None
    score: float | None = None
    source_filename: str | None = None
    source_file_id: str | None = None


class SectionResponse(BaseModel):
    """Structural section of a recommendation text."""

    section_type: str
    title: str
    content: str


class RecommendationResponse(BaseModel):
    """Persisted recommendation for one crop candidate."""

    recommendation_id: UUID
    evaluation_id: UUID
    parcel_id: UUID | None
    crop_id: str
    status: str
    title: str
    sections: list[SectionResponse]
    evidence: list[EvidenceResponse]
    structured_output: dict = Field(default_factory=dict)
    gap_recommendations: list[dict] = Field(default_factory=list)
    created_at: datetime
    provider: str
