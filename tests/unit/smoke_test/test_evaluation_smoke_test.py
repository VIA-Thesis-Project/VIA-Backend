"""
Tests unitarios del smoke test demostrativo DEMO-EVAL-1.

Verifican que el script produce resultados deterministas y correctos
sin llamar a GEE, LLM, RAG ni ningún servicio externo.
"""

from __future__ import annotations

import ast
import math
from pathlib import Path
from uuid import UUID

import pytest

from scripts import evaluation_smoke_test as sut
from via.bounded_contexts.viability_evaluation.domain.value_objects import (
    CalcCondition,
    ViabilityCategory,
)

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts" / "evaluation_smoke_test.py"


# ─────────────────────────── resultado del motor MCDA ──────────────────────────


def test_smoke_evaluation_produces_two_crop_results() -> None:
    result = sut.run_smoke_evaluation()
    assert len(result["results"]) == 2
    crop_ids = {r["crop_id"] for r in result["results"]}
    assert crop_ids == {sut.CROP_MAIZ, sut.CROP_PAPA}


def test_maiz_ranks_first_with_viable_category() -> None:
    result = sut.run_smoke_evaluation()
    maiz = _crop(result, sut.CROP_MAIZ)
    assert maiz["rank_position"] == 1
    assert maiz["viability_category"] == ViabilityCategory.VIABLE
    assert maiz["calc_condition"] == CalcCondition.DEFINITIVO


def test_papa_ranks_second_with_condicional_category() -> None:
    result = sut.run_smoke_evaluation()
    papa = _crop(result, sut.CROP_PAPA)
    assert papa["rank_position"] == 2
    assert papa["viability_category"] == ViabilityCategory.CONDICIONAL
    assert papa["calc_condition"] == CalcCondition.DEFINITIVO


def test_maiz_score_is_above_papa_score() -> None:
    result = sut.run_smoke_evaluation()
    assert _crop(result, sut.CROP_MAIZ)["score"] > _crop(result, sut.CROP_PAPA)["score"]


def test_maiz_score_is_viable_threshold_or_above() -> None:
    result = sut.run_smoke_evaluation()
    assert _crop(result, sut.CROP_MAIZ)["score"] >= sut.SMOKE_SETTINGS.mcda_viable_threshold


def test_papa_score_is_between_condicional_and_viable_thresholds() -> None:
    result = sut.run_smoke_evaluation()
    score = _crop(result, sut.CROP_PAPA)["score"]
    assert sut.SMOKE_SETTINGS.mcda_condicional_threshold <= score < sut.SMOKE_SETTINGS.mcda_viable_threshold


# ─────────────────────────────── brechas ───────────────────────────────────────


def test_maiz_has_precipitation_deficit_gap() -> None:
    result = sut.run_smoke_evaluation()
    maiz = _crop(result, sut.CROP_MAIZ)
    gaps = maiz["gaps"]
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap["criterion_id"] == "precipitacion"
    assert gap["most_limiting_period"] == sut._P2
    assert gap["observed_value"] == pytest.approx(500.0)
    assert gap["optimal_limit"] == pytest.approx(600.0)
    assert gap["gap_value"] == pytest.approx(-100.0)


def test_papa_has_temperature_excess_gap() -> None:
    result = sut.run_smoke_evaluation()
    papa = _crop(result, sut.CROP_PAPA)
    gaps = papa["gaps"]
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap["criterion_id"] == "temperatura"
    assert gap["most_limiting_period"] == sut._P2
    assert gap["observed_value"] == pytest.approx(21.0)
    assert gap["optimal_limit"] == pytest.approx(18.0)
    assert gap["gap_value"] == pytest.approx(3.0)


def test_all_gaps_have_required_fields() -> None:
    result = sut.run_smoke_evaluation()
    all_gaps = [gap for crop in result["results"] for gap in crop["gaps"]]
    assert len(all_gaps) >= 1
    required = {"criterion_id", "phase_id", "most_limiting_period", "observed_value", "optimal_limit", "gap_value"}
    for gap in all_gaps:
        assert required <= set(gap.keys()), f"gap missing fields: {required - set(gap.keys())}"


# ──────────────────────────── condición de cálculo ─────────────────────────────


def test_both_crops_have_definitivo_calc_condition() -> None:
    result = sut.run_smoke_evaluation()
    for crop in result["results"]:
        assert crop["calc_condition"] == CalcCondition.DEFINITIVO, f"{crop['crop_id']} not DEFINITIVO"


def test_no_crop_has_missing_criteria() -> None:
    result = sut.run_smoke_evaluation()
    for crop in result["results"]:
        assert crop["missing_criteria"] == [], f"{crop['crop_id']} has missing criteria"


def test_no_crop_has_unrecognized_variables() -> None:
    result = sut.run_smoke_evaluation()
    for crop in result["results"]:
        assert crop["unrecognized_variables"] == []


def test_no_crop_has_limiting_factors() -> None:
    result = sut.run_smoke_evaluation()
    for crop in result["results"]:
        assert crop["limiting_factors"] == [], f"{crop['crop_id']} has unexpected limiting factors"


