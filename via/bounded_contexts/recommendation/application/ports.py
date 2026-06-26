"""Application ports for Recommendation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from via.bounded_contexts.recommendation.domain.recommendation import Recommendation


@dataclass(frozen=True)
class GapData:
    """Agronomic gap data already produced by Evaluation."""

    criterion_id: str
    phase_id: str
    most_limiting_period: str
    observed_value: float
    optimal_limit: float
    gap_value: float
    criterion_name: str | None = None
    criterion_label: str | None = None
    criterion_group: str | None = None
    unit: str | None = None
    phase_name: str | None = None
    gap_direction: str | None = None
    severity: str | None = None
    recommendation_topic: str | None = None


@dataclass(frozen=True)
class LimitingFactorData:
    """Limiting factor data already produced by Evaluation."""

    criterion_id: str
    phase_id: str
    policy: str
    penalty_factor: float | None
    observed_value: float
    optimal_limit: float
    membership: float
    doc_source: str | None = None
    criterion_name: str | None = None
    criterion_label: str | None = None
    criterion_group: str | None = None
    unit: str | None = None
    phase_name: str | None = None
    gap_direction: str | None = None
    severity: str | None = None
    recommendation_topic: str | None = None


@dataclass(frozen=True)
class CropEvaluationResultData:
    """Crop result data already produced by Evaluation."""

    crop_id: str
    score: float | None
    rank_position: int | None
    calc_condition: str
    viability_category: str
    gaps: list[GapData] = field(default_factory=list)
    limiting_factors: list[LimitingFactorData] = field(default_factory=list)


@dataclass(frozen=True)
class EvaluationRecommendationData:
    """Evaluation result data needed for recommendation drafting."""

    evaluation_id: UUID
    crop_results: list[CropEvaluationResultData] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceData:
    """Documentary fragment data returned by the document search port."""

    fragment_id: UUID
    document_id: UUID
    text: str
    crop_tags: list[str]
    page_ref: int | None = None
    score: float | None = None
    source_filename: str | None = None
    source_file_id: str | None = None


@dataclass(frozen=True)
class EvidenceReadModel:
    """Persisted evidence data referenced by a recommendation response."""

    fragment_id: UUID
    document_id: UUID | None = None
    text: str | None = None
    crop_tags: list[str] = field(default_factory=list)
    page_ref: int | None = None
    score: float | None = None
    source_filename: str | None = None
    source_file_id: str | None = None


@dataclass(frozen=True)
class RecommendationDraftContext:
    """Context sent to the drafting provider."""

    evaluation_id: UUID
    crop_result: CropEvaluationResultData
    evidence: list[EvidenceData]


class IEvaluationResultsPort(Protocol):
    """Port for reading already-computed evaluation results."""

    def get_results_for_recommendation(self, evaluation_id: UUID) -> EvaluationRecommendationData:
        """Return evaluation data for recommendation drafting."""


class IDocumentEvidencePort(Protocol):
    """Port for retrieving documentary evidence."""

    def search_evidence(self, crop_id: str, gaps: list[GapData], max_fragments: int) -> list[EvidenceData]:
        """Return relevant evidence for a crop and its existing gaps."""


class IRecommendationDraftingProvider(Protocol):
    """Port for drafting recommendation text."""

    def draft(self, context: RecommendationDraftContext) -> str:
        """Draft recommendation text from supplied context."""


class IRecommendationRepository(Protocol):
    """Persistence port for supported recommendations."""

    def save(self, recommendation: Recommendation) -> None:
        """Persist a recommendation without committing."""


# ─── Read models for query service ────────────────────────────────────────────


@dataclass(frozen=True)
class RecommendationReadModel:
    """Persisted recommendation data for read-only query endpoints."""

    recommendation_id: UUID
    evaluation_id: UUID
    parcel_id: UUID | None
    crop_id: str
    status: str
    title: str
    text: str
    evidence: list[EvidenceReadModel]
    created_at: datetime
    provider: str
    structured_output: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FinalRecommendationResult:
    """Result of a final-recommendation lookup that distinguishes missing evaluation."""

    evaluation_found: bool
    recommendation: RecommendationReadModel | None


class IRecommendationQueryPort(Protocol):
    """Port for reading persisted recommendations.

    Implementations live in infrastructure and own all ORM/SQL concerns.
    """

    def find_by_id(self, recommendation_id: UUID) -> RecommendationReadModel | None:
        """Return recommendation by its primary key, or None when not found."""

    def find_by_evaluation_id(self, evaluation_id: UUID) -> list[RecommendationReadModel]:
        """Return all recommendations for an evaluation (may be empty)."""

    def find_final_for_evaluation(self, evaluation_id: UUID) -> FinalRecommendationResult:
        """Return whether the evaluation exists and its most recent recommendation."""
