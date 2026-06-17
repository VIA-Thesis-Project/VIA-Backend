"""SQLAlchemy repository for Rulebook Management."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from via.bounded_contexts.rulebook_management.application.ports import IRulebookRepository
from via.bounded_contexts.rulebook_management.domain.criterion import Criterion
from via.bounded_contexts.rulebook_management.domain.phase_requirement import ExtractionBinding, PhaseRequirement
from via.bounded_contexts.rulebook_management.domain.phenological_phase import PhenologicalPhase
from via.bounded_contexts.rulebook_management.domain.rulebook import Rulebook
from via.bounded_contexts.rulebook_management.domain.value_objects import (
    CriticalPolicy,
    MembershipFunction,
    RulebookStatus,
    TemporalPeriod,
)
from via.bounded_contexts.rulebook_management.infrastructure.orm_models import (
    CriterionModel,
    PhaseRequirementModel,
    RulebookModel,
    RulebookPhaseModel,
)


class SqlAlchemyRulebookRepository(IRulebookRepository):
    """Persist rulebooks using synchronous SQLAlchemy sessions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def next_version_for_crop(self, crop_id: str) -> int:
        """Return the next version number for a crop."""

        max_version = self._session.execute(
            select(func.max(RulebookModel.version)).where(RulebookModel.crop_id == crop_id)
        ).scalar_one_or_none()
        return int(max_version or 0) + 1

    def add(self, rulebook: Rulebook) -> None:
        """Persist a new rulebook aggregate.

        Insertion order matters: flush after the parent RulebookModel so the FK
        constraints on CriterionModel and RulebookPhaseModel are satisfied, then
        flush again before adding PhaseRequirementModel whose FKs point to both.
        """
        self._session.add(
            RulebookModel(
                id=rulebook.id,
                crop_id=rulebook.crop_id,
                version=rulebook.version,
                status=rulebook.status.value,
            )
        )
        # Parent must exist in the DB before FK-referencing children are inserted.
        self._session.flush()

        for criterion in rulebook.criteria:
            self._session.add(
                CriterionModel(
                    id=criterion.id,
                    rulebook_id=rulebook.id,
                    name=criterion.name,
                    is_critical=criterion.is_critical,
                    critical_policy=criterion.critical_policy.value if criterion.critical_policy else None,
                    penalty_factor=_decimal_or_none(criterion.penalty_factor),
                    ahp_weight=Decimal(str(criterion.ahp_weight)),
                    doc_source=criterion.doc_source,
                    technical_notes=criterion.technical_notes,
                )
            )
        for phase in rulebook.phases:
            self._session.add(
                RulebookPhaseModel(
                    id=phase.id,
                    rulebook_id=rulebook.id,
                    name=phase.name,
                    duration_days=phase.duration_days,
                    sequence_order=phase.sequence_order,
                )
            )
        # Criteria and phases must exist before PhaseRequirementModel references them.
        self._session.flush()

        for requirement in rulebook.phase_requirements:
            self._session.add(
                PhaseRequirementModel(
                    id=requirement.id,
                    criterion_id=requirement.criterion_id,
                    phase_id=requirement.phase_id,
                    membership_fn=requirement.membership_fn.to_mapping(),
                    phase_weight=Decimal(str(requirement.phase_weight)),
                    temporal_periods=requirement.temporal_period_payload(),
                    extraction_binding=requirement.extraction_binding.to_mapping(),
                )
            )

    def get_by_id(self, rulebook_id: UUID) -> Rulebook | None:
        """Return one rulebook by id or None."""

        model = self._session.get(RulebookModel, rulebook_id)
        if model is None:
            return None
        return self._to_domain(model)

    def get_active_by_crop(self, crop_id: str) -> Rulebook | None:
        """Return the active rulebook for one crop or None."""

        model = self._session.execute(
            select(RulebookModel).where(
                RulebookModel.crop_id == crop_id,
                RulebookModel.status == RulebookStatus.ACTIVE.value,
            )
        ).scalar_one_or_none()
        if model is None:
            return None
        return self._to_domain(model)

    def list_all(self) -> list[Rulebook]:
        """Return all rulebook versions ordered by crop and version."""

        models = self._session.execute(
            select(RulebookModel).order_by(RulebookModel.crop_id, RulebookModel.version)
        ).scalars()
        return [self._to_domain(model) for model in models]

    def deactivate_active_for_crop(self, crop_id: str) -> None:
        """Deactivate the current active version for a crop."""

        models = self._session.execute(
            select(RulebookModel).where(
                RulebookModel.crop_id == crop_id,
                RulebookModel.status == RulebookStatus.ACTIVE.value,
            )
        ).scalars()
        for model in models:
            model.status = RulebookStatus.INACTIVE.value

    def save(self, rulebook: Rulebook) -> None:
        """Persist changes to an existing rulebook aggregate."""

        model = self._session.get(RulebookModel, rulebook.id)
        if model is None:
            self.add(rulebook)
            return
        model.status = rulebook.status.value

    def _to_domain(self, model: RulebookModel) -> Rulebook:
        criteria = self._criteria_for(model.id)
        phases = self._phases_for(model.id)
        requirements = self._requirements_for(criteria, phases)
        return Rulebook(
            id=model.id,
            crop_id=model.crop_id,
            version=model.version,
            status=RulebookStatus(model.status),
            criteria=criteria,
            phases=phases,
            phase_requirements=requirements,
        )

    def _criteria_for(self, rulebook_id: UUID) -> list[Criterion]:
        models = self._session.execute(
            select(CriterionModel).where(CriterionModel.rulebook_id == rulebook_id)
        ).scalars()
        criteria: list[Criterion] = []
        for model in models:
            criteria.append(
                Criterion(
                    id=model.id,
                    name=model.name,
                    is_critical=model.is_critical,
                    critical_policy=CriticalPolicy(model.critical_policy) if model.critical_policy else None,
                    penalty_factor=_float_or_none(model.penalty_factor),
                    ahp_weight=float(model.ahp_weight),
                    doc_source=model.doc_source,
                    technical_notes=model.technical_notes,
                )
            )
        return criteria

    def _phases_for(self, rulebook_id: UUID) -> list[PhenologicalPhase]:
        models = self._session.execute(
            select(RulebookPhaseModel)
            .where(RulebookPhaseModel.rulebook_id == rulebook_id)
            .order_by(RulebookPhaseModel.sequence_order)
        ).scalars()
        return [
            PhenologicalPhase(
                id=model.id,
                name=model.name,
                duration_days=model.duration_days,
                sequence_order=model.sequence_order,
            )
            for model in models
        ]

    def _requirements_for(self, criteria: list[Criterion], phases: list[PhenologicalPhase]) -> list[PhaseRequirement]:
        criterion_ids = [criterion.id for criterion in criteria]
        phase_ids = [phase.id for phase in phases]
        if not criterion_ids or not phase_ids:
            return []
        models = self._session.execute(
            select(PhaseRequirementModel).where(
                PhaseRequirementModel.criterion_id.in_(criterion_ids),
                PhaseRequirementModel.phase_id.in_(phase_ids),
            )
        ).scalars()
        return [_requirement_to_domain(model) for model in models]


