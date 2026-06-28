"""Unit tests for Rulebook Management router."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from via.bounded_contexts.iam.domain.role import Role
from via.bounded_contexts.iam.domain.user import User
from via.bounded_contexts.rulebook_management.domain.criterion import Criterion
from via.bounded_contexts.rulebook_management.domain.phase_requirement import ExtractionBinding, PhaseRequirement
from via.bounded_contexts.rulebook_management.domain.phenological_phase import PhenologicalPhase
from via.bounded_contexts.rulebook_management.domain.rulebook import Rulebook
from via.bounded_contexts.rulebook_management.domain.value_objects import InterventionClass, MembershipFunction, RulebookStatus, TemporalPeriod
from via.bounded_contexts.rulebook_management.interfaces import rulebook_router
from via.bounded_contexts.rulebook_management.interfaces.resources import (
    CreateRulebookRequest,
    CriterionResource,
    ExtractionBindingResource,
    MembershipFunctionResource,
    PhaseRequirementResource,
    PhenologicalPhaseResource,
    TemporalPeriodResource,
)


def test_rulebook_router_exposes_only_required_routes() -> None:
    routes = sorted((next(iter(route.methods - {"HEAD", "OPTIONS"})), route.path) for route in rulebook_router.router.routes)

    assert routes == sorted([
        ("GET", "/rulebooks"),
        ("POST", "/rulebooks"),
        ("POST", "/rulebooks/{rulebook_id}/publish"),
        ("GET", "/rulebooks/{crop_id}/active"),
    ])


def test_create_rulebook_requires_admin_role() -> None:
    with pytest.raises(HTTPException) as exc_info:
        rulebook_router.create_rulebook(_create_request(), _user(Role.ESPECIALISTA_TECNICO), FakeCommandService())

    assert exc_info.value.status_code == 403


def test_create_rulebook_returns_created_summary_for_admin() -> None:
    service = FakeCommandService()
    response = rulebook_router.create_rulebook(_create_request(), _user(Role.ADMINISTRADOR), service)

    assert response.crop_id == "cacao"
    assert response.status == RulebookStatus.DRAFT.value
    assert service.created_crop_id == "cacao"


def test_publish_rulebook_requires_admin_role() -> None:
    with pytest.raises(HTTPException) as exc_info:
        rulebook_router.publish_rulebook(uuid.uuid4(), _user(Role.ESPECIALISTA_TECNICO), FakeCommandService())

    assert exc_info.value.status_code == 403


def test_list_and_active_allow_admin_and_technical_specialist() -> None:
    query_service = FakeQueryService()

    for role in (Role.ADMINISTRADOR, Role.ESPECIALISTA_TECNICO):
        assert rulebook_router.list_rulebooks(_user(role), query_service)[0].crop_id == "cacao"
        assert rulebook_router.get_active_rulebook("cacao", _user(role), query_service).crop_id == "cacao"


def test_query_routes_reject_agricultural_user() -> None:
    with pytest.raises(HTTPException) as exc_info:
        rulebook_router.list_rulebooks(_user(Role.USUARIO_AGRICOLA), FakeQueryService())

    assert exc_info.value.status_code == 403


class FakeCommandService:
    """Rulebook command service test double."""

    def __init__(self) -> None:
        self.created_crop_id: str | None = None
        self.rulebook = _rulebook(RulebookStatus.DRAFT)

    def create_rulebook(self, crop_id: str, criteria: list[Criterion], phases: list[PhenologicalPhase], phase_requirements: list[PhaseRequirement]) -> Rulebook:
        self.created_crop_id = crop_id
        return self.rulebook

    def publish_rulebook(self, rulebook_id: uuid.UUID) -> Rulebook:
        self.rulebook.publish()
        return self.rulebook


class FakeQueryService:
    """Rulebook query service test double."""

    def __init__(self) -> None:
        self.rulebook = _rulebook(RulebookStatus.ACTIVE)

    def list_rulebooks(self) -> list[Rulebook]:
        return [self.rulebook]

    def get_active_rulebook(self, crop_id: str) -> Rulebook:
        return self.rulebook


def _user(role: Role) -> User:
    return User(id=uuid.uuid4(), email="user@example.com", hashed_password="hash", role=role)


def _rulebook(status: RulebookStatus) -> Rulebook:
    criterion, phase, requirement = _domain_parts()
    return Rulebook(uuid.uuid4(), "cacao", 1, status, [criterion], [phase], [requirement])


def _domain_parts() -> tuple[Criterion, PhenologicalPhase, PhaseRequirement]:
    criterion = Criterion(uuid.uuid4(), "Vigor", False, None, None, 1.0, InterventionClass.MITIGABLE)
    phase = PhenologicalPhase(uuid.uuid4(), "Floracion", 30, 1)
    requirement = PhaseRequirement(
        id=uuid.uuid4(),
        criterion_id=criterion.id,
        phase_id=phase.id,
        membership_fn=MembershipFunction(a=0, b=0.3, c=0.7, d=1),
        phase_weight=1.0,
        temporal_periods=[TemporalPeriod("mensual", 1.0)],
        extraction_binding=ExtractionBinding("ndvi", "sentinel-2", "B08", "index", "monthly"),
    )
    return criterion, phase, requirement


def _create_request() -> CreateRulebookRequest:
    criterion_id = uuid.uuid4()
    phase_id = uuid.uuid4()
    return CreateRulebookRequest(
        crop_id="cacao",
        criteria=[CriterionResource(id=criterion_id, name="Vigor", ahp_weight=1.0, intervention_class="MITIGABLE")],
        phases=[PhenologicalPhaseResource(id=phase_id, name="Floracion", duration_days=30, sequence_order=1)],
        phase_requirements=[
            PhaseRequirementResource(
                id=uuid.uuid4(),
                criterion_id=criterion_id,
                phase_id=phase_id,
                membership_fn=MembershipFunctionResource(a=0, b=0.3, c=0.7, d=1),
                phase_weight=1.0,
                temporal_periods=[TemporalPeriodResource(period_key="mensual", temporal_weight=1.0)],
                extraction=ExtractionBindingResource(
                    variable_name="ndvi",
                    dataset_key="sentinel-2",
                    band="B08",
                    unit="index",
                    temporal_resolution="monthly",
                ),
            )
        ],
    )
