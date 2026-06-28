"""Seed multivariable diagnostic rulebooks para VIABILIDAD POTENCIAL DE PARCELA — VIA.

Usage (PowerShell):
    $env:DATABASE_URL="postgresql+psycopg2://via_user:via_password@localhost:5433/via_test"
    python scripts/seed_multivariable_diagnostic_rulebooks.py

FIXTURE DIAGNOSTICO MULTIVARIABLE PARA VIABILIDAD POTENCIAL - no es guia agronomica oficial.
Umbrales derivados de bibliografía de modelamiento agroecológico en el Perú.
No corresponde a datos INIA ni constituye guía agronómica completa ni validada.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OBJETIVO DEL MODELO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

VIA evalúa VIABILIDAD POTENCIAL DE LA PARCELA, no el estado actual de un
cultivo establecido.

Pregunta que responde:
    ¿La parcela tiene condiciones estructurales compatibles con cultivar X?

Pregunta que NO responde:
    ¿Hay un cultivo de X activo hoy en esta parcela?

Una parcela con NDVI bajo puede estar en barbecho, recién cosechada,
preparada para siembra o sin cultivo instalado. Eso no implica inviabilidad
potencial. NDVI/SAVI/NDMI son variables de CONTEXTO AUXILIAR, no criterios
determinantes de aptitud potencial.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRITERIOS Y ROL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CRITERIOS FUERTES (estructurales, determinan aptitud potencial):
    aptitud_altitudinal        -> elevacion_m       (USGS/SRTMGL1_003)  peso=0.40
    aptitud_topografica        -> pendiente_grados  (USGS/SRTMGL1_003)  peso=0.30

CRITERIOS AUXILIARES (contexto superficial, no descartan por sí solos):
    cobertura_actual           -> ndvi              (COPERNICUS/S2_SR_HARMONIZED)  peso=0.10
    cobertura_suelo_ajustada   -> savi              (COPERNICUS/S2_SR_HARMONIZED)  peso=0.10
    humedad_vegetacion_auxiliar-> ndmi              (COPERNICUS/S2_SR_HARMONIZED)  peso=0.10

Los trapecios auxiliares son amplios para no colapsar el score por barbecho.
NDMI no se usa como indicador de anoxia, estrés hídrico letal ni exceso
hídrico por sí solo sin variables de suelo, drenaje o balance hídrico.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
POLÍTICAS CRÍTICAS (solo en criterios estructurales)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    demo_papa     aptitud_altitudinal  NO_VIABLE          (< 1500m: sin acumulación de frío para tubérculo)
    demo_quinua   aptitud_altitudinal  PENALIZE  0.60     (cultivares de bajío existen; altitud es limitante)
    demo_palta    aptitud_topografica  PENALIZE  0.80     (drenaje insuficiente en suelo plano < 1% pendiente)
    demo_arandano aptitud_topografica  PENALIZE  0.75     (fertirriego uniforme requiere pendiente ≤ 5%)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESULTADOS ESPERADOS — parcela de demo (Lima, 307m, pendiente 1.86°)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Valores GEE medidos (jun-2026):
    NDVI=0.099 SAVI=0.148 NDMI=0.128 Pendiente=1.86° Elevación=307m

Membresías con el nuevo diseño:
    Variable                Valor   Maíz  Papa  Quinua  Palta  Arándano
    cobertura_actual        0.099   1.00  1.00  1.00    1.00   1.00   (aux)
    cobertura_suelo_ajust.  0.148   1.00  1.00  1.00    1.00   1.00   (aux)
    humedad_veg_auxiliar    0.128   1.00  1.00  1.00    1.00   1.00   (aux)
    aptitud_topografica     1.86°   1.00  1.00  1.00    1.00   1.00
    aptitud_altitudinal     307m    1.00  0.00  0.11    0.38   1.00

Scores aproximados (WGM con pesos 0.40/0.30/0.10/0.10/0.10):
    Maíz      1.0^0.40 * 1.0^0.30 * ...   = 1.00  -> VIABLE
    Papa      0.0^0.40 * ...               = 0.00  -> NO_VIABLE  (política NO_VIABLE altitudinal)
    Quinua    0.11^0.40 * ...              ≈ 0.41  -> CONDICIONAL
    Palta     0.38^0.40 * ...              ≈ 0.68  -> CONDICIONAL
    Arándano  1.0^0.40 * ...               = 1.00  -> VIABLE

Interpretación: el modelo responde "¿puede cultivarse X aquí potencialmente?"
basándose en altitud y pendiente estructurales, con contexto auxiliar de
cobertura superficial que no colapsa el score en barbecho.

Nota sobre pendiente:
    Bibliografía reporta % ; GEE entrega grados.
    Conversión: grados = atan(pct/100) * 180/pi
    1%→0.57° 3%→1.72° 5%→2.86° 8%→4.57° 12%→6.84° 15%→8.53° 20%→11.31° 30%→16.70°
"""

