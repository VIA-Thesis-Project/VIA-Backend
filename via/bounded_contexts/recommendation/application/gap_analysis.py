"""Deterministic gap treatment layer for the recommendation bounded context.

Groups gaps by criterion_id, classifies them by intervention feasibility,
detects data quality issues, and produces a prioritised GapAnalysisResult.

The LLM must NEVER perform these computations. All classification, grouping,
severity assessment and prioritisation is handled here in deterministic code.
"""

from __future__ import annotations

from collections import defaultdict

from via.bounded_contexts.recommendation.application.ports import (
    Correctability,
    CropEvaluationResultData,
    GapAnalysisResult,
    GapClass,
    GapData,
    GapGroup,
    GapOccurrence,
)

# ─── Classification maps ──────────────────────────────────────────────────────

# Explicit mapping from the declarative InterventionClass value (str) to runtime GapClass.
# DATA_QUALITY_REVIEW is never in this map: it is assigned at runtime by _detect_data_quality_flags.
_INTERVENTION_CLASS_TO_GAP_CLASS: dict[str, GapClass] = {
    "STRUCTURAL":   GapClass.STRUCTURAL_NOT_CORRECTABLE,
    "MITIGABLE":    GapClass.MITIGABLE,
    "CORRECTABLE":  GapClass.CORRECTABLE,
}

# Altitude range (msnm) that a hydric/climate criterion should never match.
# If a criterion named like "deficit_hidrico" shows observed_value in this range
# with an optimal_limit also in this range, it is likely an elevation criterion.
_ALTITUDE_VALUE_MIN = 800.0
_ALTITUDE_VALUE_MAX = 4_500.0
_ALTITUDE_OPTIMAL_MAX = 1_200.0

_ZERO_IMPOSSIBLE_CRITERIA: frozenset[str] = frozenset({
    "carbono_organico_suelo",
    "reaccion_suelo_ph",
})

_GAP_CLASS_TO_CORRECTABILITY: dict[GapClass, Correctability] = {
    GapClass.STRUCTURAL_NOT_CORRECTABLE: Correctability.no_corregible,
    GapClass.MITIGABLE: Correctability.mitigable,
    GapClass.CORRECTABLE: Correctability.corregible,
    GapClass.DATA_QUALITY_REVIEW: Correctability.requiere_validacion,
}

_SEVERITY_WEIGHT: dict[str, float] = {"alta": 3.0, "media": 2.0, "baja": 1.0}

_CLASS_MULTIPLIER: dict[GapClass, float] = {
    GapClass.CORRECTABLE: 1.0,
    GapClass.DATA_QUALITY_REVIEW: 0.9,
    GapClass.MITIGABLE: 0.7,
    GapClass.STRUCTURAL_NOT_CORRECTABLE: 0.4,
}

_VIABILITY_INTERPRETATION: dict[str, str] = {
    "VIABLE": (
        "El cultivo es viable bajo las condiciones evaluadas. "
        "Generar recomendacion tecnica directa con plan de manejo estandar."
    ),
    "CONDICIONAL": (
        "El cultivo presenta viabilidad condicional. "
        "Generar plan de manejo priorizado diferenciando: "
        "(1) acciones inmediatas; "
        "(2) validaciones de campo requeridas; "
        "(3) manejo agronomico aplicable; "
        "(4) restricciones que solo pueden mitigarse; "
        "(5) riesgos que deben declararse explicitamente. "
        "No afirmar que una brecha fue solventada si solo fue mitigada."
    ),
    "NO_VIABLE": (
        "El cultivo es NO VIABLE bajo las condiciones evaluadas. "
        "NO generar plan de instalacion ni de manejo productivo. "
        "Generar unicamente: "
        "(1) explicacion tecnica del descarte; "
        "(2) brechas dominantes; "
        "(3) riesgos principales; "
        "(4) condiciones minimas bajo las cuales el cultivo podria reconsiderarse, si aplica."
    ),
}


# ─── Public API ───────────────────────────────────────────────────────────────


def analyse_gaps(crop_result: CropEvaluationResultData) -> GapAnalysisResult:
    """Group, score and prioritise gaps from an already-computed crop result."""

    groups = _build_groups(crop_result.gaps)
    ruling_barriers = _find_ruling_barriers(groups)
    interpretation = _VIABILITY_INTERPRETATION.get(
        crop_result.viability_category,
        f"Categoria de viabilidad no reconocida: {crop_result.viability_category}.",
    )
    return GapAnalysisResult(
        crop_id=crop_result.crop_id,
        viability_category=crop_result.viability_category,
        viability_interpretation=interpretation,
        gap_groups=groups,
        total_criteria_with_gaps=len(groups),
        structural_count=sum(1 for g in groups if g.gap_class == GapClass.STRUCTURAL_NOT_CORRECTABLE),
        correctable_count=sum(1 for g in groups if g.gap_class == GapClass.CORRECTABLE),
        mitigable_count=sum(1 for g in groups if g.gap_class == GapClass.MITIGABLE),
        data_quality_count=sum(1 for g in groups if g.gap_class == GapClass.DATA_QUALITY_REVIEW),
        ruling_structural_barriers=ruling_barriers,
    )


