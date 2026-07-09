"""Tests for real FastAPI evaluation dependency wiring."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from via.bounded_contexts.iam.domain.role import Role
from via.bounded_contexts.viability_evaluation.interfaces.evaluation_router import (
    get_current_user,
    get_evaluation_query_service,
    get_process_manager,
)
from via.shared.orchestration.evaluation_process_manager.states import EvaluationSagaStatus


def test_evaluation_placeholders_raise_without_application_wiring() -> None:
    with pytest.raises(RuntimeError, match="Process Manager dependency is not configured"):
        get_process_manager()
    with pytest.raises(RuntimeError, match="Query Service dependency is not configured"):
        get_evaluation_query_service()
    with pytest.raises(RuntimeError, match="Authenticated user dependency is not configured"):
        get_current_user()


def test_create_app_wires_evaluation_dependencies() -> None:
    from via.bounded_contexts.iam.interfaces.auth_router import get_authentication_service
    from via.bounded_contexts.parcel_management.interfaces.parcel_router import get_parcel_command_service
    from via.main import create_app

    app = create_app()

    assert get_process_manager in app.dependency_overrides
    assert get_evaluation_query_service in app.dependency_overrides
    assert get_authentication_service in app.dependency_overrides
    assert get_parcel_command_service in app.dependency_overrides
    assert get_current_user in app.dependency_overrides


def test_post_evaluaciones_uses_runtime_process_manager_and_returns_202(monkeypatch: pytest.MonkeyPatch) -> None:
    import via.main as main_module

    process_manager = FakeProcessManager()
    monkeypatch.setattr(
        main_module,
        "configure_application_runtime",
        lambda **_: FakeRuntime(process_manager=process_manager),
    )
    app = main_module.create_app()
    current_user = FakeAuthenticatedUser()
    app.dependency_overrides[get_current_user] = lambda: current_user

    payload = {
        "parcel_id": str(uuid4()),
        "crop_candidates": ["demo_papa", "demo_maiz"],
        "temporal_window": {"start_date": "2025-01-01", "end_date": "2025-12-31"},
    }
    with TestClient(app, raise_server_exceptions=True) as client:
        response = client.post("/evaluaciones", json=payload)

    assert response.status_code == 202
    body = response.json()
    assert body["evaluation_id"] == str(process_manager.evaluation_id)
    assert body["status"] == EvaluationSagaStatus.INICIADA.value
    assert process_manager.calls == [
        (
            payload["parcel_id"],
            str(current_user.id),
            payload["crop_candidates"],
            payload["temporal_window"],
        )
    ]


def test_post_evaluaciones_without_token_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    import via.main as main_module

    monkeypatch.setattr(
        main_module,
        "configure_application_runtime",
        lambda **_: FakeRuntime(process_manager=FakeProcessManager()),
    )
    app = main_module.create_app()

    payload = {
        "parcel_id": str(uuid4()),
        "crop_candidates": ["demo_papa"],
        "temporal_window": {"start_date": "2025-01-01", "end_date": "2025-12-31"},
    }
    with TestClient(app, raise_server_exceptions=False) as client:
        post_response = client.post("/evaluaciones", json=payload)
        get_response = client.get(f"/evaluaciones/{uuid4()}/estado")
        recommendation_response = client.get(f"/evaluaciones/{uuid4()}/recomendacion-final")

    assert post_response.status_code == 401
    assert get_response.status_code == 401
    assert recommendation_response.status_code == 401


class FakeAuthenticatedUser:
    """Authenticated user double satisfying the evaluation route contract."""

    def __init__(self) -> None:
        self.id = uuid4()
        self.role = Role.USUARIO_AGRICOLA


class FakeProcessManager:
    """Runtime process manager double for HTTP wiring tests."""

    def __init__(self) -> None:
        self.evaluation_id = uuid4()
        self.calls: list[tuple[str, str, list[str], dict]] = []

    def start_evaluation(self, parcel_id, requested_by, crop_candidates, temporal_window, mcda_params=None):  # noqa: ANN001, ANN201
        """Record request data and return a deterministic id."""

        self.calls.append((str(parcel_id), str(requested_by), crop_candidates, temporal_window))
        return self.evaluation_id


@dataclass(frozen=True)
class FakeRuntime:
    """Runtime object with the attributes read by create_app."""

    process_manager: FakeProcessManager
    event_bus: object = object()
    relay_worker: object = object()


def test_create_app_registers_cors_middleware() -> None:
    from fastapi.middleware.cors import CORSMiddleware

    from via.main import create_app

    app = create_app()

    cors_layers = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert len(cors_layers) == 1
