"""Session-managed bridge adapters connecting runtime ports to real DB implementations.

Each bridge opens its own session per call so it can be held as a singleton
by long-lived components (EvaluationProcessManager, ViabilityEvaluationCommandService,
RecommendationCommandService) that are instantiated once at startup.
"""

from __future__ import annotations

from typing import Any, Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from via.bounded_contexts.agroenv_extraction.infrastructure.orm_models import (
    AgroenvVariableEntryModel,
    AgroenvVectorModel,
)
from via.bounded_contexts.parcel_management.infrastructure.parcel_geometry_read_model import (
    ParcelGeometryReadModelAdapter,
)
from via.bounded_contexts.parcel_management.infrastructure.parcel_repository import SQLAlchemyParcelRepository
from via.bounded_contexts.recommendation.application.ports import (
    CropEvaluationResultData,
    EvaluationRecommendationData,
    GapData,
    LimitingFactorData,
)
from via.bounded_contexts.rulebook_management.application.query_service import RulebookQueryService
from via.bounded_contexts.rulebook_management.domain.rulebook import Rulebook
from via.bounded_contexts.rulebook_management.infrastructure.rulebook_repository import SqlAlchemyRulebookRepository
from via.bounded_contexts.viability_evaluation.application.ports import (
    AgroenvVariableData,
    AgroenvVectorData,
    EvaluationCriterionSpec,
    RulebookEvaluationData,
)
from via.bounded_contexts.viability_evaluation.infrastructure.evaluation_query_repository import EvaluationQueryRepository
from via.shared.orchestration.evaluation_process_manager.ports import (
    ParcelGeometrySnapshot,
    RequiredExtractionSpec,
)


# ─── IRulebookReadModelPort bridge ────────────────────────────────────────────


class SqlAlchemyRulebookReadModelBridge:
    """Implements IRulebookReadModelPort using SqlAlchemyRulebookRepository and RulebookQueryService.

    Opens a dedicated session per call to be safe as a long-lived singleton.
    """

    def __init__(self, session_factory: sessionmaker[Session] | Callable[[], Session]) -> None:
        """Create the bridge with a session factory."""

        self._session_factory = session_factory

    def get_required_extraction_spec(
        self,
        crop_candidates: list[str],
        temporal_window: dict[str, Any],
    ) -> RequiredExtractionSpec:
        """Return RequiredExtractionSpec by reading active rulebooks from DB."""

        session = self._session_factory()
        try:
            repo = SqlAlchemyRulebookRepository(session)
            service = RulebookQueryService(repo)
            return service.get_required_extraction_spec(crop_candidates, temporal_window)
        finally:
            session.close()


# ─── IParcelGeometryReadModelPort bridge ──────────────────────────────────────


class SqlAlchemyParcelGeometryBridge:
    """Implements IParcelGeometryReadModelPort using SQLAlchemyParcelRepository and ParcelGeometryReadModelAdapter.

    Opens a dedicated session per call to be safe as a long-lived singleton.
    """

    def __init__(self, session_factory: sessionmaker[Session] | Callable[[], Session]) -> None:
        """Create the bridge with a session factory."""

        self._session_factory = session_factory

    def get_parcel_geometry(self, parcel_id: UUID) -> ParcelGeometrySnapshot:
        """Return a GeoJSON geometry snapshot by reading the parcel from DB."""

        session = self._session_factory()
        try:
            repo = SQLAlchemyParcelRepository(session)
            adapter = ParcelGeometryReadModelAdapter(repo)
            return adapter.get_parcel_geometry(parcel_id)
        finally:
            session.close()


# ─── IRulebookEvaluationPort bridge ───────────────────────────────────────────


class SqlAlchemyRulebookEvaluationBridge:
    """Implements IRulebookEvaluationPort by reading the active rulebook from DB and converting to evaluation DTOs.

    Opens a dedicated session per call to be safe as a long-lived singleton.
    """

    def __init__(self, session_factory: sessionmaker[Session] | Callable[[], Session]) -> None:
        """Create the bridge with a session factory."""

        self._session_factory = session_factory

    def get_active_rulebook(self, crop_id: str) -> RulebookEvaluationData:
        """Return RulebookEvaluationData for the active rulebook of the given crop."""

        session = self._session_factory()
        try:
            repo = SqlAlchemyRulebookRepository(session)
            rulebook = repo.get_active_by_crop(crop_id)
            if rulebook is None:
                raise ValueError(f"No active rulebook found for crop: {crop_id}")
            return _rulebook_to_evaluation_data(rulebook)
        finally:
            session.close()


# ─── IAgroenvVectorPort bridge ────────────────────────────────────────────────


