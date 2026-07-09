"""Application ports for viability-evaluation anti-corruption layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Protocol
from uuid import UUID

from via.bounded_contexts.viability_evaluation.domain.evaluation import Evaluation


# ─── Read models for query service ────────────────────────────────────────────


@dataclass(frozen=True)
class SagaSnapshot:
    """Lightweight saga status summary returned by IEvaluationQueryPort."""

    status: str
    last_transition: datetime | None
    failure_reason: str | None


@dataclass(frozen=True)
class GapReadModel:
    """Agronomic gap for one criterion and phase (read from persistence)."""

    criterion_id: str
    phase_id: str
    most_limiting_period: str
    observed_value: float
    optimal_limit: float
    gap_value: float
    membership: float | None = None
    criterion_name: str | None = None
    criterion_label: str | None = None
    criterion_group: str | None = None
    phase_name: str | None = None
    unit: str | None = None
    intervention_class: str | None = None


@dataclass(frozen=True)
class LimitingFactorReadModel:
    """Critical limiting factor trace (read from persistence)."""

    criterion_id: str
    phase_id: str
    policy: str
    penalty_factor: float | None
    observed_value: float
    optimal_limit: float
    membership: float
    doc_source: str | None
    criterion_name: str | None = None
    criterion_label: str | None = None
    criterion_group: str | None = None
    phase_name: str | None = None
    unit: str | None = None
    intervention_class: str | None = None


@dataclass
class CropResultReadModel:
    """Persisted crop-level MCDA result for one evaluation."""

    crop_id: str
    score: float | None
    rank_position: int | None
    calc_condition: str
    viability_category: str
    gaps: list[GapReadModel] = field(default_factory=list)
    limiting_factors: list[LimitingFactorReadModel] = field(default_factory=list)
    missing_criteria: list[str] = field(default_factory=list)
    unrecognized_variables: list[str] = field(default_factory=list)


@dataclass
class EvaluationStatusReadModel:
    """Snapshot of current saga lifecycle state."""

    evaluation_id: UUID
    status: str
    current_phase: str
    last_transition: datetime | None
    failure_reason: str | None


@dataclass
class EvaluationMcdaResultReadModel:
    """MCDA results read model — populated when evaluation is complete."""

    evaluation_id: UUID
    status: str
    results: list[CropResultReadModel] = field(default_factory=list)
    failure_reason: str | None = None


@dataclass(frozen=True)
class AgroenvVariableReadModel:
    """Persisted agroenvironmental variable with rulebook display metadata."""

    variable_name: str
    criterion_id: str
    crop_id: str
    phase_id: str
    period_key: str
    value: float | None
    unit: str
    status: str
    dataset_key: str
    band: str
    source: str
    criterion_name: str | None = None
    criterion_label: str | None = None
    criterion_group: str | None = None
    phase_name: str | None = None
    intervention_class: str | None = None


@dataclass(frozen=True)
class AgroenvVectorReadModel:
    """Persisted agroenvironmental vector exposed by the query API."""

    evaluation_id: UUID
    parcel_id: UUID
    variables: list[AgroenvVariableReadModel] = field(default_factory=list)


@dataclass(frozen=True)
class EvaluationCriterionSpec:
    """Evaluation-facing criterion data translated from the active rulebook."""

    criterion_id: str
    crop_id: str
    phase_id: str
    variable_name: str
    w_ahp: float
    phase_weight: float
    temporal_periods: list[dict[str, Any]]
    membership_fn: dict[str, Any]
    critical_policy: str
    penalty_factor: float | None
    doc_source: str | None = None


@dataclass(frozen=True)
class RulebookEvaluationData:
    """Rulebook data needed by evaluation, independent from rulebook internals."""

    crop_id: str
    rulebook_id: UUID
    version: int
    criteria: list[EvaluationCriterionSpec] = field(default_factory=list)


@dataclass(frozen=True)
class AgroenvVariableData:
    """Evaluation-facing variable value translated from an agroenvironmental vector."""

    variable_name: str
    criterion_id: str
    crop_id: str
    phase_id: str
    period_key: str
    value: float | None
    unit: str
    status: str
    dataset_key: str
    band: str
    source: str


@dataclass(frozen=True)
class AgroenvVectorData:
    """Agroenvironmental vector data needed by evaluation."""

    evaluation_id: UUID
    parcel_id: UUID
    variables: list[AgroenvVariableData] = field(default_factory=list)


class IRulebookEvaluationPort(Protocol):
    """Port for obtaining active rulebook data in evaluation terms."""

    def get_active_rulebook(self, crop_id: str) -> RulebookEvaluationData:
        """Return the active evaluative rulebook data for a crop."""


class IAgroenvVectorPort(Protocol):
    """Port for obtaining generated agroenvironmental vectors in evaluation terms."""

    def get_vector_for_evaluation(self, evaluation_id: UUID) -> AgroenvVectorData:
        """Return the generated vector associated with an evaluation."""


class IEvaluationRepository(Protocol):
    """Port for persisting computed evaluation results."""

    def save(self, evaluation: Evaluation, rulebook_versions: Mapping[str, int]) -> None:
        """Persist evaluation crop results and traceability without recalculating MCDA."""


class IEvaluationQueryPort(Protocol):
    """Port for reading evaluation lifecycle state and persisted MCDA results.

    Implementations live in infrastructure and own all ORM/SQL concerns.
    The query service depends on this port, never on ORM models directly.
    """

    def find_saga_snapshot(self, evaluation_id: UUID) -> SagaSnapshot | None:
        """Return status, last transition and failure reason, or None when not found."""

    def find_crop_results(self, evaluation_id: UUID) -> list[CropResultReadModel]:
        """Return all persisted crop results with gaps and limiting factors."""

    def find_agroenv_vector(self, evaluation_id: UUID) -> AgroenvVectorReadModel | None:
        """Return the persisted agroenvironmental vector, or None when absent."""
