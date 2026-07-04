"""Export concise evidence for gap analysis and LLM recommendations.

This script is read-only. It does not call LLM providers, does not connect to
the database, and does not require secrets. It exports compact evidence showing
the implemented separation between deterministic gap analysis, documentary
retrieval, LLM drafting and deterministic quality control.

Usage:
    python scripts/recommendation_evidence_export.py
    python scripts/recommendation_evidence_export.py --out artifacts/recommendation_evidence
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_OUT = Path("artifacts/recommendation_evidence")


PIPELINE = [
    {
        "step": 1,
        "stage": "Entrada MCDA",
        "description": "Recibe resultados ya calculados: score, ranking, categoría, brechas y factores limitantes.",
        "evidence": "EvaluationRecommendationData + CropEvaluationResultData",
    },
    {
        "step": 2,
        "stage": "Selección de cultivo",
        "description": "Selecciona el cultivo indicado o, si no se especifica, el cultivo con rank_position = 1.",
        "evidence": "RecommendationCommandService.generate",
    },
    {
        "step": 3,
        "stage": "Análisis determinístico de brechas",
        "description": "Agrupa brechas por criterio, clasifica su tipo de intervención y calcula prioridad.",
        "evidence": "analyse_gaps(crop_result)",
    },
    {
        "step": 4,
        "stage": "Recuperación documental",
        "description": "Busca evidencia técnica relacionada con cultivo y brechas detectadas.",
        "evidence": "IDocumentEvidencePort.search_evidence",
    },
    {
        "step": 5,
        "stage": "Contexto para LLM",
        "description": "Construye un contexto con resultados MCDA de solo lectura, brechas y evidencia recuperada.",
        "evidence": "RecommendationDraftContext",
    },
    {
        "step": 6,
        "stage": "Borrador LLM",
        "description": "El proveedor LLM genera una salida estructurada de recomendación; no recalcula viabilidad.",
        "evidence": "IRecommendationDraftingProvider.draft",
    },
    {
        "step": 7,
        "stage": "Control de calidad determinístico",
        "description": "Valida compatibilidad de evidencia, detecta sospechas de mapeo y puede anular recomendaciones.",
        "evidence": "_quality_control_structured_output",
    },
    {
        "step": 8,
        "stage": "Recomendación final",
        "description": "Renderiza texto visible, persiste el agregado y emite eventos de outbox.",
        "evidence": "Recommendation + RecomendacionGenerada",
    },
]


FILES = [
    {
        "file": "via/bounded_contexts/recommendation/application/gap_analysis.py",
        "symbols": "analyse_gaps, GapGroup, GapClass",
        "role": "Identifica y clasifica brechas de forma determinística, sin LLM.",
    },
    {
        "file": "via/bounded_contexts/recommendation/application/command_service.py",
        "symbols": "RecommendationCommandService.generate",
        "role": "Orquesta selección de cultivo, análisis de brechas, evidencia, LLM, QC y persistencia.",
    },
    {
        "file": "via/bounded_contexts/recommendation/application/command_service.py",
        "symbols": "_quality_control_structured_output",
        "role": "Aplica control de calidad determinístico a la salida estructurada del LLM.",
    },
    {
        "file": "via/bounded_contexts/recommendation/application/ports.py",
        "symbols": "IDocumentEvidencePort, IRecommendationDraftingProvider",
        "role": "Define puertos para recuperación documental y generación de borrador.",
    },
    {
        "file": "via/bounded_contexts/recommendation/infrastructure/openai_file_search_provider.py",
        "symbols": "OpenAIFileSearchDraftingProvider",
        "role": "Proveedor RAG con OpenAI File Search sobre documentos curados.",
    },
    {
        "file": "via/bounded_contexts/recommendation/infrastructure/openai_web_search_provider.py",
        "symbols": "OpenAIWebSearchDraftingProvider",
        "role": "Proveedor opcional con Web Search y dominios preferidos.",
    },
    {
        "file": "via/bounded_contexts/recommendation/infrastructure/tavily_rag_provider.py",
        "symbols": "TavilyRagDraftingProvider",
        "role": "Proveedor opcional de búsqueda web + redacción con OpenAI.",
    },
    {
        "file": "via/bounded_contexts/recommendation/infrastructure/recommendation_repository.py",
        "symbols": "SQLAlchemyRecommendationRepository",
        "role": "Persiste recomendación, evidencia y salida estructurada.",
    },
]


GAP_CLASSES = [
    {
        "class": "CORRECTABLE",
        "meaning": "Brecha corregible mediante manejo agronómico.",
        "example": "pH, materia orgánica, suelo, riego.",
    },
    {
        "class": "MITIGABLE",
        "meaning": "Limitación cuyo impacto puede reducirse, pero no eliminarse totalmente.",
        "example": "temperatura, riesgo climático.",
    },
    {
        "class": "STRUCTURAL_NOT_CORRECTABLE",
        "meaning": "Condición de sitio no modificable de forma práctica.",
        "example": "altitud, pendiente/topografía.",
    },
    {
        "class": "DATA_QUALITY_REVIEW",
        "meaning": "Dato sospechoso o inconsistente; requiere validación antes de recomendar.",
        "example": "valor físico imposible o posible mapeo incorrecto.",
    },
]


CONTROL_GUARDS = [
    "No recalcula scores, rankings ni categorías de viabilidad.",
    "Puede anular recomendaciones sin evidencia compatible.",
    "Mueve criterios sospechosos a validación metodológica.",
    "Reescribe recomendaciones agronómicamente inseguras, por ejemplo modificar textura directamente.",
    "Agrupa brechas de suelo en una recomendación integrada cuando corresponde.",
]


def _payload() -> dict[str, Any]:
    return {
        "title": "Evidencia de análisis de brechas y recomendaciones con LLM",
        "purpose": "Demostrar que VIA separa detección determinística de brechas y redacción asistida por LLM.",
        "pipeline": PIPELINE,
        "implementation_files": FILES,
        "gap_classes": GAP_CLASSES,
        "quality_control_guards": CONTROL_GUARDS,
        "key_design_points": [
            "El motor MCDA calcula viabilidad antes de la recomendación.",
            "El análisis de brechas es determinístico y ocurre antes del LLM.",
            "El LLM recibe contexto estructurado y evidencia; no decide la viabilidad.",
            "La salida del LLM pasa por control de calidad determinístico.",
            "La recomendación final se persiste con evidencia y structured_output.",
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
    class_rows = [
        [item["class"], item["meaning"], item["example"]]
        for item in payload["gap_classes"]
    ]
    lines = [
        "# Evidencia: Análisis De Brechas Y Recomendaciones Con LLM",
        "",
        "## Proceso Esencial",
        "",
        _table(["Paso", "Etapa", "Qué ocurre", "Evidencia de implementación"], pipeline_rows),
        "",
        "## Separación De Responsabilidades",
        "",
        "- Determinístico: MCDA, análisis de brechas, clasificación, prioridad y control de calidad.",
        "- LLM: redacción estructurada de recomendaciones a partir de brechas y evidencia documental.",
        "- Persistencia: recomendación final, evidencia utilizada y salida estructurada.",
        "",
        "## Clases De Brecha",
        "",
        _table(["Clase", "Significado", "Ejemplo"], class_rows),
        "",
        "## Archivos De Implementación",
        "",
        _table(["Archivo", "Símbolos", "Rol"], file_rows),
        "",
        "## Guardas De Control De Calidad",
        "",
    ]
    lines.extend(f"- {item}" for item in payload["quality_control_guards"])
    lines.extend(["", "## Puntos Clave", ""])
    lines.extend(f"- {item}" for item in payload["key_design_points"])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export recommendation evidence artifacts.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output directory.")
    args = parser.parse_args()

    out_dir = Path(args.out)
    payload = _payload()
    _write_json(out_dir / "recommendation_pipeline_summary.json", payload)
    (out_dir / "README.md").write_text(_markdown(payload), encoding="utf-8")

    print(f"Recommendation evidence exported to {out_dir}")
    print("Generated README.md and recommendation_pipeline_summary.json.")


if __name__ == "__main__":
    main()
