"""Seed diagnostic rulebooks for VIA differentiated MCDA testing.

Usage (PowerShell):
    $env:DATABASE_URL="postgresql+psycopg2://via_user:via_password@localhost:5433/via_test"
    python scripts/seed_diagnostic_rulebooks.py

These rulebooks are DIAGNOSTIC FIXTURES designed to produce visibly differentiated
MCDA scores, expose agronomic gaps (brechas), and exercise all three viability
categories (VIABLE / CONDICIONAL / NO_VIABLE). They are not agronomic
recommendations and do not represent INIA data or real scientific thresholds.

All five criteria map to Sentinel-2 B8 (nir_reflectancia) so the full evaluation
pipeline can run today with the real GEE integration. Trapezoids are calibrated
for typical B8 Sentinel-2 SR values (~4000–6000) observed at the demo location.

Expected outcomes with typical B8 values (~5137):
  demo_maiz     → VIABLE         (score ≈ 0.93,  minimal brechas)
  demo_papa     → VIABLE medio   (score ≈ 0.74,  brechas en desarrollo / floracion)
  demo_quinua   → CONDICIONAL    (score ≈ 0.62,  múltiples brechas)
  demo_palta    → CONDICIONAL    (score ≈ 0.50,  brechas severas, criterio crítico)
  demo_arandano → NO_VIABLE      (vegetacion_vigor crítico NO_VIABLE → forzado)
"""

from __future__ import annotations

import os
import pathlib
import sys
from collections.abc import Callable
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from via.bounded_contexts.rulebook_management.application.command_service import RulebookCommandService
from via.bounded_contexts.rulebook_management.domain.criterion import Criterion
from via.bounded_contexts.rulebook_management.domain.phase_requirement import ExtractionBinding, PhaseRequirement
from via.bounded_contexts.rulebook_management.domain.phenological_phase import PhenologicalPhase
from via.bounded_contexts.rulebook_management.domain.rulebook import Rulebook
from via.bounded_contexts.rulebook_management.domain.value_objects import CriticalPolicy, InterventionClass, MembershipFunction, TemporalPeriod
from via.bounded_contexts.rulebook_management.infrastructure.rulebook_repository import SqlAlchemyRulebookRepository

_SCRIPTS_DIR = pathlib.Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from seed_demo_rulebooks import (  # noqa: E402
    DEMO_CROPS,
    RulebookRepositoryLike,
    SeededRulebook,
    remove_existing_demo_rulebooks,
    require_database_url,
)


# ─── Metadata ─────────────────────────────────────────────────────────────────

DIAG_DOC_SOURCE = (
    "FIXTURE DIAGNOSTICO - no es guia agronomica, no corresponde a datos INIA. "
    "Disenado para generar puntajes MCDA diferenciados y ejercitar todas las "
    "ramas de politica (VIABLE / CONDICIONAL / NO_VIABLE)."
)

DIAG_VERSION_NOTE = "fixture diagnostico diferenciado"

DIAG_PHASES = (
    ("establecimiento", 30),
    ("desarrollo",      45),
    ("floracion",       35),
    ("maduracion",      40),
)

DIAG_CRITERIA = (
    "vegetacion_vigor",
    "humedad_superficial",
    "estres_hidrico",
    "estabilidad_fenologica",
    "aptitud_general",
)

# Reuses the same Sentinel-2 B8 extraction binding as the basic demo so that
# the full evaluation pipeline (GEE → MCDA) can run without additional setup.
DIAG_EXTRACTION_BINDING = ExtractionBinding(
    variable_name="nir_reflectancia",
    dataset_key="COPERNICUS/S2_SR_HARMONIZED",
    band="B8",
    unit="reflectance_scaled",
    temporal_resolution="monthly",
    spatial_resolution=None,
    scale=30.0,
    reducer="mean",
    aggregation_method="mean",
    quality_mask=None,
    fallback_allowed=True,
)


# ─── Trapezoid templates ──────────────────────────────────────────────────────
# Calibrated for typical Sentinel-2 B8 SR values at the demo location (~5137).
# Format: (a, b, c, d) for the trapezoidal membership function.
# Approximate membership at 5137:
#   _PLATEAU   → 1.000  (5137 lies in the plateau [b, c])
#   _NEAR_TOP  → 0.812  (5137 in the upper ascending ramp)
#   _MID_RAMP  → 0.625  (5137 in the middle of the ascending ramp)
#   _LOW_RAMP  → 0.455  (5137 in the lower part of the ascending ramp)
#   _BELOW     → 0.000  (5137 falls below the support, a > 5137)