from __future__ import annotations

import math
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

MULTI_DOC_SOURCE = (
    "FIXTURE DIAGNOSTICO MULTIVARIABLE PARA VIABILIDAD POTENCIAL - no es guia agronomica oficial. "
    "Umbrales derivados de bibliografía de modelamiento agroecológico en Perú. "
    "NDVI/SAVI/NDMI son variables auxiliares de contexto superficial; "
    "no determinan aptitud potencial por sí solos. "
    "No corresponde a datos INIA ni constituye guía agronómica completa."
)

MULTI_VERSION_NOTE = "fixture diagnostico multivariable viabilidad potencial"

MULTI_PHASES = (
    ("establecimiento", 30),
    ("desarrollo",      45),
    ("floracion",       35),
    ("maduracion",      40),
)

MULTI_CRITERIA = (
    "cobertura_actual",
    "cobertura_suelo_ajustada",
    "humedad_vegetacion_auxiliar",
    "aptitud_topografica",
    "aptitud_altitudinal",
)


# ─── Extraction bindings ──────────────────────────────────────────────────────

_BINDING_NDVI = ExtractionBinding(
    variable_name="ndvi",
    dataset_key="COPERNICUS/S2_SR_HARMONIZED",
    band="ndvi",
    unit="index",
    temporal_resolution="monthly",
    spatial_resolution=None,
    scale=10.0,
    reducer="mean",
    aggregation_method="mean",
    quality_mask=None,
    fallback_allowed=True,
)

_BINDING_SAVI = ExtractionBinding(
    variable_name="savi",
    dataset_key="COPERNICUS/S2_SR_HARMONIZED",
    band="savi",
    unit="index",
    temporal_resolution="monthly",
    spatial_resolution=None,
    scale=10.0,
    reducer="mean",
    aggregation_method="mean",
    quality_mask=None,
    fallback_allowed=True,
)

_BINDING_NDMI = ExtractionBinding(
    variable_name="ndmi",
    dataset_key="COPERNICUS/S2_SR_HARMONIZED",
    band="ndmi",
    unit="index",
    temporal_resolution="monthly",
    spatial_resolution=None,
    scale=20.0,
    reducer="mean",
    aggregation_method="mean",
    quality_mask=None,
    fallback_allowed=True,
)

_BINDING_PENDIENTE = ExtractionBinding(
    variable_name="pendiente_grados",
    dataset_key="USGS/SRTMGL1_003",
    band="slope",
    unit="degrees",
    temporal_resolution="static",
    spatial_resolution=None,
    scale=30.0,
    reducer="mean",
    aggregation_method="mean",
    quality_mask=None,
    fallback_allowed=True,
)

_BINDING_ELEVACION = ExtractionBinding(
    variable_name="elevacion_m",
    dataset_key="USGS/SRTMGL1_003",
    band="elevation",
    unit="m",
    temporal_resolution="static",
    spatial_resolution=None,
    scale=30.0,
    reducer="mean",
    aggregation_method="mean",
    quality_mask=None,
    fallback_allowed=True,
)

_CRITERION_BINDING: dict[str, ExtractionBinding] = {
    "cobertura_actual":            _BINDING_NDVI,
    "cobertura_suelo_ajustada":    _BINDING_SAVI,
    "humedad_vegetacion_auxiliar": _BINDING_NDMI,
    "aptitud_topografica":         _BINDING_PENDIENTE,
    "aptitud_altitudinal":         _BINDING_ELEVACION,
}


