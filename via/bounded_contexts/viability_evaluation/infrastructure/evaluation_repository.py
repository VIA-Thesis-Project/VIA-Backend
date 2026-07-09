"""SQLAlchemy repository for persisted viability evaluation results."""

from __future__ import annotations

import uuid
from decimal import Decimal
from numbers import Real
from typing import Mapping

from sqlalchemy.orm import Session

from via.bounded_contexts.viability_evaluation.domain.crop_result import CropResult
from via.bounded_contexts.viability_evaluation.domain.evaluation import Evaluation
from via.bounded_contexts.viability_evaluation.domain.value_objects import CalcCondition, ViabilityCategory
from via.bounded_contexts.viability_evaluation.infrastructure.orm_models import (
    AgronomyGapModel,
    EvaluationCriterionDetailModel,
    EvaluationResultModel,
    LimitingFactorModel,
)


class EvaluationRepository:
    """Persist evaluation results in the transactional schema."""

    def __init__(self, session: Session) -> None:
        """Create the repository with an active synchronous SQLAlchemy session."""

        self._session = session

    def save(self, evaluation: Evaluation, rulebook_versions: Mapping[str, int]) -> None:
        """Persist an evaluation aggregate and all crop-level traceability."""

        for crop_result in evaluation.crop_results:
            result_id = uuid.uuid4()
            result_model = self._to_result_model(evaluation, crop_result, result_id, rulebook_versions)
            self._session.add(result_model)
            # Flush result INSERT before children; cross-schema FK inserts are not
            # auto-ordered by SQLAlchemy's UoW without mapped relationships.
            self._session.flush()

            for detail in crop_result.criterion_details:
                self._session.add(
                    EvaluationCriterionDetailModel(
                        result_id=result_id,
                        criterion_id=detail.criterion_id,
                        memberships_by_period=dict(detail.memberships_by_period),
                        aggregated_by_phase=dict(detail.aggregated_by_phase),
                        aggregated_membership=_decimal(detail.aggregated_membership),
                        w_ahp=_decimal(detail.w_ahp),
                        w_entropy=_decimal(detail.w_entropy),
                        w_hybrid=_decimal(detail.w_hybrid),
                        entropy_series_used=detail.entropy_used,
                        entropy_fallback_reason=detail.entropy_fallback_reason,
                    )
                )

            for gap in crop_result.gaps:
                self._session.add(
                    AgronomyGapModel(
                        result_id=result_id,
                        criterion_id=gap.criterion_id,
                        phase_id=gap.phase_id,
                        most_limiting_period=gap.most_limiting_period,
                        observed_value=_decimal(gap.observed_value),
                        optimal_limit=_decimal(gap.optimal_limit),
                        gap_value=_decimal(gap.gap_value),
                        membership=_decimal(gap.membership),
                    )
                )

            for factor in crop_result.limiting_factors:
                self._session.add(
                    LimitingFactorModel(
                        result_id=result_id,
                        criterion_id=factor.criterion_id,
                        phase_id=factor.phase_id,
                        policy=factor.policy.value,
                        penalty_factor=_decimal(factor.penalty_factor),
                        observed_value=_decimal(factor.observed_value),
                        optimal_limit=_decimal(factor.optimal_limit),
                        membership=_decimal(factor.membership),
                        doc_source=factor.doc_source,
                    )
                )

    def _to_result_model(
        self,
        evaluation: Evaluation,
        crop_result: CropResult,
        result_id: uuid.UUID,
        rulebook_versions: Mapping[str, int],
    ) -> EvaluationResultModel:
        """Map a crop result to its ORM row without domain calculations."""

        return EvaluationResultModel(
            id=result_id,
            evaluation_id=evaluation.id,
            crop_id=crop_result.crop_id,
            score=_decimal(crop_result.score),
            calc_condition=_enum_value(crop_result.calc_condition),
            viability_category=_enum_value(crop_result.viability_category),
            rank_position=_rank_position(crop_result),
            rulebook_version=rulebook_versions[crop_result.crop_id],
            entropy_used=crop_result.entropy_series_sufficient,
        )


def _decimal(value: Real | None) -> Decimal | None:
    """Convert domain numeric values to Decimal for SQLAlchemy Numeric columns."""

    if value is None:
        return None
    return Decimal(str(value))


def _enum_value(value: CalcCondition | ViabilityCategory) -> str:
    """Return the persisted value for calculation and viability enums."""

    return value.value


def _rank_position(crop_result: CropResult) -> int | None:
    """Persist rank only for rankable crop results."""

    if crop_result.calc_condition is CalcCondition.NO_CONCLUYENTE:
        return None
    if crop_result.viability_category is ViabilityCategory.NO_VIABLE:
        return None
    return crop_result.rank_position