_PLATEAU  = (3000.0,  4000.0,  8000.0, 10000.0)
_NEAR_TOP = (4000.0,  5400.0,  8000.0, 10000.0)
_MID_RAMP = (4200.0,  5700.0,  8000.0, 10000.0)
_LOW_RAMP = (4500.0,  5900.0,  8000.0, 10000.0)
_BELOW    = (5500.0,  7000.0,  9000.0, 10000.0)


# ─── AHP weights ──────────────────────────────────────────────────────────────
# Non-uniform weights derived from a simplified AHP procedure.  Sum = 1.00.
_AHP_WEIGHTS: dict[str, float] = {
    "vegetacion_vigor":       0.35,
    "estres_hidrico":         0.25,
    "humedad_superficial":    0.20,
    "estabilidad_fenologica": 0.12,
    "aptitud_general":        0.08,
}

# ─── Phase weights ────────────────────────────────────────────────────────────
# Applied uniformly across all criteria.  Order matches DIAG_PHASES.  Sum = 1.00.
_PHASE_WEIGHTS: tuple[float, ...] = (0.25, 0.40, 0.25, 0.10)


# ─── Trapezoid profile ────────────────────────────────────────────────────────
# Key: (crop_id, criterion_name)
# Value: 4-tuple of (a,b,c,d) traps in phase order: est / des / flo / mad.
_TRAP_PROFILE: dict[tuple[str, str], tuple] = {
    # demo_maiz — near-optimal; near-plateau across all phases and criteria
    ("demo_maiz", "vegetacion_vigor"):       (_PLATEAU,  _PLATEAU,  _PLATEAU,  _PLATEAU ),
    ("demo_maiz", "estres_hidrico"):         (_PLATEAU,  _NEAR_TOP, _PLATEAU,  _PLATEAU ),
    ("demo_maiz", "humedad_superficial"):    (_PLATEAU,  _PLATEAU,  _NEAR_TOP, _PLATEAU ),
    ("demo_maiz", "estabilidad_fenologica"): (_NEAR_TOP, _PLATEAU,  _PLATEAU,  _PLATEAU ),
    ("demo_maiz", "aptitud_general"):        (_PLATEAU,  _PLATEAU,  _PLATEAU,  _PLATEAU ),

    # demo_papa — moderate; mid-ramp in desarrollo introduces visible brechas
    ("demo_papa", "vegetacion_vigor"):       (_NEAR_TOP, _MID_RAMP, _NEAR_TOP, _PLATEAU ),
    ("demo_papa", "estres_hidrico"):         (_NEAR_TOP, _LOW_RAMP, _MID_RAMP, _NEAR_TOP),
    ("demo_papa", "humedad_superficial"):    (_PLATEAU,  _NEAR_TOP, _NEAR_TOP, _PLATEAU ),
    ("demo_papa", "estabilidad_fenologica"): (_NEAR_TOP, _MID_RAMP, _NEAR_TOP, _PLATEAU ),
    ("demo_papa", "aptitud_general"):        (_PLATEAU,  _NEAR_TOP, _PLATEAU,  _PLATEAU ),

    # demo_quinua — suboptimal; mid-ramp dominates all criteria
    ("demo_quinua", "vegetacion_vigor"):       (_MID_RAMP, _MID_RAMP, _MID_RAMP, _NEAR_TOP),
    ("demo_quinua", "estres_hidrico"):         (_MID_RAMP, _LOW_RAMP, _MID_RAMP, _MID_RAMP),
    ("demo_quinua", "humedad_superficial"):    (_MID_RAMP, _MID_RAMP, _MID_RAMP, _MID_RAMP),
    ("demo_quinua", "estabilidad_fenologica"): (_NEAR_TOP, _LOW_RAMP, _MID_RAMP, _NEAR_TOP),
    ("demo_quinua", "aptitud_general"):        (_NEAR_TOP, _MID_RAMP, _NEAR_TOP, _NEAR_TOP),

    # demo_palta — poor; low-ramp dominates, critical criterion shows brechas severas
    ("demo_palta", "vegetacion_vigor"):       (_LOW_RAMP, _LOW_RAMP, _MID_RAMP, _MID_RAMP),
    ("demo_palta", "estres_hidrico"):         (_LOW_RAMP, _LOW_RAMP, _LOW_RAMP, _LOW_RAMP),
    ("demo_palta", "humedad_superficial"):    (_MID_RAMP, _LOW_RAMP, _LOW_RAMP, _MID_RAMP),
    ("demo_palta", "estabilidad_fenologica"): (_LOW_RAMP, _MID_RAMP, _LOW_RAMP, _LOW_RAMP),
    ("demo_palta", "aptitud_general"):        (_MID_RAMP, _LOW_RAMP, _MID_RAMP, _NEAR_TOP),

    # demo_arandano — NO_VIABLE forced by vegetacion_vigor critical criterion
    # a=5500 > 5137 → membership = 0.0 in all phases → criterion membership = 0.0
    ("demo_arandano", "vegetacion_vigor"):       (_BELOW,    _BELOW,    _BELOW,    _BELOW   ),
    ("demo_arandano", "estres_hidrico"):         (_LOW_RAMP, _LOW_RAMP, _MID_RAMP, _MID_RAMP),
    ("demo_arandano", "humedad_superficial"):    (_MID_RAMP, _LOW_RAMP, _LOW_RAMP, _MID_RAMP),
    ("demo_arandano", "estabilidad_fenologica"): (_MID_RAMP, _LOW_RAMP, _MID_RAMP, _MID_RAMP),
    ("demo_arandano", "aptitud_general"):        (_MID_RAMP, _MID_RAMP, _MID_RAMP, _MID_RAMP),
}

