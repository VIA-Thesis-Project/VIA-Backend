"""Pydantic response schemas for recommendation API endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class EvidenceResponse(BaseModel):
    """Documentary evidence fragment referenced by a recommendation."""

    fragment_id: UUID


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
    created_at: datetime
    provider: str
