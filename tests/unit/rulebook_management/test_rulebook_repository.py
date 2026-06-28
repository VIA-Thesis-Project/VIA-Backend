"""Unit tests for Rulebook Management repository mapping."""

from __future__ import annotations

import uuid

from via.bounded_contexts.rulebook_management.domain.criterion import Criterion
from via.bounded_contexts.rulebook_management.domain.phase_requirement import ExtractionBinding, PhaseRequirement
from via.bounded_contexts.rulebook_management.domain.phenological_phase import PhenologicalPhase
from via.bounded_contexts.rulebook_management.domain.rulebook import Rulebook
from via.bounded_contexts.rulebook_management.domain.value_objects import InterventionClass, MembershipFunction, RulebookStatus, TemporalPeriod
from via.bounded_contexts.rulebook_management.infrastructure.orm_models import (
    CriterionModel,
    PhaseRequirementModel,
    RulebookModel,
    RulebookPhaseModel,
)
from via.bounded_contexts.rulebook_management.infrastructure.rulebook_repository import SqlAlchemyRulebookRepository


def _make_rulebook() -> tuple[Rulebook, Criterion, PhenologicalPhase, PhaseRequirement]:
    criterion = Criterion(uuid.uuid4(), "Vigor", False, None, None, 1.0, InterventionClass.MITIGABLE)
    phase = PhenologicalPhase(uuid.uuid4(), "Floracion", 30, 1)
    requirement = PhaseRequirement(
        id=uuid.uuid4(),
        criterion_id=criterion.id,
        phase_id=phase.id,
        membership_fn=MembershipFunction(a=0, b=0.3, c=0.7, d=1.0),
        phase_weight=1.0,
        temporal_periods=[TemporalPeriod("mensual", 1.0)],
        extraction_binding=ExtractionBinding(
            variable_name="ndvi",
            dataset_key="sentinel-2",
            band="B08",
            unit="index",
            temporal_resolution="monthly",
            spatial_resolution="10m",
            scale=10,
            reducer="median",
            aggregation_method="mean",
            quality_mask={"cloud": "masked"},
            fallback_allowed=True,
        ),
    )
    rulebook = Rulebook(uuid.uuid4(), "cacao", 1, RulebookStatus.DRAFT, [criterion], [phase], [requirement])
    return rulebook, criterion, phase, requirement


def test_repository_persists_temporal_periods_and_extraction_binding_separately() -> None:
    session = FakeSession()
    repository = SqlAlchemyRulebookRepository(session)  # type: ignore[arg-type]

    rulebook, _, _, _ = _make_rulebook()
    repository.add(rulebook)

    persisted_requirement = next(item for item in session.added if isinstance(item, PhaseRequirementModel))
    assert persisted_requirement.temporal_periods == [
        {"period_key": "mensual", "temporal_weight": 1.0, "start_day": None, "end_day": None}
    ]
    assert "extraction" not in persisted_requirement.temporal_periods[0]
    assert persisted_requirement.extraction_binding == {
        "variable_name": "ndvi",
        "dataset_key": "sentinel-2",
        "band": "B08",
        "unit": "index",
        "temporal_resolution": "monthly",
        "spatial_resolution": "10m",
        "scale": 10,
        "reducer": "median",
        "aggregation_method": "mean",
        "quality_mask": {"cloud": "masked"},
        "fallback_allowed": True,
    }


def test_repository_parent_flushed_before_children() -> None:
    """RulebookModel must be added and flushed before FK-referencing children.

    Without this ordering, PostgreSQL raises a ForeignKeyViolation when
    CriterionModel or RulebookPhaseModel is inserted before the parent row.
    PhaseRequirementModel depends on both, so it must come last.
    """
    session = FakeSession()
    repository = SqlAlchemyRulebookRepository(session)  # type: ignore[arg-type]

    rulebook, _, _, _ = _make_rulebook()
    repository.add(rulebook)

    # First item must always be the parent RulebookModel
    assert isinstance(session.added[0], RulebookModel), (
        f"First item added to session must be RulebookModel, "
        f"got {type(session.added[0]).__name__}"
    )

    # A flush must occur immediately after the parent (at position 1)
    assert 1 in session.flushed_at, (
        "session.flush() must be called after adding RulebookModel (position 1) "
        "so the parent row exists in DB before FK-referencing children are inserted."
    )

    # Gather insertion positions per model type
    positions = {type(item).__name__: i for i, item in enumerate(session.added)}
    rulebook_pos = positions["RulebookModel"]
    criterion_pos = positions["CriterionModel"]
    phase_pos = positions["RulebookPhaseModel"]
    requirement_pos = positions["PhaseRequirementModel"]

    assert rulebook_pos < criterion_pos, (
        "RulebookModel must be added before CriterionModel"
    )
    assert rulebook_pos < phase_pos, (
        "RulebookModel must be added before RulebookPhaseModel"
    )
    assert criterion_pos < requirement_pos, (
        "CriterionModel must be added before PhaseRequirementModel"
    )
    assert phase_pos < requirement_pos, (
        "RulebookPhaseModel must be added before PhaseRequirementModel"
    )

    # A second flush must occur before PhaseRequirementModel
    flush_before_requirement = [f for f in session.flushed_at if f <= requirement_pos]
    assert len(flush_before_requirement) >= 2, (
        "session.flush() must be called at least twice: once after RulebookModel "
        "and once after CriterionModel+RulebookPhaseModel (before PhaseRequirementModel)."
    )


class FakeSession:
    """Session double that records ORM instances added and flush call positions."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushed_at: list[int] = []

    def add(self, instance: object) -> None:
        """Record an ORM instance."""
        self.added.append(instance)

    def flush(self) -> None:
        """Record the position in the add sequence at which flush was called."""
        self.flushed_at.append(len(self.added))
