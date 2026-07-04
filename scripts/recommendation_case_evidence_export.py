"""Export a traceable recommendation case for report screenshots.

This script builds a small, deterministic case showing:

MCDA result -> gap analysis -> documentary evidence -> simulated LLM draft
-> deterministic quality control -> final visible recommendation.

It uses the real recommendation gap analysis and quality-control functions, but
does not call an LLM, does not connect to a database, and does not require API
keys. The LLM output is intentionally simulated so the evidence can be
reproduced during thesis writing.

Usage:
    python scripts/recommendation_case_evidence_export.py
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5, NAMESPACE_URL

from via.bounded_contexts.recommendation.application.command_service import (
    _quality_control_structured_output,
    _render_visible_text,
)
from via.bounded_contexts.recommendation.application.gap_analysis import analyse_gaps
from via.bounded_contexts.recommendation.application.ports import (
    CropEvaluationResultData,
    EvidenceData,
    GapData,
    LimitingFactorData,
)


DEFAULT_OUT = Path("artifacts/recommendation_case_evidence")
EVALUATION_ID = UUID("11111111-2222-4333-8444-555555555555")
CROP_ID = "maiz_amarillo_duro"


def _uuid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"via-recommendation-case:{name}")


def _mcda_case() -> CropEvaluationResultData:
    gaps = [
        GapData(
            criterion_id="deficit_hidrico",
            criterion_name="deficit_hidrico",
            criterion_label="Déficit hídrico",
            criterion_group="riego",
            phase_id="espigamiento_floracion",
            phase_name="Espigamiento y floración",
            most_limiting_period="espigamiento_floracion_climate",
            observed_value=620.0,
            optimal_limit=300.0,
            gap_value=320.0,
            gap_direction="above_optimum",
            severity="alta",
            unit="mm",
            recommendation_topic="manejo de riego y humedad en floración",
            intervention_class="CORRECTABLE",
        ),
        GapData(
            criterion_id="reaccion_suelo_ph",
            criterion_name="reaccion_suelo_ph",
            criterion_label="pH del suelo",
            criterion_group="suelo",
            phase_id="germinacion_emergencia",
            phase_name="Germinación y emergencia",
            most_limiting_period="germinacion_emergencia_climate",
            observed_value=8.3,
            optimal_limit=7.2,
            gap_value=1.1,
            gap_direction="above_optimum",
            severity="media",
            unit="pH",
            recommendation_topic="validación y corrección gradual de pH",
            intervention_class="CORRECTABLE",
        ),
        GapData(
            criterion_id="aptitud_altitudinal",
            criterion_name="aptitud_altitudinal",
            criterion_label="Aptitud altitudinal",
            criterion_group="topografia",
            phase_id="germinacion_emergencia",
            phase_name="Germinación y emergencia",
            most_limiting_period="germinacion_emergencia_climate",
            observed_value=980.0,
            optimal_limit=600.0,
            gap_value=380.0,
            gap_direction="above_optimum",
            severity="media",
            unit="m",
            recommendation_topic="restricción altitudinal",
            intervention_class="STRUCTURAL",
        ),
    ]
    limiting_factors = [
        LimitingFactorData(
            criterion_id="aptitud_altitudinal",
            criterion_name="aptitud_altitudinal",
            criterion_label="Aptitud altitudinal",
            criterion_group="topografia",
            phase_id="germinacion_emergencia",
            phase_name="Germinación y emergencia",
            policy="PENALIZE",
            penalty_factor=0.65,
            observed_value=980.0,
            optimal_limit=600.0,
            membership=0.0,
            unit="m",
            severity="media",
            intervention_class="STRUCTURAL",
        )
    ]
    return CropEvaluationResultData(
        crop_id=CROP_ID,
        score=0.58,
        rank_position=1,
        calc_condition="CONDICIONAL",
        viability_category="CONDICIONAL",
        gaps=gaps,
        limiting_factors=limiting_factors,
    )


def _evidence() -> list[EvidenceData]:
    return [
        EvidenceData(
            fragment_id=_uuid("evidence-riego"),
            document_id=_uuid("doc-riego"),
            source_filename="riego.md",
            source_file_id="file-riego-maiz",
            crop_tags=[CROP_ID],
            score=0.91,
            text=(
                "El manejo del agua en maíz debe evitar déficit durante floración y cuajado; "
                "el riego oportuno mantiene humedad disponible y reduce estrés hídrico."
            ),
        ),
        EvidenceData(
            fragment_id=_uuid("evidence-suelo"),
            document_id=_uuid("doc-suelo"),
            source_filename="suelo.md",
            source_file_id="file-suelo-maiz",
            crop_tags=[CROP_ID],
            score=0.88,
            text=(
                "Para suelos con pH alcalino se recomienda validar con análisis de suelo, "
                "mejorar materia orgánica y planificar enmiendas de corrección gradual."
            ),
        ),
        EvidenceData(
            fragment_id=_uuid("evidence-topografia"),
            document_id=_uuid("doc-topografia"),
            source_filename="topografia.md",
            source_file_id="file-topografia-maiz",
            crop_tags=[CROP_ID],
            score=0.82,
            text=(
                "La altitud y la pendiente son condiciones topográficas de sitio; no se corrigen "
                "con manejo agronómico, aunque sus efectos pueden considerarse en la decisión."
            ),
        ),
    ]


def _llm_draft(evidence: list[EvidenceData]) -> dict[str, Any]:
    by_file = {item.source_filename: item for item in evidence}
    return {
        "schema_version": "recommendation_structured_v1",
        "summary": (
            "La evaluación del maíz amarillo duro es condicional. Las acciones deben priorizar "
            "el manejo hídrico en floración, la validación del pH alcalino y la advertencia de "
            "la restricción altitudinal."
        ),
        "gap_recommendations": [
            {
                "gap_key": "deficit_hidrico:espigamiento_floracion",
                "criterion_id": "deficit_hidrico",
                "criterion_name": "deficit_hidrico",
                "criterion_label": "Déficit hídrico",
                "criterion_group": "riego",
                "phase_id": "espigamiento_floracion",
                "phase_name": "Espigamiento y floración",
                "gap_direction": "above_optimum",
                "severity": "alta",
                "observed_value": 620.0,
                "optimal_limit": 300.0,
                "gap_value": 320.0,
                "recommendation": (
                    "Priorizar riego oportuno en floración, verificar humedad disponible y evitar "
                    "periodos prolongados de estrés hídrico."
                ),
                "rationale": "La brecha hídrica ocurre en una fase sensible para rendimiento.",
                "confidence": "alta",
                "limitations": None,
                "evidence_used": [_ref(by_file["riego.md"], "El riego oportuno reduce estrés hídrico.")],
            },
            {
                "gap_key": "reaccion_suelo_ph:germinacion_emergencia",
                "criterion_id": "reaccion_suelo_ph",
                "criterion_name": "reaccion_suelo_ph",
                "criterion_label": "pH del suelo",
                "criterion_group": "suelo",
                "phase_id": "germinacion_emergencia",
                "phase_name": "Germinación y emergencia",
                "gap_direction": "above_optimum",
                "severity": "media",
                "observed_value": 8.3,
                "optimal_limit": 7.2,
                "gap_value": 1.1,
                "recommendation": (
                    "Validar el pH con análisis de suelo y planificar acondicionamiento gradual "
                    "junto con incremento de materia orgánica."
                ),
                "rationale": "Un pH alcalino puede limitar disponibilidad de nutrientes.",
                "confidence": "alta",
                "limitations": None,
                "evidence_used": [_ref(by_file["suelo.md"], "Validar pH y planificar enmiendas graduales.")],
            },
            {
                "gap_key": "aptitud_altitudinal:germinacion_emergencia",
                "criterion_id": "aptitud_altitudinal",
                "criterion_name": "aptitud_altitudinal",
                "criterion_label": "Aptitud altitudinal",
                "criterion_group": "topografia",
                "phase_id": "germinacion_emergencia",
                "phase_name": "Germinación y emergencia",
                "gap_direction": "above_optimum",
                "severity": "media",
                "observed_value": 980.0,
                "optimal_limit": 600.0,
                "gap_value": 380.0,
                "recommendation": (
                    "Registrar la altitud como restricción estructural de sitio; no plantear "
                    "corrección agronómica directa."
                ),
                "rationale": "La altitud no puede modificarse mediante manejo de parcela.",
                "confidence": "media",
                "limitations": "Condición no corregible; solo puede considerarse en la decisión.",
                "evidence_used": [_ref(by_file["topografia.md"], "Altitud y pendiente son condiciones de sitio.")],
            },
        ],
        "overall_limitations": "Recomendación generada con evidencia documental recuperada y datos MCDA de solo lectura.",
    }


def _ref(item: EvidenceData, quote_summary: str) -> dict[str, Any]:
    return {
        "fragment_id": str(item.fragment_id),
        "source_file_id": item.source_file_id,
        "source_filename": item.source_filename,
        "source_locator": item.source_filename,
        "quote_summary": quote_summary,
    }


def _gap_analysis_payload(result: Any) -> dict[str, Any]:
    return {
        "crop_id": result.crop_id,
        "viability_category": result.viability_category,
        "counts": {
            "total_criteria_with_gaps": result.total_criteria_with_gaps,
            "structural": result.structural_count,
            "correctable": result.correctable_count,
            "mitigable": result.mitigable_count,
            "data_quality": result.data_quality_count,
        },
        "gap_groups": [
            {
                "criterion_name": group.criterion_name,
                "criterion_label": group.criterion_label,
                "gap_class": group.gap_class.value,
                "correctability": group.correctability.value,
                "representative_observed": group.representative_observed,
                "representative_optimal": group.representative_optimal,
                "representative_gap": group.representative_gap,
                "severity": group.representative_severity,
                "priority_score": group.priority_score,
                "data_quality_flags": group.data_quality_flags,
            }
            for group in result.gap_groups
        ],
    }


def _evidence_payload(evidence: list[EvidenceData]) -> list[dict[str, Any]]:
    return [
        {
            "fragment_id": str(item.fragment_id),
            "source_filename": item.source_filename,
            "source_file_id": item.source_file_id,
            "score": item.score,
            "crop_tags": item.crop_tags,
            "text": item.text,
        }
        for item in evidence
    ]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        data = asdict(value)
        return _stringify_uuids(data)
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _stringify_uuids(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _stringify_uuids(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_stringify_uuids(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    return value


def _summary_markdown(paths: dict[str, str]) -> str:
    return f"""# Evidencia: Caso De Brechas Y Recomendación LLM