# ─── Pesos AHP ────────────────────────────────────────────────────────────────
# Criterios estructurales (altitud, pendiente) dominan la decisión.
# Variables de sensor remoto de cobertura actual son auxiliares (10% c/u).
# Esta distribución aplica de forma uniforme a todos los cultivos.
# Sum = 1.00

_MULTI_INTERVENTION_CLASS: dict[str, InterventionClass] = {
    "aptitud_altitudinal":         InterventionClass.STRUCTURAL,
    "aptitud_topografica":         InterventionClass.MITIGABLE,
    "cobertura_actual":            InterventionClass.MITIGABLE,
    "cobertura_suelo_ajustada":    InterventionClass.MITIGABLE,
    "humedad_vegetacion_auxiliar": InterventionClass.MITIGABLE,
}

_MULTI_AHP_WEIGHTS: dict[str, float] = {
    "aptitud_altitudinal":         0.40,
    "aptitud_topografica":         0.30,
    "cobertura_actual":            0.10,
    "cobertura_suelo_ajustada":    0.10,
    "humedad_vegetacion_auxiliar": 0.10,
}

_MULTI_PHASE_WEIGHTS: tuple[float, ...] = (0.25, 0.40, 0.25, 0.10)


# ─── Políticas críticas ───────────────────────────────────────────────────────
# SOLO sobre criterios estructurales (altitud, pendiente).
# NDVI / SAVI / NDMI no tienen políticas críticas.

_CRITICAL_MULTI_SPECS: dict[tuple[str, str], tuple[CriticalPolicy, float | None]] = {
    # Papa no puede producir bajo los 1500 m.s.n.m.: fisiología de tubérculo
    # requiere acumulación de horas de frío que no se alcanza en bajíos.
    ("demo_papa",     "aptitud_altitudinal"): (CriticalPolicy.NO_VIABLE, None),
    # Quinua tiene cultivares de bajío, pero la altitud es limitante estructural.
    # Ref bibliográfica: óptimo andino 2800-3900 m; cultivares de bajío desde 0 m.
    ("demo_quinua",   "aptitud_altitudinal"): (CriticalPolicy.PENALIZE,  0.60),
    # Palta necesita drenaje obligatorio (mínimo 1% pendiente para evitar anegamiento
    # y patógenos radiculares).  Ref: límite inferior bibliográfico a=1% → 0.57°.
    ("demo_palta",    "aptitud_topografica"): (CriticalPolicy.PENALIZE,  0.80),
    # Arándano requiere topografía muy plana para fertirriego por goteo uniforme.
    # Ref: límite bibliográfico 0-5%; pendiente > 12% → μ=0.
    ("demo_arandano", "aptitud_topografica"): (CriticalPolicy.PENALIZE,  0.75),
}


# ─── Conversión pendiente % → grados ─────────────────────────────────────────

def _deg(pct: float) -> float:
    """Convert slope percentage to degrees (rounded to 2 decimal places)."""
    return round(math.atan(pct / 100.0) * (180.0 / math.pi), 2)


# ─── Trapecios ────────────────────────────────────────────────────────────────
#
# CRITERIOS AUXILIARES (NDVI / SAVI / NDMI)
# ─────────────────────────────────────────
# Trapecios amplios iguales para todos los cultivos.
# El objetivo es detectar condiciones extremas (cuerpos de agua, roca
# desnuda, inundación severa), NO sancionar barbecho ni suelo preparado.
#
# cobertura_actual (NDVI): (-0.10, 0.05, 0.90, 1.00)
#   μ=1 para cualquier valor entre 0.05 y 0.90.
#   NDVI=0.099 (suelo preparado/barbecho) → μ=1.0.
#   Solo da μ=0 si NDVI < -0.10 (cuerpo de agua) o > 1.0 (imposible).
#
# cobertura_suelo_ajustada (SAVI): (-0.10, 0.05, 0.90, 1.00)
#   Mismo criterio que NDVI pero compensado por suelo expuesto.
#
# humedad_vegetacion_auxiliar (NDMI): (-0.50, -0.10, 0.60, 0.80)
#   μ=1 en rango de suelo agrícola normal a moderadamente húmedo.
#   Solo da μ=0 en extremos severos (suelo hiperárido < -0.50 o
#   inundación permanente > 0.80). No implica anoxia ni estrés letal.

