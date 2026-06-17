"""Unit tests for Rulebook Management services."""

from __future__ import annotations

import uuid

from via.bounded_contexts.rulebook_management.application.command_service import RulebookCommandService
from via.bounded_contexts.rulebook_management.application.query_service import RulebookQueryService
from via.bounded_contexts.rulebook_management.domain.criterion import Criterion
from via.bounded_contexts.rulebook_management.domain.phase_requirement import ExtractionBinding, PhaseRequirement
from via.bounded_contexts.rulebook_management.domain.phenological_phase import PhenologicalPhase
from via.bounded_contexts.rulebook_management.domain.rulebook import Rulebook
from via.bounded_contexts.rulebook_management.domain.value_objects import (
    MembershipFunction,
    RulebookStatus,
    TemporalPeriod,
)
from via.shared.orchestration.evaluation_process_manager.ports import RequiredExtractionSpec


def test_create_rulebook_assigns_next_version_and_keeps_draft() -> None:
    repository = FakeRulebookRepository(next_version=3)
    criterion, phase, requirement = _rule_parts()
    service = RulebookCommandService(repository=repository)

    rulebook = service.create_rulebook("cacao", [criterion], [phase], [requirement])

    assert rulebook.version == 3
    assert rulebook.status == RulebookStatus.DRAFT
    assert repository.added == [rulebook]


def test_publish_deactivates_previous_active_before_saving_published_rulebook() -> None:
    repository = FakeRulebookRepository()
    criterion, phase, requirement = _rule_parts()
    rulebook = Rulebook(uuid.uuid4(), "cacao", 2, RulebookStatus.DRAFT, [criterion], [phase], [requirement])
    repository.by_id[rulebook.id] = rulebook
    service = RulebookCommandService(repository=repository)

    published = service.publish_rulebook(rulebook.id)

    assert published.status == RulebookStatus.ACTIVE
    assert repository.calls == [("deactivate_active_for_crop", "cacao"), ("save", str(rulebook.id))]


def test_required_extraction_spec_is_read_model_without_orm() -> None:
    repository = FakeRulebookRepository()
    criterion, phase, requirement = _rule_parts()
    active_rulebook = Rulebook(uuid.uuid4(), "cacao", 1, RulebookStatus.ACTIVE, [criterion], [phase], [requirement])
    repository.active_by_crop["cacao"] = active_rulebook
    service = RulebookQueryService(repository)

    spec = service.get_required_extraction_spec(["cacao"], {"start": "2026-01-01", "end": "2026-12-31"})

    assert isinstance(spec, RequiredExtractionSpec)
    assert len(spec.variables) == 1
    variable = spec.variables[0]
    assert variable.variable_name == "ndvi"
    assert variable.criterion_id == str(criterion.id)
    assert variable.phase_id == str(phase.id)
    assert variable.crop_id == "cacao"
    assert variable.dataset_key == "sentinel-2"
    assert variable.band == "B08"
    assert variable.unit == "index"
    assert variable.quality_mask == {"cloud": "masked"}
    assert variable.fallback_allowed is True
    assert variable.temporal_periods == [{"period_key": "mensual", "temporal_weight": 1.0, "start_day": None, "end_day": None}]
    assert not variable.__class__.__module__.startswith("via.bounded_contexts.rulebook_management.infrastructure")


def test_get_active_rulebook_returns_repository_active_version() -> None:
    repository = FakeRulebookRepository()
    criterion, phase, requirement = _rule_parts()
    active_rulebook = Rulebook(uuid.uuid4(), "cacao", 1, RulebookStatus.ACTIVE, [criterion], [phase], [requirement])
    repository.active_by_crop["cacao"] = active_rulebook

    assert RulebookQueryService(repository).get_active_rulebook("cacao") == active_rulebook


class FakeRulebookRepository:
    """In-memory rulebook repository test double."""

    def __init__(self, next_version: int = 1) -> None:
        self._next_version = next_version
        self.added: list[Rulebook] = []
        self.by_id: dict[uuid.UUID, Rulebook] = {}
        self.active_by_crop: dict[str, Rulebook] = {}
        self.calls: list[tuple[str, str]] = []

    def next_version_for_crop(self, crop_id: str) -> int:
        return self._next_version

    def add(self, rulebook: Rulebook) -> None:
        self.added.append(rulebook)
        self.by_id[rulebook.id] = rulebook

    def get_by_id(self, rulebook_id: uuid.UUID) -> Rulebook | None:
        return self.by_id.get(rulebook_id)

    def get_active_by_crop(self, crop_id: str) -> Rulebook | None:
        return self.active_by_crop.get(crop_id)

    def list_all(self) -> list[Rulebook]:
        return list(self.by_id.values())

    def deactivate_active_for_crop(self, crop_id: str) -> None:
        self.calls.append(("deactivate_active_for_crop", crop_id))
        active = self.active_by_crop.get(crop_id)
        if active is not None:
            active.deactivate()

    def save(self, rulebook: Rulebook) -> None:
        self.calls.append(("save", str(rulebook.id)))
        self.by_id[rulebook.id] = rulebook


def _rule_parts() -> tuple[Criterion, PhenologicalPhase, PhaseRequirement]:
    criterion = Criterion(uuid.uuid4(), "Vigor", False, None, None, 1.0)
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
    return criterion, phase, requirement