# ─── Internal helpers ─────────────────────────────────────────────────────────


def _build_groups(gaps: list[GapData]) -> list[GapGroup]:
    by_criterion: dict[str, list[GapData]] = defaultdict(list)
    for gap in gaps:
        by_criterion[gap.criterion_id].append(gap)

    groups = [_make_group(criterion_id, occurrences) for criterion_id, occurrences in by_criterion.items()]
    groups.sort(key=lambda g: -g.priority_score)
    return groups


def _make_group(criterion_id: str, raw: list[GapData]) -> GapGroup:
    first = raw[0]
    criterion_name = first.criterion_name
    criterion_group = first.criterion_group
    occurrences = [_to_occurrence(g) for g in raw]

    data_quality_flags = _detect_data_quality_flags(criterion_name, criterion_group, raw)
    gap_class = _determine_gap_class(criterion_name, criterion_group, data_quality_flags, raw)
    correctability = _gap_class_to_correctability(gap_class, criterion_name, raw)

    rep = _representative(raw)
    severity = rep.get("severity")
    recurrence = len(raw)
    priority = _priority_score(gap_class, severity, recurrence)
    rulebook_flag = _needs_rulebook_review(gap_class, severity, recurrence, raw)

    return GapGroup(
        criterion_id=criterion_id,
        criterion_name=criterion_name,
        criterion_label=first.criterion_label,
        criterion_group=first.criterion_group,
        unit=first.unit,
        gap_class=gap_class,
        correctability=correctability,
        occurrences=occurrences,
        representative_observed=rep["observed_value"],
        representative_optimal=rep["optimal_limit"],
        representative_gap=rep["gap_value"],
        representative_direction=rep.get("gap_direction"),
        representative_severity=severity,
        recurrence=recurrence,
        rulebook_review_required=rulebook_flag,
        priority_score=priority,
        data_quality_flags=data_quality_flags,
    )


def _to_occurrence(gap: GapData) -> GapOccurrence:
    return GapOccurrence(
        phase_id=gap.phase_id,
        phase_name=gap.phase_name,
        most_limiting_period=gap.most_limiting_period,
        observed_value=gap.observed_value,
        optimal_limit=gap.optimal_limit,
        gap_value=gap.gap_value,
        gap_direction=gap.gap_direction,
        severity=gap.severity,
    )


def _determine_gap_class(
    criterion_name: str | None,
    criterion_group: str | None,
    data_quality_flags: list[str],
    raw: list[GapData],
) -> GapClass:
    if data_quality_flags:
        return GapClass.DATA_QUALITY_REVIEW
    intervention_class = raw[0].intervention_class if raw else None
    if intervention_class is not None:
        return _INTERVENTION_CLASS_TO_GAP_CLASS.get(intervention_class, GapClass.MITIGABLE)
    # Completely unknown: no declarative class, no name, no group → data quality concern
    if not criterion_name and not criterion_group:
        return GapClass.DATA_QUALITY_REVIEW
    # Conservative fallback for gaps without intervention_class (legacy / test data)
    return GapClass.MITIGABLE


def _gap_class_to_correctability(
    gap_class: GapClass,
    criterion_name: str | None,
    raw: list[GapData],
) -> Correctability:
    if gap_class == GapClass.STRUCTURAL_NOT_CORRECTABLE:
        if _dominant_structural(raw):
            return Correctability.requiere_revision_rulebook
        return Correctability.no_corregible
    return _GAP_CLASS_TO_CORRECTABILITY[gap_class]


