"""
Smoke test demostrativo del motor MCDA difuso de VIA — DEMO-EVAL-1.

Ejecuta el motor de evaluación con datos controlados para dos cultivos
(maiz_amarillo_duro y papa) sin GEE, LLM, RAG ni servicios externos.

Uso:
    python scripts/evaluation_smoke_test.py

Salida: JSON legible con ranking, scores, brechas y factores limitantes.
"""

from __future__ import annotations

import json
import sys
from uuid import UUID

from via.bounded_contexts.viability_evaluation.application.command_service import (
    ExecuteEvaluationCommand,
    McdaRuntimeSettings,
    PureMcdaEvaluationEngine,
)
from via.bounded_contexts.viability_evaluation.application.ports import (
    AgroenvVariableData,
    AgroenvVectorData,
    EvaluationCriterionSpec,
    RulebookEvaluationData,
)
from via.bounded_contexts.viability_evaluation.domain.evaluation import Evaluation

# ──────────────────────────────── identidades fijas ────────────────────────────

_EVALUATION_ID = UUID("00000000-0000-4000-8000-000000000001")
_PARCEL_ID = UUID("00000000-0000-4000-8000-000000000002")

CROP_MAIZ = "maiz_amarillo_duro"
CROP_PAPA = "papa"

_PHASE = "vegetativo"
_P1 = "2026-Q1"
_P2 = "2026-Q2"

# ────────────────────────── configuración MCDA controlada ──────────────────────
# min_series_length=3 con solo 2 periodos → fallback total a pesos AHP (esperado)

SMOKE_SETTINGS = McdaRuntimeSettings(
    mcda_alpha=0.7,
    mcda_min_temporal_series_length=3,
    mcda_entropy_min_divergence=1e-9,
    mcda_viable_threshold=0.70,
    mcda_condicional_threshold=0.40,
    mcda_penalize_epsilon=0.01,
)

# ──────────────────────────── API pública del módulo ───────────────────────────


def build_controlled_rulebooks() -> list[RulebookEvaluationData]:
    """Retorna rulebooks controlados para maíz y papa sin acceder a base de datos."""
    return [_rulebook_maiz(), _rulebook_papa()]


def build_controlled_vector(evaluation_id: UUID | None = None) -> AgroenvVectorData:
    """Retorna vector agroambiental controlado sin llamadas a GEE."""
    eid = evaluation_id or _EVALUATION_ID
    return AgroenvVectorData(
        evaluation_id=eid,
        parcel_id=_PARCEL_ID,
        variables=_variables_maiz() + _variables_papa(),
    )


def run_smoke_evaluation() -> dict:
    """
    Ejecuta el motor MCDA con datos controlados y retorna resultado serializable.

    Resultados esperados (deterministas):
      - maiz_amarillo_duro: score ≈ 0.871 → VIABLE,      rank_position=1
      - papa:               score ≈ 0.536 → CONDICIONAL, rank_position=2
      - maiz gap: precipitacion Q2 500mm → deficit -100mm
      - papa gap: temperatura Q2 21°C → exceso +3°C

    No se usa GEE, LLM, RAG, base de datos ni ningún servicio externo.
    """
    command = ExecuteEvaluationCommand(
        evaluation_id=_EVALUATION_ID,
        extraction_result={
            "crop_candidates": [CROP_MAIZ, CROP_PAPA],
            "temporal_window": {"start": "2026-01-01", "end": "2026-06-30"},
        },
    )
    vector = build_controlled_vector()
    rulebooks = build_controlled_rulebooks()
    engine = PureMcdaEvaluationEngine()
    evaluation = engine.evaluate(command, vector, rulebooks, SMOKE_SETTINGS)
    return _serialise(evaluation)


def main() -> int:
    """Punto de entrada del smoke test demostrativo DEMO-EVAL-1."""
    result = run_smoke_evaluation()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