Caso reproducible, sin llamadas externas: se usa un resultado MCDA sintético y
se ejecutan las funciones reales de análisis de brechas y control de calidad.

## Capturas Recomendadas

| Figura | Archivo | Qué demuestra |
| --- | --- | --- |
| Figura 7.1 | `{paths['mcda']}` | Resultado MCDA de entrada: score, categoría, brechas y factor limitante. |
| Figura 7.2 | `{paths['gaps']}` | Brechas detectadas y clasificadas determinísticamente. |
| Figura 7.3 | `{paths['evidence']}` | Evidencia documental recuperada para las brechas. |
| Figura 7.4 | `{paths['draft']}` | Borrador estructurado simulado del LLM. |
| Figura 7.5 | `{paths['qc']}` | Resultado del control de calidad posterior al LLM. |
| Figura 7.6 | `{paths['final_text']}` | Recomendación final visible después del QC. |

## Recorrido Evidenciado

Resultado MCDA -> brecha detectada -> clasificación determinística ->
recuperación documental -> borrador LLM -> control de calidad -> recomendación final.

## Nota Metodológica

El LLM no se ejecuta en este script. El borrador se simula para demostrar cómo
VIA procesa una salida estructurada mediante el control de calidad real.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a recommendation case evidence package.")
    parser.add_argument("--out", default="artifacts/recommendation_case_evidence", help="Output directory.")
    args = parser.parse_args()

    out_dir = Path(args.out)
    crop_result = _mcda_case()
    gap_analysis = analyse_gaps(crop_result)
    evidence = _evidence()
    llm_draft = _llm_draft(evidence)
    qc_result = _quality_control_structured_output(
        llm_draft,
        evidence,
        crop_id=CROP_ID,
        viability_category=crop_result.viability_category,
    )
    final_text = _render_visible_text(qc_result, fallback_text="")

    paths = {
        "mcda": "01_mcda_result.json",
        "gaps": "02_gap_analysis.json",
        "evidence": "03_documentary_evidence.json",
        "draft": "04_llm_structured_draft.json",
        "qc": "05_quality_control_result.json",
        "final_text": "06_final_recommendation.md",
    }

    _write_json(out_dir / paths["mcda"], {"evaluation_id": str(EVALUATION_ID), "crop_result": crop_result})
    _write_json(out_dir / paths["gaps"], _gap_analysis_payload(gap_analysis))
    _write_json(out_dir / paths["evidence"], _evidence_payload(evidence))
    _write_json(out_dir / paths["draft"], llm_draft)
    _write_json(out_dir / paths["qc"], qc_result)
    (out_dir / paths["final_text"]).write_text(final_text, encoding="utf-8")
    (out_dir / "README.md").write_text(_summary_markdown(paths), encoding="utf-8")

    print(f"Recommendation case evidence exported to {out_dir}")
    print("Generated 6 evidence files plus README.md.")


if __name__ == "__main__":
    main()
