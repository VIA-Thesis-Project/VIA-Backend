"""Export production rulebook evidence artifacts.

The production rulebooks in VIA are implemented by ``scripts/seed_prod_rulebooks.py``
and loaded into the database during deployment/seeding. This script reconstructs
the same rulebook graphs without touching the database, then exports:

* one JSON artifact per production crop;
* a maize-focused fragment for the report;
* an endpoint-like listing showing the five active rulebooks;
* a Markdown summary with suggested screenshots.

It is read-only with respect to the application database.

Usage:
    python scripts/rulebook_evidence_export.py
    python scripts/rulebook_evidence_export.py --out artifacts/rulebook_evidence
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from seed_prod_rulebooks import PROD_CROPS, build_prod_rulebook_parts


DEFAULT_OUT = Path("artifacts/rulebook_evidence")


def _criterion_payload(criterion: Any) -> dict[str, Any]:
    return {
        "id": str(criterion.id),
        "name": criterion.name,
        "is_critical": criterion.is_critical,
        "critical_policy": criterion.critical_policy.value if criterion.critical_policy else None,
        "penalty_factor": criterion.penalty_factor,
        "ahp_weight": criterion.ahp_weight,
        "intervention_class": criterion.intervention_class.value,
        "doc_source": criterion.doc_source,
        "technical_notes": criterion.technical_notes,
    }


def _phase_payload(phase: Any) -> dict[str, Any]:
    return {
        "id": str(phase.id),
        "name": phase.name,
        "duration_days": phase.duration_days,
        "sequence_order": phase.sequence_order,
    }


def _requirement_payload(requirement: Any) -> dict[str, Any]:
    return {
        "id": str(requirement.id),
        "criterion_id": str(requirement.criterion_id),
        "phase_id": str(requirement.phase_id),
        "membership_fn": requirement.membership_fn.to_mapping(),
        "phase_weight": requirement.phase_weight,
        "temporal_periods": [period.to_mapping() for period in requirement.temporal_periods],
        "extraction": requirement.extraction_binding.to_mapping(),
    }


def _rulebook_payload(crop_id: str, display_name: str) -> dict[str, Any]:
    criteria, phases, requirements = build_prod_rulebook_parts(crop_id)
    return {
        "crop_id": crop_id,
        "display_name": display_name,
        "version": 1,
        "status": "ACTIVE_AFTER_SEED",
        "source_script": "scripts/seed_prod_rulebooks.py",
        "criteria_count": len(criteria),
        "phase_count": len(phases),
        "phase_requirement_count": len(requirements),
        "criteria": [_criterion_payload(criterion) for criterion in criteria],
        "phases": [_phase_payload(phase) for phase in phases],
        "phase_requirements": [_requirement_payload(requirement) for requirement in requirements],
    }


def _maize_fragment(rulebook: dict[str, Any]) -> dict[str, Any]:
    criteria_by_id = {criterion["id"]: criterion for criterion in rulebook["criteria"]}
    phases_by_id = {phase["id"]: phase for phase in rulebook["phases"]}
    selected: list[dict[str, Any]] = []
    wanted = {"aptitud_termica", "reaccion_suelo_ph", "aptitud_altitudinal", "contenido_arcilla"}
    for requirement in rulebook["phase_requirements"]:
        criterion = criteria_by_id[requirement["criterion_id"]]
        phase = phases_by_id[requirement["phase_id"]]
        if criterion["name"] not in wanted:
            continue
        if criterion["name"] == "aptitud_termica" and phase["name"] != "espigamiento_floracion":
            continue
        if criterion["name"] != "aptitud_termica" and phase["sequence_order"] != 1:
            continue
        selected.append(
            {
                "criterion": criterion["name"],
                "phase": phase["name"],
                "ahp_weight": criterion["ahp_weight"],
                "phase_weight": requirement["phase_weight"],
                "membership_fn": requirement["membership_fn"],
                "extraction": requirement["extraction"],
                "critical_policy": criterion["critical_policy"],
                "penalty_factor": criterion["penalty_factor"],
            }
        )
    return {
        "crop_id": rulebook["crop_id"],
        "display_name": rulebook["display_name"],
        "fragment_purpose": "Small readable fragment for report figure: criterion -> phase -> membership -> extraction binding.",
        "items": selected,
    }


def _endpoint_like_listing(rulebooks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"generated-from-seed:{rulebook['crop_id']}",
            "crop_id": rulebook["crop_id"],
            "version": rulebook["version"],
            "status": rulebook["status"],
            "criteria_count": rulebook["criteria_count"],
            "phase_count": rulebook["phase_count"],
            "phase_requirement_count": rulebook["phase_requirement_count"],
        }
        for rulebook in rulebooks
    ]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _markdown_summary(out_dir: Path, rulebooks: list[dict[str, Any]]) -> str:
    listing = _endpoint_like_listing(rulebooks)
    rows = "\n".join(
        "| {crop_id} | {display_name} | {criteria_count} | {phase_count} | {phase_requirement_count} | {status} |".format(
            **rulebook
        )
        for rulebook in rulebooks
    )
    endpoint_rows = "\n".join(
        "| `{crop_id}` | {version} | {status} | {criteria_count} | {phase_count} | {phase_requirement_count} |".format(
            **item
        )
        for item in listing
    )
    return f"""# Rulebook Evidence Artifacts

