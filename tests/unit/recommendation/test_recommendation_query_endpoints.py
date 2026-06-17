"""Unit tests for recommendation query endpoints (task 10E).

Verifies endpoint behavior using a fake query service — no DB, no LLM,
no GEE, no MCDA recalculation. All values come from pre-built read model stubs.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from via.bounded_contexts.recommendation.application.ports import (
    FinalRecommendationResult,
    RecommendationReadModel,
)
from via.bounded_contexts.recommendation.interfaces.recommendation_router import (
    get_final_recommendation,
    get_recommendation,
    get_recommendations_for_evaluation,
    router,
)


ROOT = Path(__file__).resolve().parents[3]
ROUTER_PATH = ROOT / "via" / "bounded_contexts" / "recommendation" / "interfaces" / "recommendation_router.py"
QUERY_SVC_PATH = ROOT / "via" / "bounded_contexts" / "recommendation" / "application" / "recommendation_query_service.py"

_RID = UUID("00000000-0000-4000-8000-000000000010")
_EID = UUID("00000000-0000-4000-8000-000000000001")
_PID = UUID("00000000-0000-4000-8000-000000000002")
_FID = UUID("00000000-0000-4000-8000-000000000003")
_NOW = datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc)


# ─────────────────────── test doubles ─────────────────────────────────────────


class FakeRecommendationQueryService:
    """Fake query service recording calls for test assertions."""

    def __init__(
        self,
        *,
        recommendation: RecommendationReadModel | None = None,
        evaluation_list: list[RecommendationReadModel] | None = None,
        final_result: FinalRecommendationResult | None = None,
    ) -> None:
        self._recommendation = recommendation
        self._evaluation_list = evaluation_list or []
        self._final_result = final_result or FinalRecommendationResult(evaluation_found=False, recommendation=None)
        self.get_recommendation_calls: list[UUID] = []
        self.get_recommendations_for_evaluation_calls: list[UUID] = []
        self.get_final_recommendation_calls: list[UUID] = []

    def get_recommendation(self, recommendation_id: UUID):  # noqa: ANN201
        self.get_recommendation_calls.append(recommendation_id)
        return self._recommendation

    def get_recommendations_for_evaluation(self, evaluation_id: UUID):  # noqa: ANN201
        self.get_recommendations_for_evaluation_calls.append(evaluation_id)
        return self._evaluation_list

    def get_final_recommendation(self, evaluation_id: UUID):  # noqa: ANN201
        self.get_final_recommendation_calls.append(evaluation_id)
        return self._final_result


# ─────────────────────── fixture factories ────────────────────────────────────


def _rm(
    recommendation_id: UUID = _RID,
    evaluation_id: UUID = _EID,
    parcel_id: UUID | None = _PID,
    crop_id: str = "cacao",
    fragment_ids: list[UUID] | None = None,
) -> RecommendationReadModel:
    return RecommendationReadModel(
        recommendation_id=recommendation_id,
        evaluation_id=evaluation_id,
        parcel_id=parcel_id,
        crop_id=crop_id,
        status="GENERATED",
        title=f"Recomendación para {crop_id}",
        fragment_ids=fragment_ids or [_FID],
        created_at=_NOW,
        provider="template",
    )


# ────────────────── tests GET /recomendaciones/{id} ───────────────────────────


def test_get_recommendation_returns_existing_recommendation() -> None:
    svc = FakeRecommendationQueryService(recommendation=_rm())
    resp = get_recommendation(_RID, svc)
    assert resp.recommendation_id == _RID
    assert resp.evaluation_id == _EID
    assert resp.crop_id == "cacao"
    assert svc.get_recommendation_calls == [_RID]


def test_get_recommendation_raises_404_when_not_found() -> None:
    svc = FakeRecommendationQueryService(recommendation=None)
    with pytest.raises(HTTPException) as exc_info:
        get_recommendation(_RID, svc)
    assert exc_info.value.status_code == 404


def test_get_recommendation_returns_status_generated() -> None:
    svc = FakeRecommendationQueryService(recommendation=_rm())
    resp = get_recommendation(_RID, svc)
    assert resp.status == "GENERATED"


def test_get_recommendation_returns_parcel_id() -> None:
    svc = FakeRecommendationQueryService(recommendation=_rm(parcel_id=_PID))
    resp = get_recommendation(_RID, svc)
    assert resp.parcel_id == _PID


def test_get_recommendation_returns_evidence_fragment_ids() -> None:
    svc = FakeRecommendationQueryService(recommendation=_rm(fragment_ids=[_FID]))
    resp = get_recommendation(_RID, svc)
    assert len(resp.evidence) == 1
    assert resp.evidence[0].fragment_id == _FID


def test_get_recommendation_returns_empty_sections() -> None:
    svc = FakeRecommendationQueryService(recommendation=_rm())
    resp = get_recommendation(_RID, svc)
    assert resp.sections == []


def test_get_recommendation_returns_derived_title() -> None:
    svc = FakeRecommendationQueryService(recommendation=_rm(crop_id="maiz"))
    resp = get_recommendation(_RID, svc)
    assert "maiz" in resp.title


def test_get_recommendation_returns_provider() -> None:
    svc = FakeRecommendationQueryService(recommendation=_rm())
    resp = get_recommendation(_RID, svc)
    assert resp.provider == "template"


def test_get_recommendation_returns_created_at() -> None:
    svc = FakeRecommendationQueryService(recommendation=_rm())
    resp = get_recommendation(_RID, svc)
    assert resp.created_at == _NOW


# ─────── tests GET /evaluaciones/{id}/recomendaciones ─────────────────────────


def test_get_recommendations_for_evaluation_returns_list() -> None:
    svc = FakeRecommendationQueryService(evaluation_list=[_rm(), _rm(recommendation_id=uuid4(), crop_id="maiz")])
    resp = get_recommendations_for_evaluation(_EID, svc)
    assert len(resp) == 2
    assert svc.get_recommendations_for_evaluation_calls == [_EID]


def test_get_recommendations_for_evaluation_returns_empty_list_when_none() -> None:
    svc = FakeRecommendationQueryService(evaluation_list=[])
    resp = get_recommendations_for_evaluation(_EID, svc)
    assert resp == []


def test_get_recommendations_for_evaluation_does_not_raise_404_for_unknown_evaluation() -> None:
    svc = FakeRecommendationQueryService(evaluation_list=[])
    resp = get_recommendations_for_evaluation(uuid4(), svc)
    assert resp == []


# ─────── tests GET /evaluaciones/{id}/recomendacion-final ─────────────────────


def test_get_final_recommendation_returns_200_when_available() -> None:
    result = FinalRecommendationResult(evaluation_found=True, recommendation=_rm())
    svc = FakeRecommendationQueryService(final_result=result)
    resp = get_final_recommendation(_EID, svc)
    assert resp.recommendation_id == _RID
    assert svc.get_final_recommendation_calls == [_EID]


def test_get_final_recommendation_raises_404_when_evaluation_not_found() -> None:
    result = FinalRecommendationResult(evaluation_found=False, recommendation=None)
    svc = FakeRecommendationQueryService(final_result=result)
    with pytest.raises(HTTPException) as exc_info:
        get_final_recommendation(_EID, svc)
    assert exc_info.value.status_code == 404


def test_get_final_recommendation_returns_202_when_evaluation_exists_but_no_recommendation() -> None:
    result = FinalRecommendationResult(evaluation_found=True, recommendation=None)
    svc = FakeRecommendationQueryService(final_result=result)
    resp = get_final_recommendation(_EID, svc)
    assert isinstance(resp, JSONResponse)
    assert resp.status_code == 202


def test_get_final_recommendation_202_body_contains_evaluation_id() -> None:
    import json

    result = FinalRecommendationResult(evaluation_found=True, recommendation=None)
    svc = FakeRecommendationQueryService(final_result=result)
    resp = get_final_recommendation(_EID, svc)
    assert isinstance(resp, JSONResponse)
    body = json.loads(resp.body)
    assert body["evaluation_id"] == str(_EID)


def test_get_final_recommendation_does_not_call_llm() -> None:
    result = FinalRecommendationResult(evaluation_found=True, recommendation=_rm())
    svc = FakeRecommendationQueryService(final_result=result)
    resp = get_final_recommendation(_EID, svc)
    assert resp.recommendation_id == _RID


# ─────────────────── tests de restricciones arquitectónicas ───────────────────


def test_router_does_not_import_llm_or_generation_code() -> None:
    forbidden = {"llm", "gemini", "vertex", "gee", "rag", "drafting"}
    imports = _imports_from(ROUTER_PATH)
    offenders = [i for i in imports if any(m in i.lower() for m in forbidden)]
    assert offenders == [], f"Router imports forbidden modules: {offenders}"


def test_query_service_does_not_import_orm_or_infrastructure() -> None:
    forbidden_prefixes = (
        "sqlalchemy",
        "via.shared.database",
        "via.bounded_contexts.recommendation.infrastructure",
    )
    offenders: list[str] = []
    for imported_name in _imports_from(QUERY_SVC_PATH):
        if any(imported_name == p or imported_name.startswith(p + ".") for p in forbidden_prefixes):
            offenders.append(imported_name)
    assert offenders == [], f"Query service imports infrastructure: {offenders}"


def test_router_declares_three_read_endpoints() -> None:
    paths = {getattr(r, "path", None) for r in router.routes}
    assert "/recomendaciones/{recommendation_id}" in paths
    assert "/evaluaciones/{evaluation_id}/recomendaciones" in paths
    assert "/evaluaciones/{evaluation_id}/recomendacion-final" in paths


# ─────────────────────── helpers ──────────────────────────────────────────────


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