class SqlAlchemyAgroenvVectorBridge:
    """Implements IAgroenvVectorPort by querying AgroenvVectorModel and AgroenvVariableEntryModel.

    Opens a dedicated session per call to be safe as a long-lived singleton.
    """

    def __init__(self, session_factory: sessionmaker[Session] | Callable[[], Session]) -> None:
        """Create the bridge with a session factory."""

        self._session_factory = session_factory

    def get_vector_for_evaluation(self, evaluation_id: UUID) -> AgroenvVectorData:
        """Return AgroenvVectorData by reading the persisted vector for an evaluation."""

        session = self._session_factory()
        try:
            vector_model = session.execute(
                select(AgroenvVectorModel).where(AgroenvVectorModel.evaluation_id == evaluation_id)
            ).scalars().first()
            if vector_model is None:
                raise ValueError(f"No agroenv vector found for evaluation: {evaluation_id}")
            entry_models = session.execute(
                select(AgroenvVariableEntryModel).where(
                    AgroenvVariableEntryModel.vector_id == vector_model.id
                )
            ).scalars().all()
            variables = [
                AgroenvVariableData(
                    variable_name=e.variable_name,
                    criterion_id=e.criterion_id,
                    crop_id=e.crop_id,
                    phase_id=e.phase_id,
                    period_key=e.period_key,
                    value=float(e.value) if e.value is not None else None,
                    unit=e.unit,
                    status=e.status,
                    dataset_key=e.dataset_key,
                    band=e.band,
                    source=e.source,
                )
                for e in entry_models
            ]
            return AgroenvVectorData(
                evaluation_id=vector_model.evaluation_id,
                parcel_id=vector_model.parcel_id,
                variables=variables,
            )
        finally:
            session.close()


# ─── IEvaluationResultsPort bridge ────────────────────────────────────────────


class SqlAlchemyEvaluationResultsBridge:
    """Implements IEvaluationResultsPort by reading persisted crop results via EvaluationQueryRepository.

    Opens a dedicated session per call to be safe as a long-lived singleton.
    """

    def __init__(self, session_factory: sessionmaker[Session] | Callable[[], Session]) -> None:
        """Create the bridge with a session factory."""

        self._session_factory = session_factory

    def get_results_for_recommendation(self, evaluation_id: UUID) -> EvaluationRecommendationData:
        """Return evaluation result data for recommendation drafting."""

        session = self._session_factory()
        try:
            repo = EvaluationQueryRepository(session)
            crop_results = repo.find_crop_results(evaluation_id)
            return EvaluationRecommendationData(
                evaluation_id=evaluation_id,
                crop_results=[_crop_result_to_recommendation_data(r) for r in crop_results],
            )
        finally:
            session.close()


# ─── Conversion helpers ────────────────────────────────────────────────────────


def _rulebook_to_evaluation_data(rulebook: Rulebook) -> RulebookEvaluationData:
    """Convert a Rulebook domain aggregate directly to evaluation-facing DTOs."""

    criteria_by_id = {c.id: c for c in rulebook.criteria}
    criteria: list[EvaluationCriterionSpec] = []
    for req in rulebook.phase_requirements:
        criterion = criteria_by_id.get(req.criterion_id)
        if criterion is None:
            continue
        criteria.append(
            EvaluationCriterionSpec(
                criterion_id=str(criterion.id),
                crop_id=rulebook.crop_id,
                phase_id=str(req.phase_id),
                variable_name=req.extraction_binding.variable_name,
                w_ahp=criterion.ahp_weight,
                phase_weight=float(req.phase_weight),
                temporal_periods=req.temporal_period_payload(),
                membership_fn=req.membership_fn.to_mapping(),
                critical_policy=criterion.critical_policy.value if criterion.critical_policy is not None else "",
                penalty_factor=criterion.penalty_factor,
                doc_source=criterion.doc_source,
            )
        )
    return RulebookEvaluationData(
        crop_id=rulebook.crop_id,
        rulebook_id=rulebook.id,
        version=rulebook.version,
        criteria=criteria,
    )


def _crop_result_to_recommendation_data(result: Any) -> CropEvaluationResultData:
    """Map a CropResultReadModel to a CropEvaluationResultData for recommendation drafting."""

    return CropEvaluationResultData(
        crop_id=result.crop_id,
        score=result.score,
        rank_position=result.rank_position,
        calc_condition=result.calc_condition,
        viability_category=result.viability_category,
        gaps=[
            GapData(
                criterion_id=g.criterion_id,
                phase_id=g.phase_id,
                most_limiting_period=g.most_limiting_period,
                observed_value=g.observed_value,
                optimal_limit=g.optimal_limit,
                gap_value=g.gap_value,
            )
            for g in result.gaps
        ],
        limiting_factors=[
            LimitingFactorData(
                criterion_id=lf.criterion_id,
                phase_id=lf.phase_id,
                policy=lf.policy,
                penalty_factor=lf.penalty_factor,
                observed_value=lf.observed_value,
                optimal_limit=lf.optimal_limit,
                membership=lf.membership,
                doc_source=lf.doc_source,
            )
            for lf in result.limiting_factors
        ],
    )
