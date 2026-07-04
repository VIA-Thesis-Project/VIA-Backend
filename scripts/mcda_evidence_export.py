"""Export concise evidence for the fuzzy MCDA engine.

This script is read-only. It does not run an evaluation, connect to the
database, or call Google Earth Engine. It exports a compact evidence package
showing where the MCDA engine is implemented and the essential processing flow.

Usage:
    python scripts/mcda_evidence_export.py
    python scripts/mcda_evidence_export.py --out artifacts/mcda_evidence
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_OUT = Path("artifacts/mcda_evidence")


PIPELINE = [
    {
        "step": 1,
        "stage": "Entradas",
        "description": "Recibe los rulebooks activos y el vector agroambiental de la parcela evaluada.",
        "evidence": "RulebookEvaluationData + AgroenvVectorData",
    },
    {
        "step": 2,
        "stage": "Membresía difusa",
        "description": "Aplica funciones de pertenencia trapezoidales del rulebook sobre los valores observados.",
        "evidence": "membership_fn {a,b,c,d} -> membresía en [0,1]",
    },
    {
        "step": 3,
        "stage": "Agregación por criterio",
        "description": "Agrega periodos temporales y fases fenológicas para cada criterio.",
        "evidence": "temporal_weight + phase_weight",
    },
    {
        "step": 4,
        "stage": "Entropía cross-cultivo",
        "description": "Construye la matriz cultivos x criterios y calcula pesos objetivos por entropía cuando existen suficientes alternativas.",
        "evidence": "EntropyWeightsService over aggregated memberships",
    },
    {
        "step": 5,
        "stage": "Ponderación híbrida",
        "description": "Combina los pesos AHP definidos en el rulebook con los pesos de entropía.",
        "evidence": "HybridWeightsService.combine(w_ahp, w_entropy, alpha)",
    },
    {
        "step": 6,
        "stage": "Score y políticas",
        "description": "Calcula el score final del cultivo y aplica políticas críticas y reglas de suficiencia de datos.",
        "evidence": "score, calc_condition, viability_category, limiting_factors",
    },
    {
        "step": 7,
        "stage": "Salidas",
        "description": "Devuelve resultados rankeados por cultivo, brechas agronómicas y detalles trazables por criterio.",
        "evidence": "CropResult + CriterionDetail + AgronomyGap",
    },
]


FILES = [
    {
        "file": "via/bounded_contexts/viability_evaluation/application/command_service.py",
        "symbols": "PureMcdaEvaluationEngine, _criterion_pass_for_crop, _build_decision_matrix",
        "role": "Coordina la evaluación MCDA en dos pasadas y produce los resultados por cultivo.",
    },
    {
        "file": "via/bounded_contexts/viability_evaluation/domain/mcda_basic.py",
        "symbols": "Membership and weighted aggregation helpers",
        "role": "Implementa primitivas de membresía difusa y agregación ponderada.",
    },
    {
        "file": "via/bounded_contexts/viability_evaluation/domain/entropy_weights.py",
        "symbols": "EntropyWeightsService",
        "role": "Calcula pesos objetivos a través de los cultivos candidatos.",
    },
    {
        "file": "via/bounded_contexts/viability_evaluation/domain/hybrid_weights.py",
        "symbols": "HybridWeightsService",
        "role": "Combina pesos AHP y pesos de entropía.",
    },
    {
        "file": "via/bounded_contexts/viability_evaluation/domain/mcda_policy.py",
        "symbols": "Critical policy evaluation",
        "role": "Aplica políticas críticas y categorías de viabilidad.",
    },
    {
        "file": "via/bounded_contexts/viability_evaluation/infrastructure/evaluation_repository.py",
        "symbols": "SQLAlchemyEvaluationRepository",
        "role": "Persiste resultados de evaluación, detalles, brechas y factores limitantes.",
    },
]


OUTPUT_FIELDS = [
    "crop_id",
    "score",
    "rank_position",
    "calc_condition",
    "viability_category",
    "criteria_details",
    "gaps",
    "limiting_factors",
    "missing_criteria",
    "unrecognized_variables",
]


def _payload() -> dict[str, Any]:
    return {
        "title": "Evidencia del motor MCDA difuso",
        "purpose": "Evidencia concisa de implementación del proceso de cálculo de viabilidad.",
        "pipeline": PIPELINE,
        "implementation_files": FILES,
        "main_outputs": OUTPUT_FIELDS,
        "key_design_points": [
            "El LLM no participa en el cálculo del score, ranking ni categoría de viabilidad.",
            "Los rulebooks aportan funciones de membresía, pesos AHP, pesos por fase y políticas críticas.",
            "La extracción agroambiental aporta valores observados de la parcela ya convertidos a unidades físicas.",
            "La ponderación por entropía es cross-cultivo: usa los cultivos candidatos como alternativas.",
            "El score se almacena con trazabilidad: detalles por criterio, brechas y factores limitantes.",
        ],
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |")
    return "\n".join(lines)


def _markdown(payload: dict[str, Any]) -> str:
    pipeline_rows = [
        [item["step"], item["stage"], item["description"], item["evidence"]]
        for item in payload["pipeline"]
    ]
    file_rows = [
        [f"`{item['file']}`", f"`{item['symbols']}`", item["role"]]
        for item in payload["implementation_files"]
    ]
    lines = [
        "# Evidencia: Motor MCDA Difuso",
        "",
        "## Proceso Esencial",
        "",
        _table(["Paso", "Etapa", "Qué ocurre", "Evidencia de implementación"], pipeline_rows),
        "",
        "## Archivos De Implementación",
        "",
        _table(["Archivo", "Símbolos", "Rol"], file_rows),
        "",
        "## Salidas Principales",
        "",
        ", ".join(f"`{field}`" for field in payload["main_outputs"]),
        "",
        "## Puntos Clave",
        "",
    ]
    lines.extend(f"- {item}" for item in payload["key_design_points"])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export concise MCDA evidence artifacts.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output directory.")
    args = parser.parse_args()

    out_dir = Path(args.out)
    payload = _payload()
    _write_json(out_dir / "mcda_pipeline_summary.json", payload)
    (out_dir / "README.md").write_text(_markdown(payload), encoding="utf-8")

    print(f"MCDA evidence exported to {out_dir}")
    print("Generated README.md and mcda_pipeline_summary.json.")


if __name__ == "__main__":
    main()