def _requirement_to_domain(model: PhaseRequirementModel) -> PhaseRequirement:
    temporal_periods = _temporal_periods_from_payload(model.temporal_periods)
    extraction_binding = _extraction_binding_from_payload(model.extraction_binding)
    return PhaseRequirement(
        id=model.id,
        criterion_id=model.criterion_id,
        phase_id=model.phase_id,
        membership_fn=MembershipFunction.from_mapping(model.membership_fn),
        phase_weight=float(model.phase_weight),
        temporal_periods=temporal_periods,
        extraction_binding=extraction_binding,
    )


def _temporal_periods_from_payload(payload: object) -> list[TemporalPeriod]:
    raw_periods = payload if isinstance(payload, list) else []
    return [TemporalPeriod.from_mapping(period) for period in raw_periods]


def _extraction_binding_from_payload(payload: dict[str, Any]) -> ExtractionBinding:
    return ExtractionBinding(
        variable_name=str(payload.get("variable_name", "unknown")),
        dataset_key=str(payload.get("dataset_key", "unknown")),
        band=str(payload.get("band", "unknown")),
        unit=str(payload.get("unit", "unknown")),
        temporal_resolution=str(payload.get("temporal_resolution", "unknown")),
        spatial_resolution=payload.get("spatial_resolution"),
        scale=float(payload["scale"]) if payload.get("scale") is not None else None,
        reducer=payload.get("reducer"),
        aggregation_method=payload.get("aggregation_method"),
        quality_mask=payload.get("quality_mask"),
        fallback_allowed=bool(payload.get("fallback_allowed", False)),
    )


def _decimal_or_none(value: float | None) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _float_or_none(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None