# ─────────────────────────── datos controlados — maíz ─────────────────────────
#
# Maíz Amarillo Duro — resultados esperados:
#   temperatura: trapezoid(18,22,30,35), Q1=25°C→1.0, Q2=27°C→1.0 → WGM=1.0
#   precipitacion: trapezoid(400,600,900,1100), Q1=700mm→1.0, Q2=500mm→0.5
#     WGM temporal = sqrt(1.0 * 0.5) = 0.7071
#   score = WGM(1.0^0.6, 0.707^0.4) ≈ 0.871 → VIABLE, rank 1
#   gap: precipitacion Q2 500mm, optimal_limit=600, gap=-100 (déficit)


def _rulebook_maiz() -> RulebookEvaluationData:
    return RulebookEvaluationData(
        crop_id=CROP_MAIZ,
        rulebook_id=UUID("00000000-0000-4000-8000-000000000010"),
        version=1,
        criteria=[
            EvaluationCriterionSpec(
                criterion_id="temperatura",
                crop_id=CROP_MAIZ,
                phase_id=_PHASE,
                variable_name="temperatura_media",
                w_ahp=0.6,
                phase_weight=1.0,
                temporal_periods=[
                    {"period_key": _P1, "temporal_weight": 0.5},
                    {"period_key": _P2, "temporal_weight": 0.5},
                ],
                membership_fn={"type": "TRAPEZOIDAL", "a": 18.0, "b": 22.0, "c": 30.0, "d": 35.0},
                critical_policy="NONE",
                penalty_factor=None,
                doc_source="Manual Maíz INIA 2024, Cap. 3",
            ),
            EvaluationCriterionSpec(
                criterion_id="precipitacion",
                crop_id=CROP_MAIZ,
                phase_id=_PHASE,
                variable_name="precipitacion_acumulada",
                w_ahp=0.4,
                phase_weight=1.0,
                temporal_periods=[
                    {"period_key": _P1, "temporal_weight": 0.5},
                    {"period_key": _P2, "temporal_weight": 0.5},
                ],
                membership_fn={"type": "TRAPEZOIDAL", "a": 400.0, "b": 600.0, "c": 900.0, "d": 1100.0},
                critical_policy="NONE",
                penalty_factor=None,
                doc_source="Manual Maíz INIA 2024, Cap. 4",
            ),
        ],
    )


def _variables_maiz() -> list[AgroenvVariableData]:
    return [
        _var(CROP_MAIZ, "temperatura", "temperatura_media", _P1, 25.0, "°C"),
        _var(CROP_MAIZ, "temperatura", "temperatura_media", _P2, 27.0, "°C"),
        _var(CROP_MAIZ, "precipitacion", "precipitacion_acumulada", _P1, 700.0, "mm"),
        _var(CROP_MAIZ, "precipitacion", "precipitacion_acumulada", _P2, 500.0, "mm"),
    ]


# ─────────────────────────── datos controlados — papa ─────────────────────────
#
# Papa — resultados esperados:
#   temperatura: trapezoid(10,14,18,22), Q1=20°C→0.5, Q2=21°C→0.25
#     WGM temporal = sqrt(0.5 * 0.25) = 0.5^0.5 * 0.25^0.5 ≈ 0.3536
#   precipitacion: trapezoid(400,600,900,1100), Q1=700mm→1.0, Q2=650mm→1.0 → WGM=1.0
#   score = WGM(0.3536^0.6, 1.0^0.4) ≈ 0.536 → CONDICIONAL, rank 2
#   gap: temperatura Q2 21°C, optimal_limit=18(c), gap=+3 (exceso)