_AUX_NDVI = (-0.10,  0.05, 0.90, 1.00)
_AUX_SAVI = (-0.10,  0.05, 0.90, 1.00)
_AUX_NDMI = (-0.50, -0.10, 0.60, 0.80)


# CRITERIOS FUERTES (elevación / pendiente)
# ─────────────────────────────────────────
# Trapecios per-cultivo derivados de bibliografía agronómica peruana.
# Pendiente convertida de % a grados: grados = atan(pct/100) * 180/pi

# ── Papa (Solanum tuberosum L.) ───────────────────────────────────────────────
# Elevación: acumulación de frío; óptimo 2800-3800 m; < 1500m inviable.
# Pendiente: óptimo 0-12% para mecanización; límite erosión 30%.
_PAPA_PEND = (0.0,        0.0,        _deg(12), _deg(30))
_PAPA_ELEV = (1500,       2800,       3800,     4200)

# ── Maíz (Zea mays L.) ────────────────────────────────────────────────────────
# Elevación: máxima productividad 0-1800 m; límite térmico 2800 m.
# Pendiente: óptimo 0-8%; límite 20%.
_MAIZ_PEND = (0.0,        0.0,        _deg(8),  _deg(20))
_MAIZ_ELEV = (0,          0,          1800,     2800)

# ── Quinua (Chenopodium quinoa Willd.) ────────────────────────────────────────
# Elevación: óptimo andino 2800-3900 m; cultivares de bajío desde 0 m.
# Pendiente: siembra mecanizada 0-12%; manual hasta 25%.
_QUIN_PEND = (0.0,        0.0,        _deg(12), _deg(25))
_QUIN_ELEV = (0,          2800,       3900,     4100)

# ── Palta Hass (Persea americana Mill.) ───────────────────────────────────────
# Elevación: valles interandinos 800-2200 m; portainjertos permiten cota 0.
# Pendiente: drenaje obligatorio (a=1%); óptimo 3-15%; límite 30%.
_PALT_PEND = (_deg(1),    _deg(3),    _deg(15), _deg(30))
_PALT_ELEV = (0,          800,        2200,     2500)

# ── Arándano (Vaccinium corymbosum L.) ────────────────────────────────────────
# Elevación: costero y de bajío; límite 1800 m por necesidades térmicas.
# Pendiente: muy restrictivo 0-5% para fertirriego uniforme; límite 12%.
_ARAN_PEND = (0.0,        0.0,        _deg(5),  _deg(12))
_ARAN_ELEV = (0,          0,          1000,     1800)


# ─── Tabla de trapecios por (cultivo, criterio) y fase ───────────────────────
# Auxiliares: mismo trapecio amplio para todos los cultivos.
# Fuertes: trapecio bibliográfico per-cultivo.
# Las 4 fases fenológicas usan el mismo trapecio; la bibliografía consultada
# no desagrega umbrales por fase fenológica.

