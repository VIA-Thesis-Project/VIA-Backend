"""E2E tests for lote 25A: MCDA evaluation flow (HTTP → saga → persistence → query).

Flow: POST /evaluaciones → Process Manager → ControlledExtractionClient (no GEE) →
      Evaluation Consumer (ControlledRulebookEvaluationPort, no LLM) →
      LockFreeRelayWorker → EVALUACION_COMPLETADA →
      GET /evaluaciones/{id}/resultado-mcda → ranking + gaps from DB.

No real GEE, LLM, Recommendation, or network calls.
Results come from the query endpoint, NOT from in-memory test objects.
"""

from __future__ import annotations

import sys

import pytest

from tests.e2e.conftest import CROP_MAIZ, CROP_PAPA
from via.shared.orchestration.evaluation_process_manager.states import EvaluationSagaStatus


# ──────────────────────────── saga completion ──────────────────────────────────


def test_saga_reaches_evaluacion_completada(completed_e2e_evaluation) -> None:
    """Saga must reach EVALUACION_COMPLETADA (not FALLIDA) for MCDA results to be available."""
    assert completed_e2e_evaluation["final_status"] == EvaluationSagaStatus.EVALUACION_COMPLETADA.value


def test_estado_endpoint_returns_200(completed_e2e_evaluation) -> None:
    assert completed_e2e_evaluation["estado_response"].status_code == 200


def test_estado_reflects_evaluacion_completada(completed_e2e_evaluation) -> None:
    body = completed_e2e_evaluation["estado_response"].json()
    assert body["status"] == EvaluationSagaStatus.EVALUACION_COMPLETADA.value


# ──────────────────────────── resultado-mcda endpoint ─────────────────────────


def test_resultado_mcda_returns_200(completed_e2e_evaluation) -> None:
    assert completed_e2e_evaluation["mcda_response"].status_code == 200


def test_resultado_mcda_has_two_ranked_crops(completed_e2e_evaluation) -> None:
    results = completed_e2e_evaluation["mcda_response"].json()["results"]
    assert len(results) >= 2, f"expected ≥2 crop results, got {len(results)}"


def test_crop_ids_include_maiz_and_papa(completed_e2e_evaluation) -> None:
    results = completed_e2e_evaluation["mcda_response"].json()["results"]
    crop_ids = {r["crop_id"] for r in results}
    assert CROP_MAIZ in crop_ids, "maiz_amarillo_duro missing from results"
    assert CROP_PAPA in crop_ids, "papa missing from results"


def test_maiz_has_rank_position_1(completed_e2e_evaluation) -> None:
    results = completed_e2e_evaluation["mcda_response"].json()["results"]
    maiz = _find_crop(results, CROP_MAIZ)
    assert maiz["rank_position"] == 1, f"maiz rank_position={maiz['rank_position']}, expected 1"


def test_papa_has_rank_position_2(completed_e2e_evaluation) -> None:
    results = completed_e2e_evaluation["mcda_response"].json()["results"]
    papa = _find_crop(results, CROP_PAPA)
    assert papa["rank_position"] == 2, f"papa rank_position={papa['rank_position']}, expected 2"


def test_rank_positions_are_ordered_by_score(completed_e2e_evaluation) -> None:
    results = completed_e2e_evaluation["mcda_response"].json()["results"]
    maiz = _find_crop(results, CROP_MAIZ)
    papa = _find_crop(results, CROP_PAPA)
    assert maiz["score"] > papa["score"], (
        f"maiz score={maiz['score']} should be > papa score={papa['score']}"
    )


def test_maiz_viability_category_is_viable(completed_e2e_evaluation) -> None:
    results = completed_e2e_evaluation["mcda_response"].json()["results"]
    maiz = _find_crop(results, CROP_MAIZ)
    assert maiz["viability_category"] == "VIABLE", f"maiz category={maiz['viability_category']}"


def test_papa_viability_category_is_condicional(completed_e2e_evaluation) -> None:
    results = completed_e2e_evaluation["mcda_response"].json()["results"]
    papa = _find_crop(results, CROP_PAPA)
    assert papa["viability_category"] == "CONDICIONAL", f"papa category={papa['viability_category']}"


# ──────────────────────────── gaps ────────────────────────────────────────────


def test_at_least_one_gap_exists_overall(completed_e2e_evaluation) -> None:
    results = completed_e2e_evaluation["mcda_response"].json()["results"]
    all_gaps = [gap for r in results for gap in r["gaps"]]
    assert len(all_gaps) >= 1, "Expected at least one agronomic gap"


