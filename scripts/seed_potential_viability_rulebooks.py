"""Seed rulebooks para VIABILIDAD POTENCIAL DE PARCELA con variables climáticas y edáficas — VIA.

Usage (PowerShell):
    $env:DATABASE_URL="postgresql+psycopg2://via_user:via_password@localhost:5433/via_test"
    python scripts/seed_potential_viability_rulebooks.py

FIXTURE DIAGNOSTICO DE VIABILIDAD POTENCIAL - rangos agronomicamente plausibles, no guia oficial.
Umbrales derivados de bibliografía de modelamiento agroecológico en el Perú.
No corresponde a datos INIA ni constituye guía agronómica completa ni validada.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OBJETIVO DEL MODELO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

VIA evalúa VIABILIDAD POTENCIAL DE LA PARCELA, no el estado actual de un
cultivo establecido. Este seed incorpora variables climáticas de ERA5-Land y
CHIRPS, variables edáficas de OpenLandMap, y criterios estructurales SRTM.

Pregunta que responde:
    ¿Las condiciones climáticas, edáficas y estructurales de esta parcela son
    compatibles con cultivar X potencialmente?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRITERIOS, VARIABLES Y ROL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CRITERIOS CLIMÁTICOS (peso total 0.48):
    aptitud_termica          -> temperatura_media_c             (ERA5-Land)  0.12
    riesgo_frio              -> temperatura_minima_c            (ERA5-Land)  0.07
    riesgo_calor             -> temperatura_maxima_c            (ERA5-Land)  0.07
    disponibilidad_hidrica   -> precipitacion_acumulada_mm      (CHIRPS)     0.12
    deficit_hidrico          -> deficit_hidrico_mm              (derivado)   0.10

CRITERIOS ESTRUCTURALES TOPOGRÁFICOS (peso total 0.20):
    aptitud_altitudinal      -> elevacion_m                     (SRTM)       0.12
    aptitud_topografica      -> pendiente_grados                (SRTM)       0.08

CRITERIOS EDÁFICOS (peso total 0.27):
    reaccion_suelo_ph        -> ph_suelo                        (OpenLandMap) 0.10
    contenido_arcilla        -> arcilla_pct                     (OpenLandMap) 0.07
    contenido_arena          -> arena_pct                       (OpenLandMap) 0.06
    carbono_organico_suelo   -> carbono_organico_suelo          (OpenLandMap) 0.04

CRITERIO AUXILIAR DE SENSOR REMOTO (peso 0.05):
    cobertura_actual_auxiliar -> ndvi                           (Sentinel-2) 0.05

Suma total = 0.12+0.07+0.07+0.12+0.10+0.12+0.08+0.10+0.07+0.06+0.04+0.05 = 1.00

textura_suelo_clase (OpenLandMap) se extrae para trazabilidad pero NO es
criterio principal porque el motor MCDA requiere valores numéricos continuos;
la clase textural es categórica (entero 1–12 USDA).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
POLÍTICAS CRÍTICAS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    demo_papa     aptitud_altitudinal   NO_VIABLE         (< 1500m: sin acumulación de frío)
    demo_quinua   aptitud_altitudinal   PENALIZE  0.60    (altitud es limitante estructural)
    demo_palta    aptitud_topografica   PENALIZE  0.80    (drenaje en suelo plano < 1%)
    demo_arandano aptitud_topografica   PENALIZE  0.75    (fertirriego uniforme requiere <5%)

Los criterios edáficos no tienen políticas críticas en este seed. Las funciones
trapezoidales capturan gradualmente los rangos óptimos y el piso mínimo de
membresía no crítica (0.05) evita colapso del WGM por factores de calidad de suelo.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DATASETS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    TEMPERATURA (ERA5-Land): ECMWF/ERA5_LAND/MONTHLY_AGGR — ~11 132 m, mensual (1950–presente)
    PRECIPITACIÓN (CHIRPS): UCSB-CHG/CHIRPS/DAILY — ~5 566 m, diario (1981–presente)
    EVAPOTRANSPIRACIÓN: ERA5-Land potential_evaporation_sum (abs*1000 → mm)
    DÉFICIT HÍDRICO: max(0, ET_ref - P)
    TOPOGRAFÍA: USGS/SRTMGL1_003 — 30 m, estático
    SUELO (OpenLandMap v02): ~250 m, estático global, topsoil_0_30cm_mean de b0+b10+b30
        ph_suelo: SOL_PH-H2O_USDA-4C1A2A_M/v02 (raw × 0.1 → pH)
        arcilla_pct: SOL_CLAY-WFRACTION_USDA-3A1A1A_M/v02 (raw × 0.1 → %)
        arena_pct: SOL_SAND-WFRACTION_USDA-3A1A1A_M/v02 (raw × 0.1 → %)
        carbono_organico_suelo: SOL_ORGANIC-CARBON_USDA-6A1C_M/v02 (raw × 0.2 → g/kg)
    NDVI: COPERNICUS/S2_SR_HARMONIZED — 10 m, mensual

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
POLÍTICA DE SUFICIENCIA DE DATOS (umbral 0.30)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    Clima faltante (todos): 0.48 ≥ 0.30 → NO_CONCLUYENTE ✓
    Topo faltante (uno): _STRUCTURAL_CRITERIA → NO_CONCLUYENTE ✓
    Suelo todo faltante: 0.27 < 0.30 → PARCIAL (no bloquea por sí solo)
    Solo carbono faltante: 0.04 < 0.30 → PARCIAL ✓
    pH+arcilla+arena faltante: 0.23 < 0.30 → PARCIAL (tolerable si hay clima+topo)
    Suelo (0.27) + cualquier clima (≥0.07): 0.34+ ≥ 0.30 → NO_CONCLUYENTE ✓

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESULTADOS ESPERADOS — parcela demo (Lima costera, 307m, pendiente 1.86°)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Valores estimados para Lima (-76.0, -12.0):
    temp_media ~19°C  temp_min ~14°C  temp_max ~25°C
    precip ~15mm/año  pet ~1200mm/año  deficit ~1185mm/año
    elevacion 307m   pendiente 1.86°  NDVI ~0.099
    pH suelo ~7.5 (calcáreo costero)  arcilla ~20%  arena ~55%  OC ~4 g/kg

Aviso: VIA no modela irrigación. Lima costera tiene precipitación muy baja pero
los cultivos viables usualmente dependen de riego. La disponibilidad_hidrica
empieza en a=0 para no penalizar zonas irrigadas, pero el modelo no distingue
riego de secano. La brecha hídrica será tratada en el módulo de recomendaciones.
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
from via.bounded_contexts.rulebook_management.domain.value_objects import CriticalPolicy, MembershipFunction, TemporalPeriod
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

_DOC_SOURCE = (
    "FIXTURE DIAGNOSTICO DE VIABILIDAD POTENCIAL - rangos agronomicamente plausibles, no guia oficial. "
    "Variables climaticas: ECMWF/ERA5_LAND/MONTHLY_AGGR (ERA5-Land ~11km mensual) "
    "y UCSB-CHG/CHIRPS/DAILY (CHIRPS ~5.5km diario). "
    "Variables topograficas: USGS/SRTMGL1_003 (SRTM ~30m). "
    "Variables edaficas: OpenLandMap v02 (~250m, topsoil_0_30cm_mean): "
    "SOL_PH-H2O (pH), SOL_CLAY-WFRACTION (arcilla%), SOL_SAND-WFRACTION (arena%), "
    "SOL_ORGANIC-CARBON (carbono organico g/kg). "
    "Variable auxiliar NDVI: COPERNICUS/S2_SR_HARMONIZED. "
    "No corresponde a datos INIA ni constituye guia agronomica completa."
)

_VERSION_NOTE = (
    "fixture viabilidad potencial con variables climaticas ERA5-Land/CHIRPS, "
    "edaficas OpenLandMap topsoil_0_30cm_mean y topograficas SRTM"
)

_PHASES = (
    ("establecimiento", 30),
    ("desarrollo",      45),
    ("floracion",       35),
    ("maduracion",      40),
)

_CRITERIA = (
    "aptitud_termica",
    "riesgo_frio",
    "riesgo_calor",
    "disponibilidad_hidrica",
    "deficit_hidrico",
    "aptitud_altitudinal",
    "aptitud_topografica",
    "reaccion_suelo_ph",
    "contenido_arcilla",
    "contenido_arena",
    "carbono_organico_suelo",
    "cobertura_actual_auxiliar",
)

_SOIL_CRITERIA = frozenset({
    "reaccion_suelo_ph",
    "contenido_arcilla",
    "contenido_arena",
    "carbono_organico_suelo",
})


# ─── Dataset keys ─────────────────────────────────────────────────────────────

_ERA5   = "ECMWF/ERA5_LAND/MONTHLY_AGGR"
_CHIRPS = "UCSB-CHG/CHIRPS/DAILY"
_SRTM   = "USGS/SRTMGL1_003"
_S2     = "COPERNICUS/S2_SR_HARMONIZED"
_OLM_PH   = "OpenLandMap/SOL/SOL_PH-H2O_USDA-4C1A2A_M/v02"
_OLM_CLAY = "OpenLandMap/SOL/SOL_CLAY-WFRACTION_USDA-3A1A1A_M/v02"
_OLM_SAND = "OpenLandMap/SOL/SOL_SAND-WFRACTION_USDA-3A1A1A_M/v02"
_OLM_OC   = "OpenLandMap/SOL/SOL_ORGANIC-CARBON_USDA-6A1C_M/v02"


# ─── Extraction bindings ──────────────────────────────────────────────────────

_BINDING_TEMP_MEDIA = ExtractionBinding(
    variable_name="temperatura_media_c",
    dataset_key=_ERA5,
    band="temperature_2m",
    unit="celsius",
    temporal_resolution="monthly",
    spatial_resolution=None,
    scale=11132.0,
    reducer="mean",
    aggregation_method="mean",
    quality_mask=None,
    fallback_allowed=True,
)

_BINDING_TEMP_MIN = ExtractionBinding(
    variable_name="temperatura_minima_c",
    dataset_key=_ERA5,
    band="temperature_2m_min",
    unit="celsius",
    temporal_resolution="monthly",
    spatial_resolution=None,
    scale=11132.0,
    reducer="mean",
    aggregation_method="mean",
    quality_mask=None,
    fallback_allowed=True,
)

_BINDING_TEMP_MAX = ExtractionBinding(
    variable_name="temperatura_maxima_c",
    dataset_key=_ERA5,
    band="temperature_2m_max",
    unit="celsius",
    temporal_resolution="monthly",
    spatial_resolution=None,
    scale=11132.0,
    reducer="mean",
    aggregation_method="mean",
    quality_mask=None,
    fallback_allowed=True,
)

_BINDING_PRECIP = ExtractionBinding(
    variable_name="precipitacion_acumulada_mm",
    dataset_key=_CHIRPS,
    band="precipitation",
    unit="mm",
    temporal_resolution="daily",
    spatial_resolution=None,
    scale=5566.0,
    reducer="mean",
    aggregation_method="sum",
    quality_mask=None,
    fallback_allowed=True,
)

_BINDING_DEFICIT = ExtractionBinding(
    variable_name="deficit_hidrico_mm",
    dataset_key=_ERA5,
    band="deficit_hidrico_mm",
    unit="mm",
    temporal_resolution="derived",
    spatial_resolution=None,
    scale=11132.0,
    reducer="mean",
    aggregation_method="sum",
    quality_mask=None,
    fallback_allowed=True,
)

_BINDING_ELEVACION = ExtractionBinding(
    variable_name="elevacion_m",
    dataset_key=_SRTM,
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

_BINDING_PENDIENTE = ExtractionBinding(
    variable_name="pendiente_grados",
    dataset_key=_SRTM,
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

# OpenLandMap soil bindings — band stores depth_strategy for traceability
_BINDING_PH = ExtractionBinding(
    variable_name="ph_suelo",
    dataset_key=_OLM_PH,
    band="topsoil_0_30cm_mean",
    unit="pH",
    temporal_resolution="static",
    spatial_resolution=None,
    scale=250.0,
    reducer="mean",
    aggregation_method="mean",
    quality_mask=None,
    fallback_allowed=True,
)

_BINDING_CLAY = ExtractionBinding(
    variable_name="arcilla_pct",
    dataset_key=_OLM_CLAY,
    band="topsoil_0_30cm_mean",
    unit="%",
    temporal_resolution="static",
    spatial_resolution=None,
    scale=250.0,
    reducer="mean",
    aggregation_method="mean",
    quality_mask=None,
    fallback_allowed=True,
)

_BINDING_SAND = ExtractionBinding(
    variable_name="arena_pct",
    dataset_key=_OLM_SAND,
    band="topsoil_0_30cm_mean",
    unit="%",
    temporal_resolution="static",
    spatial_resolution=None,
    scale=250.0,
    reducer="mean",
    aggregation_method="mean",
    quality_mask=None,
    fallback_allowed=True,
)

_BINDING_OC = ExtractionBinding(
    variable_name="carbono_organico_suelo",
    dataset_key=_OLM_OC,
    band="topsoil_0_30cm_mean",
    unit="g/kg",
    temporal_resolution="static",
    spatial_resolution=None,
    scale=250.0,
    reducer="mean",
    aggregation_method="mean",
    quality_mask=None,
    fallback_allowed=True,
)

_BINDING_NDVI = ExtractionBinding(
    variable_name="ndvi",
    dataset_key=_S2,
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

_CRITERION_BINDING: dict[str, ExtractionBinding] = {
    "aptitud_termica":           _BINDING_TEMP_MEDIA,
    "riesgo_frio":               _BINDING_TEMP_MIN,
    "riesgo_calor":              _BINDING_TEMP_MAX,
    "disponibilidad_hidrica":    _BINDING_PRECIP,
    "deficit_hidrico":           _BINDING_DEFICIT,
    "aptitud_altitudinal":       _BINDING_ELEVACION,
    "aptitud_topografica":       _BINDING_PENDIENTE,
    "reaccion_suelo_ph":         _BINDING_PH,
    "contenido_arcilla":         _BINDING_CLAY,
    "contenido_arena":           _BINDING_SAND,
    "carbono_organico_suelo":    _BINDING_OC,
    "cobertura_actual_auxiliar": _BINDING_NDVI,
}


# ─── Pesos AHP ────────────────────────────────────────────────────────────────
# Clima: 0.48  Topografía: 0.20  Suelo: 0.27  Auxiliar remoto: 0.05
# Suma = 1.00

_AHP_WEIGHTS: dict[str, float] = {
    "aptitud_termica":           0.12,
    "riesgo_frio":               0.07,
    "riesgo_calor":              0.07,
    "disponibilidad_hidrica":    0.12,
    "deficit_hidrico":           0.10,
    "aptitud_altitudinal":       0.12,
    "aptitud_topografica":       0.08,
    "reaccion_suelo_ph":         0.10,
    "contenido_arcilla":         0.07,
    "contenido_arena":           0.06,
    "carbono_organico_suelo":    0.04,
    "cobertura_actual_auxiliar": 0.05,
}

_PHASE_WEIGHTS: tuple[float, ...] = (0.25, 0.40, 0.25, 0.10)


# ─── Políticas críticas ───────────────────────────────────────────────────────
# Suelo: sin políticas críticas — el piso mínimo de membresía no crítica (0.05)
# previene colapso del WGM. Las funciones trapezoidales capturan rangos óptimos.

_CRITICAL_SPECS: dict[tuple[str, str], tuple[CriticalPolicy, float | None]] = {
    ("demo_papa",     "aptitud_altitudinal"): (CriticalPolicy.NO_VIABLE, None),
    ("demo_quinua",   "aptitud_altitudinal"): (CriticalPolicy.PENALIZE,  0.60),
    ("demo_palta",    "aptitud_topografica"): (CriticalPolicy.PENALIZE,  0.80),
    ("demo_arandano", "aptitud_topografica"): (CriticalPolicy.PENALIZE,  0.75),
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _deg(pct: float) -> float:
    """Convert slope percentage to degrees."""
    return round(math.atan(pct / 100.0) * (180.0 / math.pi), 2)


def _all_phases(trap: tuple) -> tuple:
    """Return the same trapezoid for all 4 phenological phases."""
    return (trap,) * 4


# ─── Trapecios climáticos ─────────────────────────────────────────────────────
# Temperatura °C, precipitación mm, déficit hídrico mm, elevación m, pendiente °

_AUX_NDVI = (-0.10, 0.05, 0.90, 1.00)

# ── Papa (Solanum tuberosum L.)
_PAPA_T_MED  = (8,   12,  18,  24)
_PAPA_T_MIN  = (2,   6,   14,  20)
_PAPA_T_MAX  = (14,  18,  24,  28)
_PAPA_PRECIP = (0,   0,   700, 1400)
_PAPA_DEF    = (0,   0,   400, 1300)
_PAPA_PEND   = (0.0, 0.0, _deg(12), _deg(30))
_PAPA_ELEV   = (1500, 2800, 3800, 4200)

# ── Maíz (Zea mays L.)
_MAIZ_T_MED  = (12,  18,  28,  34)
_MAIZ_T_MIN  = (8,   12,  20,  26)
_MAIZ_T_MAX  = (18,  24,  32,  38)
_MAIZ_PRECIP = (0,   0,   800, 1600)
_MAIZ_DEF    = (0,   0,   700, 1500)
_MAIZ_PEND   = (0.0, 0.0, _deg(8),  _deg(20))
_MAIZ_ELEV   = (0,   0,   1800, 2800)

# ── Quinua (Chenopodium quinoa Willd.)
_QUIN_T_MED  = (5,   10,  18,  22)
_QUIN_T_MIN  = (-4,  2,   14,  20)
_QUIN_T_MAX  = (12,  18,  25,  30)
_QUIN_PRECIP = (0,   0,   500, 1000)
_QUIN_DEF    = (0,   0,   800, 1800)
_QUIN_PEND   = (0.0, 0.0, _deg(12), _deg(25))
_QUIN_ELEV   = (0,   2800, 3900, 4100)

# ── Palta Hass (Persea americana Mill.)
_PALT_T_MED  = (14,  18,  26,  30)
_PALT_T_MIN  = (6,   10,  20,  26)
_PALT_T_MAX  = (20,  24,  30,  36)
_PALT_PRECIP = (0,   0,   1000, 2000)
_PALT_DEF    = (0,   0,   300,  1400)
_PALT_PEND   = (_deg(1), _deg(3), _deg(15), _deg(30))
_PALT_ELEV   = (0,   800, 2200, 2500)

# ── Arándano (Vaccinium corymbosum L.)
_ARAN_T_MED  = (10,  14,  22,  28)
_ARAN_T_MIN  = (-6,  0,   14,  20)
_ARAN_T_MAX  = (14,  20,  28,  34)
_ARAN_PRECIP = (0,   0,   800, 1600)
_ARAN_DEF    = (0,   0,   400, 1500)
_ARAN_PEND   = (0.0, 0.0, _deg(5),  _deg(12))
_ARAN_ELEV   = (0,   0,   1000, 1800)


# ─── Trapecios edáficos ───────────────────────────────────────────────────────
#
# pH (real, después de conversión raw × 0.1):
#   Rango útil ~4.0–9.0. Óptimos por cultivo en bibliografía agroecológica.
#   Lima costera: pH ~7.0–8.0 (suelos calcáreos).
#
# Arcilla % (real, después de conversión raw × 0.1):
#   Suelos francos (~15–35% arcilla) son óptimos para la mayoría de cultivos.
#   Lima costera: ~15–25% arcilla.
#
# Arena % (real, después de conversión raw × 0.1):
#   Suelos francos (~35–65% arena) ofrecen buen balance retención/drenaje.
#   Lima costera: ~50–65% arena.
#
# Carbono orgánico g/kg (real, después de conversión raw × 0.2):
#   Lima costera: OC ~3–5 g/kg (suelo poco desarrollado sin materia orgánica).
#   Los rangos óptimos reflejan suelos agrícolas manejados (>8 g/kg deseable).

# ── pH por cultivo ──
# Papa: pH óptimo 5.5–6.8; tolera 4.8–8.0 (tubérculo sensible a alcalinidad)
_PAPA_PH   = (4.8, 5.5, 6.8, 8.0)
# Maíz: pH óptimo 6.0–7.2; tolera suelos neutros a ligeramente alcalinos
_MAIZ_PH   = (5.5, 6.0, 7.2, 8.0)
# Quinua: tolerante a suelos alcalinos; pH óptimo 6.0–7.5, tolera hasta 8.5
_QUIN_PH   = (5.5, 6.0, 7.5, 8.5)
# Palta: pH óptimo 6.0–7.0; sensible a suelos muy alcalinos (calcáreos)
_PALT_PH   = (5.5, 6.0, 7.0, 7.8)
# Arándano: ACIDÓFILO estricto; pH óptimo 4.5–5.5; > 6.5 da μ=0
_ARAN_PH   = (4.0, 4.5, 5.5, 6.5)

# ── Arcilla % por cultivo ──
# Amplio para no penalizar variaciones naturales; extremos (< 5% o > 65%) reducen μ
_PAPA_CLAY  = (5,  15, 35, 55)
_MAIZ_CLAY  = (5,  15, 40, 60)
_QUIN_CLAY  = (5,  10, 45, 65)
_PALT_CLAY  = (5,  10, 30, 50)
_ARAN_CLAY  = (5,  10, 30, 50)

# ── Arena % por cultivo ──
# Arándano prefiere suelos más arenosos; palta y papa prefieren francos
_PAPA_SAND  = (20, 35, 65, 80)
_MAIZ_SAND  = (15, 35, 65, 80)
_QUIN_SAND  = (15, 30, 70, 85)
_PALT_SAND  = (25, 40, 70, 85)
_ARAN_SAND  = (30, 40, 70, 85)

# ── Carbono orgánico g/kg por cultivo ──
# Lima costera (~3–5 g/kg) estará en rango bajo para todos los cultivos.
# Quinua es el más tolerante a suelos pobres; arándano prefiere suelos orgánicos.
_PAPA_OC   = (2, 5,  25, 50)
_MAIZ_OC   = (2, 5,  25, 50)
_QUIN_OC   = (1, 3,  25, 50)
_PALT_OC   = (2, 5,  30, 55)
_ARAN_OC   = (3, 8,  40, 70)


# ─── Tabla de trapecios ───────────────────────────────────────────────────────

_TRAP: dict[tuple[str, str], tuple] = {
    # ── Maíz ──────────────────────────────────────────────────────────────────
    ("demo_maiz", "aptitud_termica"):           _all_phases(_MAIZ_T_MED),
    ("demo_maiz", "riesgo_frio"):               _all_phases(_MAIZ_T_MIN),
    ("demo_maiz", "riesgo_calor"):              _all_phases(_MAIZ_T_MAX),
    ("demo_maiz", "disponibilidad_hidrica"):    _all_phases(_MAIZ_PRECIP),
    ("demo_maiz", "deficit_hidrico"):           _all_phases(_MAIZ_DEF),
    ("demo_maiz", "aptitud_altitudinal"):       _all_phases(_MAIZ_ELEV),
    ("demo_maiz", "aptitud_topografica"):       _all_phases(_MAIZ_PEND),
    ("demo_maiz", "reaccion_suelo_ph"):         _all_phases(_MAIZ_PH),
    ("demo_maiz", "contenido_arcilla"):         _all_phases(_MAIZ_CLAY),
    ("demo_maiz", "contenido_arena"):           _all_phases(_MAIZ_SAND),
    ("demo_maiz", "carbono_organico_suelo"):    _all_phases(_MAIZ_OC),
    ("demo_maiz", "cobertura_actual_auxiliar"): _all_phases(_AUX_NDVI),

    # ── Papa ──────────────────────────────────────────────────────────────────
    ("demo_papa", "aptitud_termica"):           _all_phases(_PAPA_T_MED),
    ("demo_papa", "riesgo_frio"):               _all_phases(_PAPA_T_MIN),
    ("demo_papa", "riesgo_calor"):              _all_phases(_PAPA_T_MAX),
    ("demo_papa", "disponibilidad_hidrica"):    _all_phases(_PAPA_PRECIP),
    ("demo_papa", "deficit_hidrico"):           _all_phases(_PAPA_DEF),
    ("demo_papa", "aptitud_altitudinal"):       _all_phases(_PAPA_ELEV),
    ("demo_papa", "aptitud_topografica"):       _all_phases(_PAPA_PEND),
    ("demo_papa", "reaccion_suelo_ph"):         _all_phases(_PAPA_PH),
    ("demo_papa", "contenido_arcilla"):         _all_phases(_PAPA_CLAY),
    ("demo_papa", "contenido_arena"):           _all_phases(_PAPA_SAND),
    ("demo_papa", "carbono_organico_suelo"):    _all_phases(_PAPA_OC),
    ("demo_papa", "cobertura_actual_auxiliar"): _all_phases(_AUX_NDVI),

    # ── Quinua ────────────────────────────────────────────────────────────────
    ("demo_quinua", "aptitud_termica"):           _all_phases(_QUIN_T_MED),
    ("demo_quinua", "riesgo_frio"):               _all_phases(_QUIN_T_MIN),
    ("demo_quinua", "riesgo_calor"):              _all_phases(_QUIN_T_MAX),
    ("demo_quinua", "disponibilidad_hidrica"):    _all_phases(_QUIN_PRECIP),
    ("demo_quinua", "deficit_hidrico"):           _all_phases(_QUIN_DEF),
    ("demo_quinua", "aptitud_altitudinal"):       _all_phases(_QUIN_ELEV),
    ("demo_quinua", "aptitud_topografica"):       _all_phases(_QUIN_PEND),
    ("demo_quinua", "reaccion_suelo_ph"):         _all_phases(_QUIN_PH),
    ("demo_quinua", "contenido_arcilla"):         _all_phases(_QUIN_CLAY),
    ("demo_quinua", "contenido_arena"):           _all_phases(_QUIN_SAND),
    ("demo_quinua", "carbono_organico_suelo"):    _all_phases(_QUIN_OC),
    ("demo_quinua", "cobertura_actual_auxiliar"): _all_phases(_AUX_NDVI),

    # ── Palta ─────────────────────────────────────────────────────────────────
    ("demo_palta", "aptitud_termica"):           _all_phases(_PALT_T_MED),
    ("demo_palta", "riesgo_frio"):               _all_phases(_PALT_T_MIN),
    ("demo_palta", "riesgo_calor"):              _all_phases(_PALT_T_MAX),
    ("demo_palta", "disponibilidad_hidrica"):    _all_phases(_PALT_PRECIP),
    ("demo_palta", "deficit_hidrico"):           _all_phases(_PALT_DEF),
    ("demo_palta", "aptitud_altitudinal"):       _all_phases(_PALT_ELEV),
    ("demo_palta", "aptitud_topografica"):       _all_phases(_PALT_PEND),
    ("demo_palta", "reaccion_suelo_ph"):         _all_phases(_PALT_PH),
    ("demo_palta", "contenido_arcilla"):         _all_phases(_PALT_CLAY),
    ("demo_palta", "contenido_arena"):           _all_phases(_PALT_SAND),
    ("demo_palta", "carbono_organico_suelo"):    _all_phases(_PALT_OC),
    ("demo_palta", "cobertura_actual_auxiliar"): _all_phases(_AUX_NDVI),

    # ── Arándano ──────────────────────────────────────────────────────────────
    ("demo_arandano", "aptitud_termica"):           _all_phases(_ARAN_T_MED),
    ("demo_arandano", "riesgo_frio"):               _all_phases(_ARAN_T_MIN),
    ("demo_arandano", "riesgo_calor"):              _all_phases(_ARAN_T_MAX),
    ("demo_arandano", "disponibilidad_hidrica"):    _all_phases(_ARAN_PRECIP),
    ("demo_arandano", "deficit_hidrico"):           _all_phases(_ARAN_DEF),
    ("demo_arandano", "aptitud_altitudinal"):       _all_phases(_ARAN_ELEV),
    ("demo_arandano", "aptitud_topografica"):       _all_phases(_ARAN_PEND),
    ("demo_arandano", "reaccion_suelo_ph"):         _all_phases(_ARAN_PH),
    ("demo_arandano", "contenido_arcilla"):         _all_phases(_ARAN_CLAY),
    ("demo_arandano", "contenido_arena"):           _all_phases(_ARAN_SAND),
    ("demo_arandano", "carbono_organico_suelo"):    _all_phases(_ARAN_OC),
    ("demo_arandano", "cobertura_actual_auxiliar"): _all_phases(_AUX_NDVI),
}


# ─── Core functions ───────────────────────────────────────────────────────────


def seed_potential_viability_rulebooks(
    session_factory: Callable,
    cleanup_func: Callable[[Session], None] | None = None,
    repository_factory: Callable[[Session], RulebookRepositoryLike] | None = None,
) -> list[SeededRulebook]:
    """Replace existing demo rulebooks with climate+soil potential-viability versions."""

    session = session_factory()
    try:
        resolved_cleanup = cleanup_func or remove_existing_demo_rulebooks
        resolved_repository_factory = repository_factory or SqlAlchemyRulebookRepository
        resolved_cleanup(session)
        seeded = create_and_publish_potential_viability_rulebooks(resolved_repository_factory(session))
        session.commit()
        return seeded
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_and_publish_potential_viability_rulebooks(
    repository: RulebookRepositoryLike,
) -> list[SeededRulebook]:
    """Create and publish one active climate+soil rulebook per demo crop."""

    service = RulebookCommandService(repository=repository)
    seeded: list[SeededRulebook] = []
    for crop_id, display_name in DEMO_CROPS.items():
        criteria, phases, requirements = build_potential_viability_rulebook_parts(crop_id)
        rulebook = service.create_rulebook(
            crop_id=crop_id,
            criteria=criteria,
            phases=phases,
            phase_requirements=requirements,
        )
        service.publish_rulebook(rulebook.id)
        seeded.append(_summary(rulebook, display_name))
    return seeded


def build_potential_viability_rulebook_parts(
    crop_id: str,
) -> tuple[list[Criterion], list[PhenologicalPhase], list[PhaseRequirement]]:
    """Build climate+soil+structural rulebook graph for one demo crop."""

    if crop_id not in DEMO_CROPS:
        raise ValueError(f"Unknown demo crop: {crop_id!r}")

    criteria = [_build_criterion(crop_id, name) for name in _CRITERIA]
    phases = [
        PhenologicalPhase(
            id=_stable_id(crop_id, "phase", phase_name),
            name=phase_name,
            duration_days=duration_days,
            sequence_order=index,
        )
        for index, (phase_name, duration_days) in enumerate(_PHASES, start=1)
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
    is_auxiliary = criterion_name == "cobertura_actual_auxiliar"
    is_soil = criterion_name in _SOIL_CRITERIA

    if key in _CRITICAL_SPECS:
        policy, penalty_factor = _CRITICAL_SPECS[key]
        is_critical = True
    else:
        policy = None
        penalty_factor = None
        is_critical = False

    if is_auxiliary:
        role_note = (
            "variable auxiliar de contexto superficial (NDVI). "
            "Peso reducido (0.05): no determina viabilidad potencial por si sola. "
            "Amplio trapecio: no colapsa por barbecho ni suelo preparado."
        )
    elif is_soil:
        role_note = (
            f"criterio edafico estatico de aptitud potencial de parcela "
            f"(OpenLandMap ~250m, topsoil_0_30cm_mean). "
            f"Sin politica critica: piso minimo de membresia no critica (0.05) "
            f"previene colapso del WGM."
        )
    elif criterion_name in ("aptitud_altitudinal", "aptitud_topografica"):
        role_note = "criterio estructural estatico de aptitud potencial de parcela."
    else:
        role_note = "criterio climatico de viabilidad potencial de parcela (ERA5-Land / CHIRPS)."

    return Criterion(
        id=_stable_id(crop_id, "criterion", criterion_name),
        name=criterion_name,
        is_critical=is_critical,
        critical_policy=policy,
        penalty_factor=penalty_factor,
        ahp_weight=_AHP_WEIGHTS[criterion_name],
        doc_source=_DOC_SOURCE,
        technical_notes=(
            f"{_VERSION_NOTE}. "
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
    trap = _TRAP[(crop_id, criterion.name)][phase_idx]
    binding = _CRITERION_BINDING[criterion.name]
    return PhaseRequirement(
        id=_stable_id(crop_id, "requirement", criterion.name, phase.name),
        criterion_id=criterion.id,
        phase_id=phase.id,
        membership_fn=MembershipFunction(a=trap[0], b=trap[1], c=trap[2], d=trap[3]),
        phase_weight=_PHASE_WEIGHTS[phase_idx],
        temporal_periods=[
            TemporalPeriod(
                period_key=f"{phase.name}_climate",
                temporal_weight=1.0,
            )
        ],
        extraction_binding=binding,
    )


# ─── Entry point ──────────────────────────────────────────────────────────────


def main() -> None:
    database_url = require_database_url()
    engine = create_engine(database_url, future=True)
    try:
        session_factory = sessionmaker(bind=engine, class_=Session, autoflush=False, expire_on_commit=False)
        seeded = seed_potential_viability_rulebooks(session_factory)
    finally:
        engine.dispose()

    print("Seeded potential-viability rulebooks (clima + suelo + topografia):")
    for item in seeded:
        print(f"  {item.crop_id} ({item.display_name}): {item.status} v{item.version} {item.rulebook_id}")
    print()
    print("AVISO: FIXTURE DIAGNOSTICO DE VIABILIDAD POTENCIAL — no guia oficial")
    print("       Clima (0.48) + Suelo (0.27) + Topografia (0.20) + NDVI aux (0.05) = 1.00")
    print()
    print("       Valores estimados Lima costera (307m, pendiente 1.86°, pH ~7.5):")
    print("         demo_maiz     -> score parcial  (deficit hidrico alto; pH y OC moderados)")
    print("         demo_papa     -> NO_VIABLE      (< 1500m: politica altitudinal)")
    print("         demo_quinua   -> score parcial  (suboptimo en altitud; pH y OC aceptables)")
    print("         demo_palta    -> score parcial  (altitud y deficit; pH suboptimo para palta)")
    print("         demo_arandano -> NO_CONCLUYENTE o bajo  (pH ~7.5 fuera del rango acidofilo)")


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _stable_id(crop_id: str, *parts: str) -> UUID:
    return uuid5(NAMESPACE_URL, ":".join(("via-potential-viability-rulebook", crop_id, *parts)))


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