_TRAP_MULTI: dict[tuple[str, str], tuple] = {
    # ── Maíz ──────────────────────────────────────────────────────────────────
    ("demo_maiz", "cobertura_actual"):            (_AUX_NDVI,) * 4,
    ("demo_maiz", "cobertura_suelo_ajustada"):    (_AUX_SAVI,) * 4,
    ("demo_maiz", "humedad_vegetacion_auxiliar"): (_AUX_NDMI,) * 4,
    ("demo_maiz", "aptitud_topografica"):         (_MAIZ_PEND,) * 4,
    ("demo_maiz", "aptitud_altitudinal"):         (_MAIZ_ELEV,) * 4,

    # ── Papa ──────────────────────────────────────────────────────────────────
    ("demo_papa", "cobertura_actual"):            (_AUX_NDVI,) * 4,
    ("demo_papa", "cobertura_suelo_ajustada"):    (_AUX_SAVI,) * 4,
    ("demo_papa", "humedad_vegetacion_auxiliar"): (_AUX_NDMI,) * 4,
    ("demo_papa", "aptitud_topografica"):         (_PAPA_PEND,) * 4,
    ("demo_papa", "aptitud_altitudinal"):         (_PAPA_ELEV,) * 4,

    # ── Quinua ────────────────────────────────────────────────────────────────
    ("demo_quinua", "cobertura_actual"):            (_AUX_NDVI,) * 4,
    ("demo_quinua", "cobertura_suelo_ajustada"):    (_AUX_SAVI,) * 4,
    ("demo_quinua", "humedad_vegetacion_auxiliar"): (_AUX_NDMI,) * 4,
    ("demo_quinua", "aptitud_topografica"):         (_QUIN_PEND,) * 4,
    ("demo_quinua", "aptitud_altitudinal"):         (_QUIN_ELEV,) * 4,

    # ── Palta ─────────────────────────────────────────────────────────────────
    ("demo_palta", "cobertura_actual"):            (_AUX_NDVI,) * 4,
    ("demo_palta", "cobertura_suelo_ajustada"):    (_AUX_SAVI,) * 4,
    ("demo_palta", "humedad_vegetacion_auxiliar"): (_AUX_NDMI,) * 4,
    ("demo_palta", "aptitud_topografica"):         (_PALT_PEND,) * 4,
    ("demo_palta", "aptitud_altitudinal"):         (_PALT_ELEV,) * 4,

    # ── Arándano ──────────────────────────────────────────────────────────────
    ("demo_arandano", "cobertura_actual"):            (_AUX_NDVI,) * 4,
    ("demo_arandano", "cobertura_suelo_ajustada"):    (_AUX_SAVI,) * 4,
    ("demo_arandano", "humedad_vegetacion_auxiliar"): (_AUX_NDMI,) * 4,
    ("demo_arandano", "aptitud_topografica"):         (_ARAN_PEND,) * 4,
    ("demo_arandano", "aptitud_altitudinal"):         (_ARAN_ELEV,) * 4,
}


# ─── Core functions ───────────────────────────────────────────────────────────


def seed_multivariable_diagnostic_rulebooks(
    session_factory: Callable,
    cleanup_func: Callable[[Session], None] | None = None,
    repository_factory: Callable[[Session], RulebookRepositoryLike] | None = None,
) -> list[SeededRulebook]:
    """Replace existing demo rulebooks with multivariable potential-viability versions."""

    session = session_factory()
    try:
        resolved_cleanup = cleanup_func or remove_existing_demo_rulebooks
        resolved_repository_factory = repository_factory or SqlAlchemyRulebookRepository
        resolved_cleanup(session)
        seeded = create_and_publish_multivariable_rulebooks(resolved_repository_factory(session))
        session.commit()
        return seeded
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_and_publish_multivariable_rulebooks(
    repository: RulebookRepositoryLike,
) -> list[SeededRulebook]:
    """Create and publish one active multivariable rulebook per demo crop."""

    service = RulebookCommandService(repository=repository)
    seeded: list[SeededRulebook] = []
    for crop_id, display_name in DEMO_CROPS.items():
        criteria, phases, requirements = build_multivariable_rulebook_parts(crop_id)
        rulebook = service.create_rulebook(
            crop_id=crop_id,
            criteria=criteria,
            phases=phases,
            phase_requirements=requirements,
        )
        service.publish_rulebook(rulebook.id)
        seeded.append(_summary(rulebook, display_name))
    return seeded


def build_multivariable_rulebook_parts(
    crop_id: str,
) -> tuple[list[Criterion], list[PhenologicalPhase], list[PhaseRequirement]]:
    """Build the full multivariable rulebook graph for one demo crop."""

    if crop_id not in DEMO_CROPS:
        raise ValueError(f"Unknown demo crop: {crop_id!r}")

    criteria = [_build_criterion(crop_id, name) for name in MULTI_CRITERIA]
    phases = [
        PhenologicalPhase(
            id=_stable_id(crop_id, "phase", phase_name),
            name=phase_name,
            duration_days=duration_days,
            sequence_order=index,
        )
        for index, (phase_name, duration_days) in enumerate(MULTI_PHASES, start=1)
    ]
    requirements = [
        _build_requirement(crop_id, criterion, phase, phase_idx)
        for criterion in criteria
        for phase_idx, phase in enumerate(phases)
    ]
    return criteria, phases, requirements