# ─── Critical criteria ────────────────────────────────────────────────────────
# Key: (crop_id, criterion_name)
# Value: (CriticalPolicy, penalty_factor | None)
_CRITICAL_SPECS: dict[tuple[str, str], tuple[CriticalPolicy, float | None]] = {
    ("demo_papa",     "estres_hidrico"):   (CriticalPolicy.PENALIZE,  0.50),
    ("demo_quinua",   "estres_hidrico"):   (CriticalPolicy.PENALIZE,  0.40),
    ("demo_palta",    "estres_hidrico"):   (CriticalPolicy.PENALIZE,  0.30),
    ("demo_arandano", "vegetacion_vigor"): (CriticalPolicy.NO_VIABLE, None),
}


# ─── Core functions ───────────────────────────────────────────────────────────


def seed_diagnostic_rulebooks(
    session_factory: Callable,
    cleanup_func: Callable[[Session], None] | None = None,
    repository_factory: Callable[[Session], RulebookRepositoryLike] | None = None,
) -> list[SeededRulebook]:
    """Replace existing demo rulebooks with diagnostic versions and publish them."""

    session = session_factory()
    try:
        resolved_cleanup = cleanup_func or remove_existing_demo_rulebooks
        resolved_repository_factory = repository_factory or SqlAlchemyRulebookRepository
        resolved_cleanup(session)
        seeded = create_and_publish_diagnostic_rulebooks(resolved_repository_factory(session))
        session.commit()
        return seeded
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_and_publish_diagnostic_rulebooks(
    repository: RulebookRepositoryLike,
) -> list[SeededRulebook]:
    """Create and publish one active diagnostic rulebook per demo crop."""

    service = RulebookCommandService(repository=repository)
    seeded: list[SeededRulebook] = []
    for crop_id, display_name in DEMO_CROPS.items():
        criteria, phases, requirements = build_diagnostic_rulebook_parts(crop_id)
        rulebook = service.create_rulebook(
            crop_id=crop_id,
            criteria=criteria,
            phases=phases,
            phase_requirements=requirements,
        )
        service.publish_rulebook(rulebook.id)
        seeded.append(_summary(rulebook, display_name))
    return seeded