These artifacts were generated from `scripts/seed_prod_rulebooks.py`, the same
source used to seed VIA production rulebooks. No database connection was used.

## Figure X: Files Of The Five Rulebooks

Generated files:

- `prod_rulebooks/maiz_amarillo_duro.json`
- `prod_rulebooks/mandarina_murcott.json`
- `prod_rulebooks/maracuya_criolla_amarilla.json`
- `prod_rulebooks/palta_hass.json`
- `prod_rulebooks/uva_de_mesa_sweet_globe.json`

| Crop ID | Display name | Criteria | Phases | Phase requirements | Status |
| --- | --- | ---: | ---: | ---: | --- |
{rows}

## Figure X+1: Maize Rulebook Fragment

Use `maiz_rulebook_fragment.json` as a compact screenshot. It shows selected
criteria, phase-specific trapezoidal membership functions, AHP/phase weights
and extraction bindings.

## Figure X+2: Load Or Listing Evidence

Use `endpoint_like_rulebook_listing.json` for an endpoint-shaped listing of the
five seeded rulebooks:

| Crop ID | Version | Status | Criteria | Phases | Phase requirements |
| --- | ---: | --- | ---: | ---: | ---: |
{endpoint_rows}

If you want a live system screenshot instead, seed and query the backend:

```powershell
python scripts/seed_prod_rulebooks.py
curl -H "Authorization: Bearer <TOKEN>" http://127.0.0.1:8000/rulebooks
curl -H "Authorization: Bearer <TOKEN>" http://127.0.0.1:8000/rulebooks/maiz_amarillo_duro/active
```

Suggested screenshot paths:

- `{out_dir / "prod_rulebooks"}`
- `{out_dir / "maiz_rulebook_fragment.json"}`
- `{out_dir / "endpoint_like_rulebook_listing.json"}`
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Export production rulebook evidence artifacts.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output directory.")
    args = parser.parse_args()

    out_dir = Path(args.out)
    rulebooks = [_rulebook_payload(crop_id, display_name) for crop_id, display_name in PROD_CROPS.items()]

    for rulebook in rulebooks:
        _write_json(out_dir / "prod_rulebooks" / f"{rulebook['crop_id']}.json", rulebook)

    maize = next(rulebook for rulebook in rulebooks if rulebook["crop_id"] == "maiz_amarillo_duro")
    _write_json(out_dir / "maiz_rulebook_fragment.json", _maize_fragment(maize))
    _write_json(out_dir / "endpoint_like_rulebook_listing.json", _endpoint_like_listing(rulebooks))
    (out_dir / "README.md").write_text(_markdown_summary(out_dir, rulebooks), encoding="utf-8")

    print(f"Rulebook evidence exported to {out_dir}")
    print(f"Generated {len(rulebooks)} rulebook JSON files plus README.md, maize fragment and endpoint-like listing.")


if __name__ == "__main__":
    main()
