"""Tests verifying that IAM dependencies are wired in the real FastAPI app."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from via.bounded_contexts.iam.domain.role import Role
from via.bounded_contexts.iam.domain.user import User
from via.bounded_contexts.iam.infrastructure.jwt_adapter import JWTTokenService
from via.bounded_contexts.parcel_management.domain.parcel import Parcel
from via.bounded_contexts.parcel_management.domain.value_objects import GeoJSONGeometry, ParcelMetadata


def test_authentication_service_stub_raises_runtime_error() -> None:
    from via.bounded_contexts.iam.interfaces.auth_router import get_authentication_service

    with pytest.raises(RuntimeError, match="not configured"):
        get_authentication_service()


def test_authentication_service_dependency_is_wired_in_real_app() -> None:
    from via.bounded_contexts.iam.interfaces.auth_router import get_authentication_service
    from via.main import create_app

    app = create_app()

    assert get_authentication_service in app.dependency_overrides, (
        "get_authentication_service must be overridden — POST /auth/login would return 500"
    )
    override = app.dependency_overrides[get_authentication_service]
    assert override is not get_authentication_service


def test_current_user_dependency_is_wired_for_protected_routers() -> None:
    from via.bounded_contexts.document_management.interfaces.document_router import get_current_user as get_document_current_user
    from via.bounded_contexts.parcel_management.interfaces.parcel_router import get_current_user as get_parcel_current_user
    from via.bounded_contexts.rulebook_management.interfaces.rulebook_router import get_current_user as get_rulebook_current_user
    from via.main import create_app

    app = create_app()

    assert get_parcel_current_user in app.dependency_overrides
    assert get_rulebook_current_user in app.dependency_overrides
    assert get_document_current_user in app.dependency_overrides


def test_post_parcelas_without_token_returns_auth_error_not_runtime_error() -> None:
    from via.main import create_app

    app = create_app()

    with TestClient(app, raise_server_exceptions=True) as client:
        response = client.post("/parcelas", json=_parcel_payload())

    assert response.status_code in {401, 403}


def test_post_parcelas_with_valid_token_resolves_current_user(monkeypatch: pytest.MonkeyPatch) -> None:
    import via.main as main_module
    from via.bounded_contexts.parcel_management.interfaces.parcel_router import get_parcel_command_service

    user = User.create(uuid4(), "admin@example.com", "hash", Role.ADMINISTRADOR)
    seen_owner_ids = []
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 32)

    class FakeUserRepository:
        """Repository double returning the user encoded in the JWT subject."""

        def __init__(self, session) -> None:
            """Accept the runtime session object."""

        def get_by_email(self, email: str) -> User | None:
            """Return no user for login paths unused by this test."""

            return None

        def get_by_id(self, user_id) -> User | None:
            """Return the test user when the decoded token subject matches."""

            return user if user_id == user.id else None

    class FakeParcelCommandService:
        """Command service double recording the resolved owner."""

        def register_parcel(self, owner_id, geometry, metadata):
            """Return a persisted-like parcel for the resolved owner."""

            seen_owner_ids.append(owner_id)
            return Parcel.create(
                owner_id=owner_id,
                geometry=GeoJSONGeometry.from_geojson(geometry),
                metadata=ParcelMetadata.from_mapping(metadata),
            )

    monkeypatch.setattr(main_module, "SQLAlchemyUserRepository", FakeUserRepository)
    app = main_module.create_app()
    app.dependency_overrides[get_parcel_command_service] = lambda: FakeParcelCommandService()
    token = JWTTokenService(main_module.get_settings()).create_access_token(user).access_token

    with TestClient(app, raise_server_exceptions=True) as client:
        response = client.post(
            "/parcelas",
            json=_parcel_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 201
    assert seen_owner_ids == [user.id]


def _parcel_payload() -> dict:
    return {
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[-76, -12], [-75.99, -12], [-75.99, -11.99], [-76, -11.99], [-76, -12]]],
        },
        "metadata": {"name": "Farm", "description": "Plot", "crs": "EPSG:4326"},
    }