def _detect_data_quality_flags(
    criterion_name: str | None,
    criterion_group: str | None,
    raw: list[GapData],
) -> list[str]:
    flags: list[str] = []
    name = criterion_name or ""
    group = criterion_group or ""
    intervention_class = raw[0].intervention_class if raw else None
    observed_values = {g.observed_value for g in raw}

    if not name and not group and not intervention_class:
        flags.append(
            "criterio completamente desconocido: ni criterion_name, criterion_group ni intervention_class "
            "disponibles para este criterion_id; verificar mapeo en rulebook antes de interpretar la brecha."
        )
        return flags

    if name in _ZERO_IMPOSSIBLE_CRITERIA and 0.0 in observed_values:
        flags.append(
            f"observed_value=0.0 para criterio '{name}' — valor fisicamente imposible; "
            "verificar capa de extraccion antes de recomendar enmiendas."
        )
    elif all(g.observed_value == 0.0 for g in raw) and raw:
        flags.append(
            f"todos los periodos muestran observed_value=0.0 para '{name or group}' — "
            "posible fallo de extraccion o capa ausente; validar en campo."
        )

    if _is_hydric_criterion(name, group) and _values_suggest_altitude(raw):
        flags.append(
            f"criterion_id con nombre '{name or 'DESCONOCIDO'}' muestra observed_value "
            f"({next(iter(observed_values)):.1f}) y optimal_limit "
            f"({raw[0].optimal_limit:.1f}) consistentes con altitud (msnm), no con deficit hidrico (mm). "
            "Verificar en rulebook si este criterion_id corresponde a aptitud_altitudinal u otro "
            "criterio topografico antes de interpretar como brecha hidrica."
        )

    # Flag identical values across phases only for dynamic (temporal) variables.
    # Static variables (soil, topography) legitimately have the same value in all phases.
    if len(raw) > 1 and len(observed_values) == 1 and intervention_class != "STRUCTURAL":
        single = next(iter(observed_values))
        if single != 0.0 and group in ("clima", "riego", "agroambiental"):
            flags.append(
                f"valor identico {single} en todas las {len(raw)} fases para variable temporal '{name or 'DESCONOCIDO'}' — "
                "posible extraccion con valor unico en vez de media por periodo."
            )

    for g in raw:
        if g.gap_value == 0.0 or g.optimal_limit == 0.0:
            continue
        expected = g.observed_value - g.optimal_limit
        if expected != 0.0 and (expected * g.gap_value < 0):
            flags.append(
                f"inconsistencia de signo en gap_value para '{name or 'DESCONOCIDO'}' "
                f"(fase {g.phase_id}): observed={g.observed_value}, optimal_limit={g.optimal_limit} "
                f"implica {'below' if expected < 0 else 'above'}_optimum, "
                f"pero gap_value={g.gap_value:.4g} indica la direccion contraria. "
                "Verificar la formula de brecha en el motor de evaluacion antes de recomendar enmiendas."
            )
            break

    return flags


def _is_hydric_criterion(name: str, group: str) -> bool:
    return "deficit_hidrico" in name or "disponibilidad_hidrica" in name or group == "riego"


def _values_suggest_altitude(raw: list[GapData]) -> bool:
    """True when observed_value and optimal_limit are both in typical altitude range (msnm)."""
    if not raw:
        return False
    observed = raw[0].observed_value
    optimal = raw[0].optimal_limit
    return (
        _ALTITUDE_VALUE_MIN <= observed <= _ALTITUDE_VALUE_MAX
        and 0 < optimal <= _ALTITUDE_OPTIMAL_MAX
    )


def _representative(raw: list[GapData]) -> dict:
    """Select the most severe occurrence as the representative gap."""
    severity_order = {"alta": 3, "media": 2, "baja": 1}
    worst = max(
        raw,
        key=lambda g: (severity_order.get(str(g.severity or "").lower(), 0), abs(g.gap_value)),
    )
    return {
        "observed_value": worst.observed_value,
        "optimal_limit": worst.optimal_limit,
        "gap_value": worst.gap_value,
        "gap_direction": worst.gap_direction,
        "severity": worst.severity,
    }


def _priority_score(gap_class: GapClass, severity: str | None, recurrence: int) -> float:
    s = _SEVERITY_WEIGHT.get(str(severity or "").lower(), 0.0)
    r = min(recurrence, 7) / 7.0
    c = _CLASS_MULTIPLIER.get(gap_class, 0.5)
    return round(s * r * c, 3)


def _dominant_structural(raw: list[GapData]) -> bool:
    intervention_class = raw[0].intervention_class if raw else None
    if intervention_class != "STRUCTURAL":
        return False
    high_severity = sum(1 for g in raw if str(g.severity or "").lower() == "alta")
    return high_severity >= 2


def _needs_rulebook_review(
    gap_class: GapClass,
    severity: str | None,
    recurrence: int,
    raw: list[GapData],
) -> bool:
    if gap_class != GapClass.STRUCTURAL_NOT_CORRECTABLE:
        return False
    return str(severity or "").lower() == "alta" and recurrence >= 3


def _find_ruling_barriers(groups: list[GapGroup]) -> list[str]:
    return [
        g.criterion_name or g.criterion_id
        for g in groups
        if g.gap_class == GapClass.STRUCTURAL_NOT_CORRECTABLE
        and str(g.representative_severity or "").lower() == "alta"
    ]