# ──────────────────────────── salida JSON ──────────────────────────────────────


def test_output_has_required_top_level_keys() -> None:
    result = sut.run_smoke_evaluation()
    assert {"evaluation_id", "parcel_id", "status", "results"} <= set(result.keys())


def test_output_evaluation_id_is_valid_uuid() -> None:
    result = sut.run_smoke_evaluation()
    UUID(result["evaluation_id"])


def test_output_status_is_completada() -> None:
    result = sut.run_smoke_evaluation()
    assert result["status"] == "COMPLETADA"


# ──────────────────────── determinismo ─────────────────────────────────────────


def test_ranking_is_deterministic_across_two_calls() -> None:
    first = sut.run_smoke_evaluation()
    second = sut.run_smoke_evaluation()
    for a, b in zip(first["results"], second["results"]):
        assert a["crop_id"] == b["crop_id"]
        assert a["score"] == pytest.approx(b["score"])
        assert a["rank_position"] == b["rank_position"]
        assert a["viability_category"] == b["viability_category"]


def test_maiz_score_is_numerically_stable() -> None:
    result = sut.run_smoke_evaluation()
    score = _crop(result, sut.CROP_MAIZ)["score"]
    assert math.isfinite(score)
    assert 0.0 <= score <= 1.0


def test_papa_score_is_numerically_stable() -> None:
    result = sut.run_smoke_evaluation()
    score = _crop(result, sut.CROP_PAPA)["score"]
    assert math.isfinite(score)
    assert 0.0 <= score <= 1.0


# ──────────────────────── sin servicios externos ───────────────────────────────


def test_script_does_not_import_gee() -> None:
    imports = _imports_from(SCRIPT_PATH)
    gee_modules = [imp for imp in imports if "earthengine" in imp or "ee" == imp or imp.startswith("ee.")]
    assert gee_modules == [], f"script imports GEE modules: {gee_modules}"


def test_script_does_not_import_llm_or_recommendation() -> None:
    imports = _imports_from(SCRIPT_PATH)
    forbidden = [imp for imp in imports if "recommendation" in imp or "llm" in imp or "gemini" in imp or "vertex" in imp]
    assert forbidden == [], f"script imports forbidden modules: {forbidden}"


def test_script_does_not_import_sqlalchemy() -> None:
    imports = _imports_from(SCRIPT_PATH)
    db_modules = [imp for imp in imports if "sqlalchemy" in imp or "psycopg2" in imp]
    assert db_modules == [], f"script imports DB modules: {db_modules}"


def test_script_does_not_import_fastapi() -> None:
    imports = _imports_from(SCRIPT_PATH)
    web_modules = [imp for imp in imports if "fastapi" in imp]
    assert web_modules == [], f"script imports FastAPI: {web_modules}"


def test_script_does_not_import_outbox_or_event_bus() -> None:
    imports = _imports_from(SCRIPT_PATH)
    messaging = [imp for imp in imports if "outbox" in imp or "event_bus" in imp or "relay" in imp]
    assert messaging == [], f"script imports messaging infrastructure: {messaging}"


# ──────────────────────── datos controlados ────────────────────────────────────


def test_controlled_vector_contains_variables_for_both_crops() -> None:
    vector = sut.build_controlled_vector()
    crop_ids = {v.crop_id for v in vector.variables}
    assert crop_ids == {sut.CROP_MAIZ, sut.CROP_PAPA}


def test_controlled_vector_all_variables_have_ok_status() -> None:
    vector = sut.build_controlled_vector()
    for var in vector.variables:
        assert var.status == "OK", f"variable {var.variable_name}/{var.period_key} is not OK"


def test_controlled_rulebooks_have_two_entries() -> None:
    rulebooks = sut.build_controlled_rulebooks()
    assert len(rulebooks) == 2
    assert {r.crop_id for r in rulebooks} == {sut.CROP_MAIZ, sut.CROP_PAPA}


def test_controlled_rulebooks_ahp_weights_sum_to_one() -> None:
    for rulebook in sut.build_controlled_rulebooks():
        criterion_ids = list(dict.fromkeys(c.criterion_id for c in rulebook.criteria))
        total_ahp = sum(
            next(c.w_ahp for c in rulebook.criteria if c.criterion_id == cid)
            for cid in criterion_ids
        )
        assert abs(total_ahp - 1.0) < 0.001, f"{rulebook.crop_id} AHP weights don't sum to 1"


def test_vector_evaluation_id_is_accepted() -> None:
    custom_id = UUID("aaaaaaaa-0000-4000-8000-000000000001")
    vector = sut.build_controlled_vector(evaluation_id=custom_id)
    assert vector.evaluation_id == custom_id


# ─────────────────────────── helpers ───────────────────────────────────────────


def _crop(result: dict, crop_id: str) -> dict:
    for crop in result["results"]:
        if crop["crop_id"] == crop_id:
            return crop
    raise KeyError(f"{crop_id} not found in results")


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
