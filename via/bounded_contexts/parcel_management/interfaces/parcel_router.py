"""Protected parcel management routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from via.bounded_contexts.iam.domain.role import Role
from via.bounded_contexts.iam.domain.user import User
from via.bounded_contexts.parcel_management.application.command_service import (
    ParcelAccessDeniedError,
    ParcelCommandService,
    ParcelNotFoundError,
)
from via.bounded_contexts.parcel_management.application.query_service import ParcelQueryService
from via.bounded_contexts.parcel_management.domain.parcel import Parcel
from via.bounded_contexts.parcel_management.domain.value_objects import GeometryValidationError
from via.bounded_contexts.parcel_management.interfaces.resources import (
    ParcelCreateRequest,
    ParcelMetadataResource,
    ParcelResponse,
    ParcelUpdateRequest,
)


router = APIRouter(prefix="/parcelas", tags=["parcelas"])
ALLOWED_PARCEL_ROLES = {Role.ADMINISTRADOR, Role.USUARIO_AGRICOLA}


def get_current_user() -> User:
    """Return the authenticated user dependency."""

    raise RuntimeError("Authenticated user dependency is not configured")


def get_parcel_command_service() -> ParcelCommandService:
    """Return the configured parcel command service dependency."""

    raise RuntimeError("Parcel command service dependency is not configured")


def get_parcel_query_service() -> ParcelQueryService:
    """Return the configured parcel query service dependency."""

    raise RuntimeError("Parcel query service dependency is not configured")


@router.get("", response_model=list[ParcelResponse])
def list_parcels(
    current_user: User = Depends(get_current_user),
    query_service: ParcelQueryService = Depends(get_parcel_query_service),
) -> list[ParcelResponse]:
    """List parcels owned by the authenticated user."""

    _ensure_allowed_role(current_user)
    return [_to_response(parcel) for parcel in query_service.list_parcels(current_user.id)]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ParcelResponse)
def create_parcel(
    request: ParcelCreateRequest,
    current_user: User = Depends(get_current_user),
    command_service: ParcelCommandService = Depends(get_parcel_command_service),
) -> ParcelResponse:
    """Register a new parcel for the authenticated user."""

    _ensure_allowed_role(current_user)
    try:
        parcel = command_service.register_parcel(
            owner_id=current_user.id,
            geometry=request.geometry,
            metadata=request.metadata.model_dump(),
        )
    except (GeometryValidationError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _to_response(parcel)


@router.get("/{parcel_id}", response_model=ParcelResponse)
def get_parcel(
    parcel_id: UUID,
    current_user: User = Depends(get_current_user),
    query_service: ParcelQueryService = Depends(get_parcel_query_service),
) -> ParcelResponse:
    """Return one owned parcel by id."""

    _ensure_allowed_role(current_user)
    try:
        return _to_response(query_service.get_parcel(parcel_id, current_user.id))
    except ParcelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parcel not found") from exc
    except ParcelAccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied") from exc


@router.patch("/{parcel_id}", response_model=ParcelResponse)
def update_parcel(
    parcel_id: UUID,
    request: ParcelUpdateRequest,
    current_user: User = Depends(get_current_user),
    command_service: ParcelCommandService = Depends(get_parcel_command_service),
) -> ParcelResponse:
    """Update one owned parcel."""

    _ensure_allowed_role(current_user)
    try:
        parcel = command_service.update_parcel(
            parcel_id=parcel_id,
            owner_id=current_user.id,
            geometry=request.geometry,
            metadata=request.metadata.model_dump() if request.metadata is not None else None,
        )
    except ParcelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parcel not found") from exc
    except ParcelAccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied") from exc
    except (GeometryValidationError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _to_response(parcel)


def _ensure_allowed_role(user: User) -> None:
    if user.role not in ALLOWED_PARCEL_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


def _to_response(parcel: Parcel) -> ParcelResponse:
    return ParcelResponse(
        id=parcel.id,
        owner_id=parcel.owner_id,
        geometry=parcel.geometry.to_geojson(),
        metadata=ParcelMetadataResource(**parcel.metadata.to_mapping()),
    )
