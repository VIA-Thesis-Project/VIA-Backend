"""Unit tests for evaluation status and MCDA result query endpoints (task 20A).

Verifies endpoint behavior using fake query services — no DB or MCDA
recalculation involved. All values come from pre-built read model stubs.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from via.bounded_contexts.viability_evaluation.application.ports import (
    CropResultReadModel,
    EvaluationMcdaResultReadModel,
    EvaluationStatusReadModel,
    GapReadModel,
    LimitingFactorReadModel,
)
from via.bounded_contexts.viability_evaluation.interfaces.evaluation_router import (
    get_evaluation_status,
    get_mcda_result,
    router,
)
from via.shared.orchestration.evaluation_process_manager.states import EvaluationSagaStatus


ROOT = Path(__file__).resolve().parents[3]
ROUTER_PATH = ROOT / "via" / "bounded_contexts" / "viability_evaluation" / "interfaces" / "evaluation_router.py"
QUERY_SVC_PATH = ROOT / "via" / "bounded_contexts" / "viability_evaluation" / "application" / "query_service.py"

_EID = UUID("00000000-0000-4000-8000-000000000001")
_NOW = datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc)


# ─────────────────────── test doubles ─────────────────────────────────────────


class FakeQueryService:
    """Fake query service recording calls for test assertions."""

    def __init__(self, *, status_rm=None, result_rm=None) -> None:
        self._status_rm = status_rm
        self._result_rm = result_rm
        self.status_calls: list[UUID] = []
        self.result_calls: list[UUID] = []

    def get_evaluation_status(self, evaluation_id: UUID):  # noqa: ANN201
        self.status_calls.append(evaluation_id)
        return self._status_rm

    def get_mcda_result(self, evaluation_id: UUID):  # noqa: ANN201
        self.result_calls.append(evaluation_id)
        return self._result_rm


# ─────────────────────── fixture factories ────────────────────────────────────


def _status_rm(
    status: str = EvaluationSagaStatus.EVALUACION_COMPLETADA.value,
    failure_reason: str | None = None,
) -> EvaluationStatusReadModel:
    return EvaluationStatusReadModel(
        evaluation_id=_EID,
        status=status,
        current_phase=status,
        last_transition=_NOW,
        failure_reason=failure_reason,
    )


def _result_rm(
    status: str = EvaluationSagaStatus.EVALUACION_COMPLETADA.value,
    results: list[CropResultReadModel] | None = None,
    failure_reason: str | None = None,
) -> EvaluationMcdaResultReadModel:
    return EvaluationMcdaResultReadModel(
        evaluation_id=_EID,
        status=status,
        results=results or [],
        failure_reason=failure_reason,
    )


def _gap() -> GapReadModel:
    return GapReadModel("precipitacion", "vegetativo", "2026-Q2", 500.0, 600.0, -100.0)


def _factor() -> LimitingFactorReadModel:
    return LimitingFactorReadModel("temperatura", "vegetativo", "PENALIZE", 0.5, 18.0, 22.0, 0.0, "INIA")


def _crop(
    crop_id: str = "maiz",
    rank: int | None = 1,
    score: float | None = 0.87,
    calc: str = "DEFINITIVO",
    cat: str = "VIABLE",
    gaps: list[GapReadModel] | None = None,
    factors: list[LimitingFactorReadModel] | None = None,
) -> CropResultReadModel:
    return CropResultReadModel(
        crop_id=crop_id,
        score=score,
        rank_position=rank,
        calc_condition=calc,
        viability_category=cat,
        gaps=gaps or [],
        limiting_factors=factors or [],
    )


# ──────────────────── tests endpoint /estado ──────────────────────────────────


def test_get_status_returns_existing_evaluation() -> None:
    svc = FakeQueryService(status_rm=_status_rm())
    resp = get_evaluation_status(_EID, svc)
    assert resp.evaluation_id == _EID
    assert resp.status == EvaluationSagaStatus.EVALUACION_COMPLETADA.value
    assert svc.status_calls == [_EID]


def test_get_status_raises_404_when_evaluation_not_found() -> None:
    svc = FakeQueryService(status_rm=None)
    with pytest.raises(HTTPException) as exc_info:
        get_evaluation_status(_EID, svc)
    assert exc_info.value.status_code == 404


def test_get_status_includes_current_phase() -> None:
    svc = FakeQueryService(status_rm=_status_rm(status=EvaluationSagaStatus.INICIADA.value))
    resp = get_evaluation_status(_EID, svc)
    assert resp.current_phase == EvaluationSagaStatus.INICIADA.value


def test_get_status_returns_failure_reason_for_failed_evaluation() -> None:
    rm = _status_rm(status=EvaluationSagaStatus.FALLIDA.value, failure_reason="Timeout en GEE")
    svc = FakeQueryService(status_rm=rm)
    resp = get_evaluation_status(_EID, svc)
    assert resp.status == EvaluationSagaStatus.FALLIDA.value
    assert resp.failure_reason == "Timeout en GEE"


def test_get_status_returns_last_transition_timestamp() -> None:
    svc = FakeQueryService(status_rm=_status_rm())
    resp = get_evaluation_status(_EID, svc)
    assert resp.last_transition == _NOW


# ──────────────────── tests endpoint /resultado-mcda ──────────────────────────


def test_get_mcda_result_returns_ranking_and_gaps_for_completed_evaluation() -> None:
    results = [_crop(gaps=[_gap()])]
    svc = FakeQueryService(result_rm=_result_rm(results=results))
    resp = get_mcda_result(_EID, svc)
    assert len(resp.results) == 1
    assert resp.results[0].crop_id == "maiz"
    assert resp.results[0].rank_position == 1
    assert resp.results[0].gaps[0].gap_value == pytest.approx(-100.0)


def test_get_mcda_result_raises_404_when_evaluation_not_found() -> None:
    svc = FakeQueryService(result_rm=None)
    with pytest.raises(HTTPException) as exc_info:
        get_mcda_result(_EID, svc)
    assert exc_info.value.status_code == 404


def test_get_mcda_result_returns_202_for_iniciada() -> None:
    svc = FakeQueryService(result_rm=_result_rm(status=EvaluationSagaStatus.INICIADA.value))
    resp = get_mcda_result(_EID, svc)
    assert isinstance(resp, JSONResponse)
    assert resp.status_code == 202


def test_get_mcda_result_returns_202_for_extraccion_completada() -> None:
    svc = FakeQueryService(result_rm=_result_rm(status=EvaluationSagaStatus.EXTRACCION_COMPLETADA.value))
    resp = get_mcda_result(_EID, svc)
    assert isinstance(resp, JSONResponse)
    assert resp.status_code == 202


def test_get_mcda_result_returns_failure_reason_for_failed_evaluation() -> None:
    rm = _result_rm(status=EvaluationSagaStatus.FALLIDA.value, failure_reason="Fallo en extracción")
    svc = FakeQueryService(result_rm=rm)
    resp = get_mcda_result(_EID, svc)
    assert resp.failure_reason == "Fallo en extracción"
    assert resp.results == []


def test_get_mcda_result_rank_position_none_for_unranked_crops() -> None:
    results = [
        _crop(rank=1, cat="VIABLE"),
        _crop(crop_id="papa", rank=None, score=None, calc="NO_CONCLUYENTE", cat="NO_VIABLE"),
    ]
    svc = FakeQueryService(result_rm=_result_rm(results=results))
    resp = get_mcda_result(_EID, svc)
    papa = next(r for r in resp.results if r.crop_id == "papa")
    assert papa.rank_position is None


def test_get_mcda_result_does_not_include_recommendation() -> None:
    svc = FakeQueryService(result_rm=_result_rm(results=[_crop()]))
    resp = get_mcda_result(_EID, svc)
    resp_dict = resp.model_dump()
    assert "recommendation" not in resp_dict
    assert "recomendacion" not in resp_dict


def test_get_mcda_result_available_when_evaluacion_completada_without_recommendation() -> None:
    svc = FakeQueryService(
        result_rm=_result_rm(status=EvaluationSagaStatus.EVALUACION_COMPLETADA.value, results=[_crop()])
    )
    resp = get_mcda_result(_EID, svc)
    assert resp.status == EvaluationSagaStatus.EVALUACION_COMPLETADA.value
    assert len(resp.results) == 1


def test_get_mcda_result_returns_limiting_factors() -> None:
    results = [_crop(factors=[_factor()])]
    svc = FakeQueryService(result_rm=_result_rm(results=results))
    resp = get_mcda_result(_EID, svc)
    lf = resp.results[0].limiting_factors[0]
    assert lf.criterion_id == "temperatura"
    assert lf.policy == "PENALIZE"
    assert lf.penalty_factor == pytest.approx(0.5)


# ─────────────────── tests de restricciones arquitectónicas ───────────────────


def test_router_does_not_import_llm_or_recommendation() -> None:
    forbidden = {"llm", "gemini", "vertex", "recommendation", "rag"}
    imports = _imports_from(ROUTER_PATH)
    offenders = [i for i in imports if any(m in i.lower() for m in forbidden)]
    assert offenders == [], f"Router imports forbidden modules: {offenders}"


def test_query_service_does_not_reference_mcda_calculation_code() -> None:
    forbidden_symbols = {"PureMcdaEvaluationEngine", "TrapezoidalMembershipFunction", "weighted_geometric_mean"}
    source = QUERY_SVC_PATH.read_text(encoding="utf-8")
    offenders = [sym for sym in forbidden_symbols if sym in source]
    assert offenders == [], f"Query service references MCDA calculation code: {offenders}"


def test_router_declares_estado_and_resultado_mcda_endpoints() -> None:
    paths = {getattr(r, "path", None) for r in router.routes}
    assert "/evaluaciones/{evaluation_id}/estado" in paths
    assert "/evaluaciones/{evaluation_id}/resultado-mcda" in paths


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