# ─── Builders ─────────────────────────────────────────────────────────────────


def _build_criterion(crop_id: str, criterion_name: str) -> Criterion:
    key = (crop_id, criterion_name)
    binding = _CRITERION_BINDING[criterion_name]
    is_auxiliary = binding.variable_name in ("ndvi", "savi", "ndmi")

    if key in _CRITICAL_MULTI_SPECS:
        policy, penalty_factor = _CRITICAL_MULTI_SPECS[key]
        is_critical = True
    else:
        policy = None
        penalty_factor = None
        is_critical = False

    role_note = (
        "variable auxiliar de contexto superficial; "
        "no determina aptitud potencial por sí sola. "
        "Trapecio amplio: no descarta por barbecho ni suelo preparado."
        if is_auxiliary
        else "criterio estructural de aptitud potencial de parcela."
    )

    return Criterion(
        id=_stable_id(crop_id, "criterion", criterion_name),
        name=criterion_name,
        is_critical=is_critical,
        critical_policy=policy,
        penalty_factor=penalty_factor,
        ahp_weight=_MULTI_AHP_WEIGHTS[criterion_name],
        doc_source=MULTI_DOC_SOURCE,
        intervention_class=_MULTI_INTERVENTION_CLASS[criterion_name],
        technical_notes=(
            f"{MULTI_VERSION_NOTE}. "
            f"Criterio '{criterion_name}' mapeado a {binding.variable_name} "
            f"({binding.dataset_key}). {role_note}"
        ),
    )


def _build_requirement(
    crop_id: str,
    criterion: Criterion,
    phase: PhenologicalPhase,
    phase_idx: int,
) -> PhaseRequirement:
    trap = _TRAP_MULTI[(crop_id, criterion.name)][phase_idx]
    binding = _CRITERION_BINDING[criterion.name]
    return PhaseRequirement(
        id=_stable_id(crop_id, "requirement", criterion.name, phase.name),
        criterion_id=criterion.id,
        phase_id=phase.id,
        membership_fn=MembershipFunction(a=trap[0], b=trap[1], c=trap[2], d=trap[3]),
        phase_weight=_MULTI_PHASE_WEIGHTS[phase_idx],
        temporal_periods=[
            TemporalPeriod(
                period_key=f"{phase.name}_multi",
                temporal_weight=1.0,
            )
        ],
        extraction_binding=binding,
    )


# ─── Entry point ──────────────────────────────────────────────────────────────


def main() -> None:
    """Run the multivariable seed from DATABASE_URL and print a summary."""

    database_url = require_database_url()
    engine = create_engine(database_url, future=True)
    try:
        session_factory = sessionmaker(bind=engine, class_=Session, autoflush=False, expire_on_commit=False)
        seeded = seed_multivariable_diagnostic_rulebooks(session_factory)
    finally:
        engine.dispose()

    print("Seeded multivariable diagnostic rulebooks (viabilidad potencial de parcela):")
    for item in seeded:
        print(f"  {item.crop_id} ({item.display_name}): {item.status} v{item.version} {item.rulebook_id}")
    print()
    print("AVISO: FIXTURE DIAGNOSTICO MULTIVARIABLE PARA VIABILIDAD POTENCIAL")
    print("       NDVI/SAVI/NDMI son contexto auxiliar (peso=0.10 c/u).")
    print("       Altitud (0.40) y pendiente (0.30) dominan el score.")
    print()
    print("       Resultados esperados (parcela costera 307m, pendiente 1.86°):")
    print("         demo_maiz     -> VIABLE       (óptimo para bajío costero)")
    print("         demo_papa     -> NO_VIABLE    (< 1500m: fisiología de tubérculo)")
    print("         demo_quinua   -> CONDICIONAL  (bajío posible pero subóptimo)")
    print("         demo_palta    -> CONDICIONAL  (por debajo del óptimo altitudinal)")
    print("         demo_arandano -> VIABLE       (costero comercial ideal)")


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _stable_id(crop_id: str, *parts: str) -> UUID:
    return uuid5(NAMESPACE_URL, ":".join(("via-multi-rulebook", crop_id, *parts)))


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
