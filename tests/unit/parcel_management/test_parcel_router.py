"""Unit tests for parcel HTTP route functions."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from via.bounded_contexts.iam.domain.role import Role
from via.bounded_contexts.iam.domain.user import User
from via.bounded_contexts.parcel_management.application.command_service import ParcelAccessDeniedError
from via.bounded_contexts.parcel_management.domain.parcel import Parcel
from via.bounded_contexts.parcel_management.domain.value_objects import GeoJSONGeometry, ParcelMetadata
from via.bounded_contexts.parcel_management.interfaces.parcel_router import create_parcel, delete_parcel, get_parcel, list_parcels, router
from via.bounded_contexts.parcel_management.interfaces.resources import ParcelCreateRequest, ParcelMetadataResource


class FakeCommandService:
    """Command service test double."""

    def __init__(self) -> None:
        """Initialize call log."""

        self.calls = []

    def register_parcel(self, owner_id, geometry, metadata):
        """Record and return a parcel."""

        self.calls.append((owner_id, geometry, metadata))
        return _parcel(owner_id)

    def delete_parcel(self, parcel_id, owner_id):
        """Record or deny a deletion."""

        self.calls.append(("delete", parcel_id, owner_id))
        if getattr(self, "deny_delete", False):
            raise ParcelAccessDeniedError("Access denied")


class FakeQueryService:
    """Query service test double."""

    def __init__(self, parcel: Parcel | None = None, deny: bool = False) -> None:
        """Configure the fake response."""

        self.parcel = parcel
        self.deny = deny
        self.calls = []

    def list_parcels(self, owner_id):
        """Return owned parcels."""

        self.calls.append(("list", owner_id))
        return [self.parcel] if self.parcel is not None else []

    def get_parcel(self, parcel_id, owner_id):
        """Return or deny one parcel."""

        self.calls.append(("get", parcel_id, owner_id))
        if self.deny:
            raise ParcelAccessDeniedError("Access denied")
        return self.parcel


def test_create_parcel_requires_allowed_role_and_returns_201_shape() -> None:
    user = _user(Role.USUARIO_AGRICOLA)
    service = FakeCommandService()

    response = create_parcel(
        ParcelCreateRequest(geometry=_polygon(), metadata=ParcelMetadataResource(**_metadata())),
        user,
        service,
    )

    assert response.owner_id == user.id
    assert response.geometry["type"] == "MultiPolygon"
    assert service.calls[0][0] == user.id


def test_list_parcels_returns_only_query_service_results_for_current_user() -> None:
    user = _user(Role.ADMINISTRADOR)
    parcel = _parcel(user.id)

    response = list_parcels(user, FakeQueryService(parcel))

    assert [item.id for item in response] == [parcel.id]


def test_foreign_parcel_access_returns_403() -> None:
    user = _user(Role.ADMINISTRADOR)

    with pytest.raises(HTTPException) as exc_info:
        get_parcel(uuid4(), user, FakeQueryService(_parcel(uuid4()), deny=True))

    assert exc_info.value.status_code == 403


def test_especialista_tecnico_is_rejected_for_parcel_routes() -> None:
    user = _user(Role.ESPECIALISTA_TECNICO)

    with pytest.raises(HTTPException) as exc_info:
        list_parcels(user, FakeQueryService())

    assert exc_info.value.status_code == 403


def test_delete_parcel_delegates_to_command_service() -> None:
    user = _user(Role.USUARIO_AGRICOLA)
    service = FakeCommandService()
    parcel_id = uuid4()

    delete_parcel(parcel_id, user, service)

    assert service.calls == [("delete", parcel_id, user.id)]


def test_delete_foreign_parcel_returns_403() -> None:
    user = _user(Role.USUARIO_AGRICOLA)
    service = FakeCommandService()
    service.deny_delete = True

    with pytest.raises(HTTPException) as exc_info:
        delete_parcel(uuid4(), user, service)

    assert exc_info.value.status_code == 403


def test_router_exposes_exactly_required_parcel_routes() -> None:
    routes = {(route.path, tuple(sorted(route.methods))) for route in router.routes}

    assert routes == {
        ("/parcelas", ("GET",)),
        ("/parcelas", ("POST",)),
        ("/parcelas/{parcel_id}", ("GET",)),
        ("/parcelas/{parcel_id}", ("PATCH",)),
        ("/parcelas/{parcel_id}", ("DELETE",)),
    }


def _user(role: Role) -> User:
    return User.create(uuid4(), "user@example.com", "hash", role)


def _parcel(owner_id) -> Parcel:
    return Parcel.create(owner_id, GeoJSONGeometry.from_geojson(_polygon()), ParcelMetadata.from_mapping(_metadata()))


def _polygon() -> dict:
    return {"type": "Polygon", "coordinates": [[[-76, -12], [-75.99, -12], [-75.99, -11.99], [-76, -11.99], [-76, -12]]]}


def _metadata() -> dict:
    return {"name": "Farm", "description": "Plot", "crs": "EPSG:4326"}