def build_diagnostic_rulebook_parts(
    crop_id: str,
) -> tuple[list[Criterion], list[PhenologicalPhase], list[PhaseRequirement]]:
    """Build the full diagnostic rulebook graph for one demo crop."""

    if crop_id not in DEMO_CROPS:
        raise ValueError(f"Unknown demo crop: {crop_id!r}")

    criteria = [
        _build_criterion(crop_id, criterion_name)
        for criterion_name in DIAG_CRITERIA
    ]
    phases = [
        PhenologicalPhase(
            id=_stable_id(crop_id, "phase", phase_name),
            name=phase_name,
            duration_days=duration_days,
            sequence_order=index,
        )
        for index, (phase_name, duration_days) in enumerate(DIAG_PHASES, start=1)
    ]
    requirements = [
        _build_requirement(crop_id, criterion, phase, phase_idx)
        for criterion in criteria
        for phase_idx, phase in enumerate(phases)
    ]
    return criteria, phases, requirements


# ─── Builders ────────────────────────────────────────────────────────────────


def _build_criterion(crop_id: str, criterion_name: str) -> Criterion:
    key = (crop_id, criterion_name)
    if key in _CRITICAL_SPECS:
        policy, penalty_factor = _CRITICAL_SPECS[key]
        is_critical = True
    else:
        policy = None
        penalty_factor = None
        is_critical = False

    return Criterion(
        id=_stable_id(crop_id, "criterion", criterion_name),
        name=criterion_name,
        is_critical=is_critical,
        critical_policy=policy,
        penalty_factor=penalty_factor,
        ahp_weight=_AHP_WEIGHTS[criterion_name],
        doc_source=DIAG_DOC_SOURCE,
        intervention_class=InterventionClass.MITIGABLE,
        technical_notes=(
            f"{DIAG_VERSION_NOTE}. Criterio mapeado a "
            f"{DIAG_EXTRACTION_BINDING.variable_name} (Sentinel-2 B8); "
            f"umbrales sinteticos, no datos INIA."
        ),
    )


def _build_requirement(
    crop_id: str,
    criterion: Criterion,
    phase: PhenologicalPhase,
    phase_idx: int,
) -> PhaseRequirement:
    trap = _TRAP_PROFILE[(crop_id, criterion.name)][phase_idx]
    return PhaseRequirement(
        id=_stable_id(crop_id, "requirement", criterion.name, phase.name),
        criterion_id=criterion.id,
        phase_id=phase.id,
        membership_fn=MembershipFunction(a=trap[0], b=trap[1], c=trap[2], d=trap[3]),
        phase_weight=_PHASE_WEIGHTS[phase_idx],
        temporal_periods=[
            TemporalPeriod(
                period_key=f"{phase.name}_diag",
                temporal_weight=1.0,
            )
        ],
        extraction_binding=DIAG_EXTRACTION_BINDING,
    )


# ─── Entry point ──────────────────────────────────────────────────────────────


def main() -> None:
    """Run the diagnostic seed from DATABASE_URL and print a summary."""

    database_url = require_database_url()
    engine = create_engine(database_url, future=True)
    try:
        session_factory = sessionmaker(bind=engine, class_=Session, autoflush=False, expire_on_commit=False)
        seeded = seed_diagnostic_rulebooks(session_factory)
    finally:
        engine.dispose()

    print("Seeded diagnostic rulebooks (diferenciados):")
    for item in seeded:
        print(f"  {item.crop_id} ({item.display_name}): {item.status} v{item.version} {item.rulebook_id}")
    print()
    print("AVISO: Estos son fixtures diagnósticos, no datos INIA ni guía agronómica.")
    print("       Scores esperados con B8 ~5137:")
    print("         demo_maiz     → VIABLE         (≈ 0.93)")
    print("         demo_papa     → VIABLE medio   (≈ 0.74, con brechas)")
    print("         demo_quinua   → CONDICIONAL    (≈ 0.62)")
    print("         demo_palta    → CONDICIONAL    (≈ 0.50, brechas severas)")
    print("         demo_arandano → NO_VIABLE      (criterio crítico NO_VIABLE forzado)")


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _stable_id(crop_id: str, *parts: str) -> UUID:
    return uuid5(NAMESPACE_URL, ":".join(("via-diag-rulebook", crop_id, *parts)))


def _summary(rulebook: Rulebook, display_name: str) -> SeededRulebook:
    return SeededRulebook(
        crop_id=rulebook.crop_id,
        display_name=display_name,
        rulebook_id=rulebook.id,
        version=rulebook.version,
        status=rulebook.status.value,
    )


if __name__ == "__main__":
    main()
