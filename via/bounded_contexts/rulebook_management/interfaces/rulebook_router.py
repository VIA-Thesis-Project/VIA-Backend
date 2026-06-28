"""Protected Rulebook Management routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from via.bounded_contexts.iam.domain.role import Role
from via.bounded_contexts.iam.domain.user import User
from via.bounded_contexts.rulebook_management.application.command_service import RulebookCommandService
from via.bounded_contexts.rulebook_management.application.exceptions import ActiveRulebookNotFoundError, RulebookNotFoundError
from via.bounded_contexts.rulebook_management.application.query_service import RulebookQueryService
from via.bounded_contexts.rulebook_management.domain.criterion import Criterion
from via.bounded_contexts.rulebook_management.domain.phase_requirement import ExtractionBinding, PhaseRequirement
from via.bounded_contexts.rulebook_management.domain.phenological_phase import PhenologicalPhase
from via.bounded_contexts.rulebook_management.domain.rulebook import Rulebook
from via.bounded_contexts.rulebook_management.domain.value_objects import (
    CriticalPolicy,
    InterventionClass,
    MembershipFunction,
    RulebookValidationError,
    TemporalPeriod,
)
from via.bounded_contexts.rulebook_management.interfaces.resources import (
    CreateRulebookRequest,
    CriterionResource,
    ExtractionBindingResource,
    MembershipFunctionResource,
    PhaseRequirementResource,
    PhenologicalPhaseResource,
    RulebookDetailResponse,
    RulebookResponse,
    TemporalPeriodResource,
)


router = APIRouter(prefix="/rulebooks", tags=["rulebooks"])
QUERY_ROLES = {Role.ADMINISTRADOR, Role.ESPECIALISTA_TECNICO}
COMMAND_ROLES = {Role.ADMINISTRADOR}


def get_current_user() -> User:
    """Return the authenticated user dependency."""

    raise RuntimeError("Authenticated user dependency is not configured")


def get_rulebook_command_service() -> RulebookCommandService:
    """Return the configured rulebook command service dependency."""

    raise RuntimeError("Rulebook command service dependency is not configured")


def get_rulebook_query_service() -> RulebookQueryService:
    """Return the configured rulebook query service dependency."""

    raise RuntimeError("Rulebook query service dependency is not configured")


@router.get("", response_model=list[RulebookResponse])
def list_rulebooks(
    current_user: User = Depends(get_current_user),
    query_service: RulebookQueryService = Depends(get_rulebook_query_service),
) -> list[RulebookResponse]:
    """List all rulebook versions."""

    _ensure_role(current_user, QUERY_ROLES)
    return [_to_summary(rulebook) for rulebook in query_service.list_rulebooks()]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=RulebookResponse)
def create_rulebook(
    request: CreateRulebookRequest,
    current_user: User = Depends(get_current_user),
    command_service: RulebookCommandService = Depends(get_rulebook_command_service),
) -> RulebookResponse:
    """Create a draft rulebook version."""

    _ensure_role(current_user, COMMAND_ROLES)
    try:
        rulebook = command_service.create_rulebook(
            crop_id=request.crop_id,
            criteria=[_criterion_from_resource(item) for item in request.criteria],
            phases=[_phase_from_resource(item) for item in request.phases],
            phase_requirements=[_requirement_from_resource(item) for item in request.phase_requirements],
        )
    except (RulebookValidationError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _to_summary(rulebook)


@router.post("/{rulebook_id}/publish", response_model=RulebookResponse)
def publish_rulebook(
    rulebook_id: UUID,
    current_user: User = Depends(get_current_user),
    command_service: RulebookCommandService = Depends(get_rulebook_command_service),
) -> RulebookResponse:
    """Publish a rulebook version."""

    _ensure_role(current_user, COMMAND_ROLES)
    try:
        return _to_summary(command_service.publish_rulebook(rulebook_id))
    except RulebookNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rulebook not found") from exc


@router.get("/{crop_id}/active", response_model=RulebookDetailResponse)
def get_active_rulebook(
    crop_id: str,
    current_user: User = Depends(get_current_user),
    query_service: RulebookQueryService = Depends(get_rulebook_query_service),
) -> RulebookDetailResponse:
    """Return the active rulebook for one crop."""

    _ensure_role(current_user, QUERY_ROLES)
    try:
        return _to_detail(query_service.get_active_rulebook(crop_id))
    except ActiveRulebookNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active rulebook not found") from exc


def _ensure_role(user: User, allowed_roles: set[Role]) -> None:
    if user.role not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


def _criterion_from_resource(resource: CriterionResource) -> Criterion:
    policy = CriticalPolicy(resource.critical_policy) if resource.critical_policy is not None else None
    return Criterion(
        id=resource.id,
        name=resource.name,
        is_critical=resource.is_critical,
        critical_policy=policy,
        penalty_factor=resource.penalty_factor,
        ahp_weight=resource.ahp_weight,
        intervention_class=InterventionClass(resource.intervention_class),
        doc_source=resource.doc_source,
        technical_notes=resource.technical_notes,
    )


def _phase_from_resource(resource: PhenologicalPhaseResource) -> PhenologicalPhase:
    return PhenologicalPhase(
        id=resource.id,
        name=resource.name,
        duration_days=resource.duration_days,
        sequence_order=resource.sequence_order,
    )


def _requirement_from_resource(resource: PhaseRequirementResource) -> PhaseRequirement:
    return PhaseRequirement(
        id=resource.id,
        criterion_id=resource.criterion_id,
        phase_id=resource.phase_id,
        membership_fn=_membership_from_resource(resource.membership_fn),
        phase_weight=resource.phase_weight,
        temporal_periods=[_period_from_resource(period) for period in resource.temporal_periods],
        extraction_binding=_extraction_from_resource(resource.extraction),
    )


def _membership_from_resource(resource: MembershipFunctionResource) -> MembershipFunction:
    return MembershipFunction(
        a=resource.a,
        b=resource.b,
        c=resource.c,
        d=resource.d,
        function_type=resource.function_type,
    )


def _period_from_resource(resource: TemporalPeriodResource) -> TemporalPeriod:
    return TemporalPeriod(
        period_key=resource.period_key,
        temporal_weight=resource.temporal_weight,
        start_day=resource.start_day,
        end_day=resource.end_day,
    )


def _extraction_from_resource(resource: ExtractionBindingResource) -> ExtractionBinding:
    return ExtractionBinding(**resource.model_dump())


def _to_summary(rulebook: Rulebook) -> RulebookResponse:
    return RulebookResponse(id=rulebook.id, crop_id=rulebook.crop_id, version=rulebook.version, status=rulebook.status.value)


def _to_detail(rulebook: Rulebook) -> RulebookDetailResponse:
    return RulebookDetailResponse(
        **_to_summary(rulebook).model_dump(),
        criteria=[_criterion_to_resource(criterion) for criterion in rulebook.criteria],
        phases=[_phase_to_resource(phase) for phase in rulebook.phases],
        phase_requirements=[_requirement_to_resource(requirement) for requirement in rulebook.phase_requirements],
    )


def _criterion_to_resource(criterion: Criterion) -> CriterionResource:
    return CriterionResource(
        id=criterion.id,
        name=criterion.name,
        is_critical=criterion.is_critical,
        critical_policy=criterion.critical_policy.value if criterion.critical_policy else None,
        penalty_factor=criterion.penalty_factor,
        ahp_weight=criterion.ahp_weight,
        intervention_class=criterion.intervention_class.value,
        doc_source=criterion.doc_source,
        technical_notes=criterion.technical_notes,
    )


def _phase_to_resource(phase: PhenologicalPhase) -> PhenologicalPhaseResource:
    return PhenologicalPhaseResource(id=phase.id, name=phase.name, duration_days=phase.duration_days, sequence_order=phase.sequence_order)


def _requirement_to_resource(requirement: PhaseRequirement) -> PhaseRequirementResource:
    return PhaseRequirementResource(
        id=requirement.id,
        criterion_id=requirement.criterion_id,
        phase_id=requirement.phase_id,
        membership_fn=MembershipFunctionResource(**requirement.membership_fn.to_mapping()),
        phase_weight=requirement.phase_weight,
        temporal_periods=[TemporalPeriodResource(**period.to_mapping()) for period in requirement.temporal_periods],
        extraction=ExtractionBindingResource(**requirement.extraction_binding.to_mapping()),
    )
