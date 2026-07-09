"""Tests for the minimal evaluation HTTP router."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from via.bounded_contexts.iam.domain.role import Role
from via.bounded_contexts.viability_evaluation.interfaces.evaluation_router import (
    StartEvaluationRequest,
    router,
    start_evaluation,
)


@dataclass(frozen=True)
class FakeUser:
    """Authenticated user double for route dependency injection."""

    id: UUID
    role: Role = Role.USUARIO_AGRICOLA


class FakeProcessManager:
    """Process Manager test double for route dependency injection."""

    def __init__(self, evaluation_id):
        """Store the deterministic evaluation id returned by the route."""

        self.evaluation_id = evaluation_id
        self.calls = []

    def start_evaluation(self, parcel_id, requested_by, crop_candidates, temporal_window):
        """Record input and return a precomputed evaluation id."""

        self.calls.append((parcel_id, requested_by, crop_candidates, temporal_window))
        return self.evaluation_id


def test_start_evaluation_endpoint_returns_accepted_evaluation_id() -> None:
    evaluation_id = uuid4()
    process_manager = FakeProcessManager(evaluation_id)
    parcel_id = uuid4()
    current_user = FakeUser(id=uuid4())

    response = start_evaluation(
        StartEvaluationRequest(
            parcel_id=parcel_id,
            crop_candidates=["cacao"],
            temporal_window={"start": "2026-01-01", "end": "2026-03-31"},
        ),
        current_user,
        process_manager,
    )

    assert response.evaluation_id == evaluation_id
    assert response.status == "INICIADA"
    assert process_manager.calls[0][2] == ["cacao"]


def test_start_evaluation_uses_authenticated_user_as_requested_by() -> None:
    process_manager = FakeProcessManager(uuid4())
    current_user = FakeUser(id=uuid4())

    start_evaluation(
        StartEvaluationRequest(
            parcel_id=uuid4(),
            crop_candidates=["cacao"],
            temporal_window={"start": "2026-01-01", "end": "2026-03-31"},
        ),
        current_user,
        process_manager,
    )

    assert process_manager.calls[0][1] == current_user.id


def test_start_evaluation_request_has_no_requested_by_field() -> None:
    assert "requested_by" not in StartEvaluationRequest.model_fields


def test_start_evaluation_rejects_disallowed_role() -> None:
    process_manager = FakeProcessManager(uuid4())
    current_user = FakeUser(id=uuid4(), role=Role.ESPECIALISTA_TECNICO)

    with pytest.raises(HTTPException) as exc_info:
        start_evaluation(
            StartEvaluationRequest(
                parcel_id=uuid4(),
                crop_candidates=["cacao"],
                temporal_window={"start": "2026-01-01", "end": "2026-03-31"},
            ),
            current_user,
            process_manager,
        )

    assert exc_info.value.status_code == 403
    assert process_manager.calls == []


def test_router_declares_http_202_start_endpoint() -> None:
    matching_routes = [
        route
        for route in router.routes
        if getattr(route, "path", None) == "/evaluaciones" and route.methods == {"POST"}
    ]

    assert len(matching_routes) == 1
    assert len(router.routes) == 5  # POST+GET /evaluaciones + GET estado/resultado-mcda/vector-agroambiental
    assert matching_routes[0].status_code == 202