def _rulebook_papa() -> RulebookEvaluationData:
    return RulebookEvaluationData(
        crop_id=CROP_PAPA,
        rulebook_id=UUID("00000000-0000-4000-8000-000000000020"),
        version=1,
        criteria=[
            EvaluationCriterionSpec(
                criterion_id="temperatura",
                crop_id=CROP_PAPA,
                phase_id=_PHASE,
                variable_name="temperatura_media",
                w_ahp=0.6,
                phase_weight=1.0,
                temporal_periods=[
                    {"period_key": _P1, "temporal_weight": 0.5},
                    {"period_key": _P2, "temporal_weight": 0.5},
                ],
                membership_fn={"type": "TRAPEZOIDAL", "a": 10.0, "b": 14.0, "c": 18.0, "d": 22.0},
                critical_policy="NONE",
                penalty_factor=None,
                doc_source="Manual Papa INIA 2023, Cap. 2",
            ),
            EvaluationCriterionSpec(
                criterion_id="precipitacion",
                crop_id=CROP_PAPA,
                phase_id=_PHASE,
                variable_name="precipitacion_acumulada",
                w_ahp=0.4,
                phase_weight=1.0,
                temporal_periods=[
                    {"period_key": _P1, "temporal_weight": 0.5},
                    {"period_key": _P2, "temporal_weight": 0.5},
                ],
                membership_fn={"type": "TRAPEZOIDAL", "a": 400.0, "b": 600.0, "c": 900.0, "d": 1100.0},
                critical_policy="NONE",
                penalty_factor=None,
                doc_source="Manual Papa INIA 2023, Cap. 4",
            ),
        ],
    )


def _variables_papa() -> list[AgroenvVariableData]:
    return [
        _var(CROP_PAPA, "temperatura", "temperatura_media", _P1, 20.0, "°C"),
        _var(CROP_PAPA, "temperatura", "temperatura_media", _P2, 21.0, "°C"),
        _var(CROP_PAPA, "precipitacion", "precipitacion_acumulada", _P1, 700.0, "mm"),
        _var(CROP_PAPA, "precipitacion", "precipitacion_acumulada", _P2, 650.0, "mm"),
    ]


# ──────────────────────────── utilidades ───────────────────────────────────────


def _var(
    crop_id: str,
    criterion_id: str,
    variable_name: str,
    period_key: str,
    value: float,
    unit: str,
) -> AgroenvVariableData:
    return AgroenvVariableData(
        variable_name=variable_name,
        criterion_id=criterion_id,
        crop_id=crop_id,
        phase_id=_PHASE,
        period_key=period_key,
        value=value,
        unit=unit,
        status="OK",
        dataset_key="smoke_test_controlled",
        band=variable_name,
        source="controlled_fixture",
    )


def _serialise(evaluation: Evaluation) -> dict:
    return {
        "evaluation_id": str(evaluation.id),
        "parcel_id": str(evaluation.parcel_id),
        "status": "COMPLETADA",
        "results": [
            {
                "crop_id": result.crop_id,
                "score": round(float(result.score), 6) if result.score is not None else None,
                "rank_position": result.rank_position,
                "calc_condition": result.calc_condition.value,
                "viability_category": result.viability_category.value,
                "missing_criteria": result.missing_criteria,
                "unrecognized_variables": result.unrecognized_variables,
                "limiting_factors": [
                    {
                        "criterion_id": lf.criterion_id,
                        "phase_id": lf.phase_id,
                        "policy": lf.policy.value,
                        "penalty_factor": lf.penalty_factor,
                        "observed_value": float(lf.observed_value),
                        "optimal_limit": float(lf.optimal_limit),
                        "membership": float(lf.membership),
                        "doc_source": lf.doc_source,
                    }
                    for lf in result.limiting_factors
                ],
                "gaps": [
                    {
                        "criterion_id": gap.criterion_id,
                        "phase_id": gap.phase_id,
                        "most_limiting_period": gap.most_limiting_period,
                        "observed_value": float(gap.observed_value),
                        "optimal_limit": float(gap.optimal_limit),
                        "gap_value": float(gap.gap_value),
                    }
                    for gap in result.gaps
                ],
            }
            for result in evaluation.crop_results
        ],
    }


if __name__ == "__main__":
    sys.exit(main())
