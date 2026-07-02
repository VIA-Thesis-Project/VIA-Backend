"""Tests for the minimal evaluation HTTP router."""

from __future__ import annotations

from uuid import uuid4

from via.bounded_contexts.viability_evaluation.interfaces.evaluation_router import StartEvaluationRequest, router, start_evaluation


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
    requested_by = uuid4()

    response = start_evaluation(
        StartEvaluationRequest(
            parcel_id=parcel_id,
            requested_by=requested_by,
            crop_candidates=["cacao"],
            temporal_window={"start": "2026-01-01", "end": "2026-03-31"},
        ),
        process_manager,
    )

    assert response.evaluation_id == evaluation_id
    assert response.status == "INICIADA"
    assert process_manager.calls[0][2] == ["cacao"]


def test_router_declares_http_202_start_endpoint() -> None:
    matching_routes = [route for route in router.routes if getattr(route, "path", None) == "/evaluaciones"]

    assert len(matching_routes) == 1
    assert len(router.routes) == 4  # POST /evaluaciones + GET estado/resultado-mcda/vector-agroambiental
    assert matching_routes[0].status_code == 202
    assert matching_routes[0].methods == {"POST"}