def test_maiz_has_precipitation_deficit_gap(completed_e2e_evaluation) -> None:
    results = completed_e2e_evaluation["mcda_response"].json()["results"]
    maiz = _find_crop(results, CROP_MAIZ)
    precip_gaps = [g for g in maiz["gaps"] if g["criterion_id"] == "precipitacion"]
    assert len(precip_gaps) >= 1, "maiz should have a precipitation gap (Q2=480mm < optimal 600mm)"
    gap = precip_gaps[0]
    assert gap["gap_value"] < 0, f"maiz precipitation gap should be negative (deficit), got {gap['gap_value']}"


def test_papa_has_temperature_excess_gap(completed_e2e_evaluation) -> None:
    results = completed_e2e_evaluation["mcda_response"].json()["results"]
    papa = _find_crop(results, CROP_PAPA)
    temp_gaps = [g for g in papa["gaps"] if g["criterion_id"] == "temperatura"]
    assert len(temp_gaps) >= 1, "papa should have a temperature gap (Q2=21°C > optimal 18°C)"
    gap = temp_gaps[0]
    assert gap["gap_value"] > 0, f"papa temperature gap should be positive (excess), got {gap['gap_value']}"


def test_all_gaps_have_required_fields(completed_e2e_evaluation) -> None:
    results = completed_e2e_evaluation["mcda_response"].json()["results"]
    required = {"criterion_id", "phase_id", "most_limiting_period", "observed_value", "optimal_limit", "gap_value"}
    for r in results:
        for gap in r["gaps"]:
            missing = required - set(gap.keys())
            assert not missing, f"{r['crop_id']} gap missing fields: {missing}"


# ──────────────────────────── resultado-mcda excludes Recommendation ──────────


def test_resultado_mcda_has_no_recommendation_field(completed_e2e_evaluation) -> None:
    body = completed_e2e_evaluation["mcda_response"].json()
    assert "recommendation" not in body, "resultado-mcda should not expose Recommendation"
    assert "recommendations" not in body, "resultado-mcda should not expose Recommendation"
    for r in body.get("results", []):
        assert "recommendation" not in r, f"crop result for {r['crop_id']} should not have recommendation"


def test_resultado_mcda_does_not_expose_internal_ids(completed_e2e_evaluation) -> None:
    body = completed_e2e_evaluation["mcda_response"].json()
    assert "outbox_id" not in body
    assert "saga_id" not in body


# ──────────────────────────── no real GEE call ────────────────────────────────


def test_controlled_extraction_client_was_used(completed_e2e_evaluation, controlled_extraction_client) -> None:
    assert controlled_extraction_client.call_count > 0, (
        "ControlledExtractionClient.extract_variable was never called — extraction did not run"
    )


def test_gee_earthengine_not_imported(completed_e2e_evaluation) -> None:
    for mod_name in sys.modules:
        assert "earthengine" not in mod_name, f"earthengine module imported: {mod_name}"
        assert mod_name != "ee", "ee (earthengine-api) module imported"


# ──────────────────────────── no real LLM call ────────────────────────────────


def test_no_llm_module_imported(completed_e2e_evaluation) -> None:
    llm_indicators = ("openai", "anthropic", "google.generativeai", "vertexai", "transformers")
    for mod_name in sys.modules:
        for indicator in llm_indicators:
            assert not mod_name.startswith(indicator), f"LLM module imported: {mod_name}"


# ──────────────────────────── persistence integrity ───────────────────────────


def test_results_come_from_query_endpoint_not_in_memory(completed_e2e_evaluation, e2e_session_factory) -> None:
    """Verify results were persisted to SQLite and served by the query endpoint (not in-memory objects).

    Queries evaluation_results via EvaluationQueryRepository (same path as the API) on a
    session opened AFTER all relay waves and HTTP requests complete.
    """
    from via.bounded_contexts.viability_evaluation.infrastructure.evaluation_query_repository import (
        EvaluationQueryRepository,
    )

    evaluation_id = completed_e2e_evaluation["evaluation_id"]
    session = e2e_session_factory()
    try:
        repo = EvaluationQueryRepository(session)
        crop_results = repo.find_crop_results(evaluation_id)
    finally:
        session.close()

    assert len(crop_results) >= 2, f"Expected ≥2 persisted crop results, got {len(crop_results)}"
    stored_crop_ids = {r.crop_id for r in crop_results}
    assert CROP_MAIZ in stored_crop_ids
    assert CROP_PAPA in stored_crop_ids


# ──────────────────────────── helpers ─────────────────────────────────────────


def _find_crop(results: list[dict], crop_id: str) -> dict:
    for r in results:
        if r["crop_id"] == crop_id:
            return r
    raise AssertionError(f"Crop '{crop_id}' not found in results: {[r['crop_id'] for r in results]}")
