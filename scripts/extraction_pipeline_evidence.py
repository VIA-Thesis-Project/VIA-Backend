"""Print evidence of the agroenvironmental extraction pipeline.

This script is read-only: it does not connect to Google Earth Engine, does not
open a database session, and does not require secrets. It inspects the code
registry used by VIA to document which extraction sources, variables and
dispatch strategies are implemented.

Usage:
    python scripts/extraction_pipeline_evidence.py
    python scripts/extraction_pipeline_evidence.py --format json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from via.bounded_contexts.agroenv_extraction.infrastructure.gee_variable_registry import (
    get_variable_definition,
    list_variable_names,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


PIPELINE_STEPS = [
    {
        "step": "1",
        "stage": "Rulebook -> RequiredExtractionSpec",
        "file": "via/bounded_contexts/rulebook_management/application/query_service.py",
        "symbols": "get_required_extraction_spec",
        "evidence": "Builds the variables and periods that must be extracted for each crop candidate.",
    },
    {
        "step": "2",
        "stage": "Extraction command intake",
        "file": "via/bounded_contexts/agroenv_extraction/interfaces/extraction_consumer.py",
        "symbols": "AgroenvExtractionConsumer",
        "evidence": "Receives the IniciarExtraccionAgroambiental message from the internal bus.",
    },
    {
        "step": "3",
        "stage": "Transactional command service",
        "file": "via/bounded_contexts/agroenv_extraction/application/command_service.py",
        "symbols": "handle_start_command",
        "evidence": "Applies idempotency, calls the ACL, persists the vector and writes outbox events.",
    },
    {
        "step": "4",
        "stage": "Spec -> ExtractionRequest",
        "file": "via/bounded_contexts/agroenv_extraction/infrastructure/extraction_acl.py",
        "symbols": "build_vector, _request_from_spec",
        "evidence": "Iterates required variables and temporal periods, then calls extraction_client.extract_variable().",
    },
    {
        "step": "5",
        "stage": "External extraction adapter",
        "file": "via/bounded_contexts/agroenv_extraction/infrastructure/gee_client.py",
        "symbols": "GeeExtractionClient.extract_variable",
        "evidence": "Calls Google Earth Engine when enabled and dispatches by GeeVariableType.",
    },
    {
        "step": "6",
        "stage": "Variable registry",
        "file": "via/bounded_contexts/agroenv_extraction/infrastructure/gee_variable_registry.py",
        "symbols": "GeeVariableDefinition",
        "evidence": "Defines supported variables, datasets, bands, units, scales, conversions and sampling strategies.",
    },
]


def _registry_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in list_variable_names():
        definition = get_variable_definition(name)
        if definition is None:
            continue
        rows.append(
            {
                "category": definition.category,
                "variable": definition.variable_name,
                "type": definition.variable_type.value,
                "dataset": definition.dataset_key,
                "bands": ", ".join(definition.source_bands) or "-",
                "result_band": definition.result_band,
                "unit": definition.unit,
                "scale_m": definition.default_scale,
                "sampling": definition.spatial_sampling_strategy,
                "aggregation": definition.temporal_aggregation,
                "formula_or_conversion": definition.formula_note or "-",
            }
        )
    return rows


def _dataset_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["category"]), str(row["dataset"]))].append(str(row["variable"]))
    return [
        {
            "category": category,
            "dataset": dataset,
            "variable_count": len(variables),
            "variables": ", ".join(variables),
        }
        for (category, dataset), variables in sorted(grouped.items())
    ]


def _payload() -> dict[str, Any]:
    rows = _registry_rows()
    return {
        "title": "Agroenvironmental extraction implementation evidence",
        "pipeline_steps": PIPELINE_STEPS,
        "variable_count": len(rows),
        "dataset_count": len({row["dataset"] for row in rows}),
        "categories": sorted({row["category"] for row in rows}),
        "datasets": _dataset_summary(rows),
        "variables": rows,
        "notes": [
            "Read-only evidence script; it does not call GEE and does not require credentials.",
            "The registry is the implementation source for supported GEE variables.",
            "Fine-resolution datasets use polygon_mean; coarse datasets use centroid_sample when declared in the registry.",
        ],
    }


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_cell(value) for value in row) + " |")
    return "\n".join(lines)


def _cell(value: Any) -> str:
    text = str(value).replace("\n", " ").replace("|", "\\|")
    return text


def _markdown(payload: dict[str, Any]) -> str:
    step_rows = [
        [
            item["step"],
            item["stage"],
            f"`{item['file']}`",
            f"`{item['symbols']}`",
            item["evidence"],
        ]
        for item in payload["pipeline_steps"]
    ]
    dataset_rows = [
        [
            item["category"],
            f"`{item['dataset']}`",
            item["variable_count"],
            "`" + item["variables"].replace(", ", "`, `") + "`",
        ]
        for item in payload["datasets"]
    ]
    variable_rows = [
        [
            row["category"],
            f"`{row['variable']}`",
            row["type"],
            f"`{row['dataset']}`",
            f"`{row['bands']}`",
            row["unit"],
            row["scale_m"],
            row["sampling"],
        ]
        for row in payload["variables"]
    ]
    lines = [
        "# Evidence: Agroenvironmental Extraction Pipeline",
        "",
        f"- Registered variables: {payload['variable_count']}",
        f"- Registered datasets: {payload['dataset_count']}",
        "- Categories: " + ", ".join(payload["categories"]),
        "",
        "## Pipeline Trace",
        "",
        _table(["Step", "Stage", "File", "Symbol", "Evidence"], step_rows),
        "",
        "## Dataset Summary",
        "",
        _table(["Category", "Dataset", "Variables", "Variable names"], dataset_rows),
        "",
        "## Registered Variables",
        "",
        _table(
            ["Category", "Variable", "Type", "Dataset", "Bands", "Unit", "Scale m", "Sampling"],
            variable_rows,
        ),
        "",
        "## Notes",
        "",
    ]
    lines.extend(f"- {note}" for note in payload["notes"])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Print extraction pipeline evidence.")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()

    payload = _payload()
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=True, indent=2, default=_json_default))
    else:
        print(_markdown(payload))


def _json_default(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return str(value)


if __name__ == "__main__":
    main()
