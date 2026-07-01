"""Seed production rulebooks for VIA — cultivos reales con umbrales agronómicos documentados.

Usage (PowerShell):
    $env:DATABASE_URL="postgresql+psycopg2://via_user:via_password@localhost:5433/via_test"
    python scripts/seed_prod_rulebooks.py
    python scripts/seed_prod_rulebooks.py --only maiz_amarillo_duro

CROPS:
    maiz_amarillo_duro        Zea mays L.                         <- implementado
    mandarina_murcott         Citrus reticulata 'Murcott'         <- implementado
    maracuya_criolla_amarilla Passiflora edulis f. flavicarpa     <- implementado
    palta_hass                Persea americana 'Hass'             <- pendiente
    uva_de_mesa_sweet_globe   Vitis vinifera 'Sweet Globe'        <- pendiente

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MAIZ AMARILLO DURO — fuentes documentales
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SENASA  Guia BPA Maiz Amarillo Duro (2020)
  MIDAGRI Ficha Tecnica 09 Cultivo MAD (repositorio.midagri.gob.pe)
  SENAMHI Estudio Clima MAD Costa Central (senamhi.gob.pe 2010)
  INIA    Variedades INIA-605, INIA-609, INIA-619

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRITERIOS (13) — Variables GEE extractables
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  aptitud_termica           temperatura_media_c         ERA5-Land   0.13
  riesgo_frio               temperatura_minima_c        ERA5-Land   0.06
  riesgo_calor              temperatura_maxima_c        ERA5-Land   0.08
  disponibilidad_hidrica    precipitacion_acumulada_mm  CHIRPS      0.12
  deficit_hidrico           deficit_hidrico_mm          ERA5 deriv  0.11
  aptitud_altitudinal       elevacion_m                 SRTM        0.12
  aptitud_topografica       pendiente_grados            SRTM        0.06
  reaccion_suelo_ph         ph_suelo                    OLM         0.09
  contenido_arcilla         arcilla_pct                 OLM         0.07
  contenido_arena           arena_pct                   OLM         0.05
  carbono_organico_suelo    carbono_organico_suelo      OLM         0.05
  salinidad_suelo           conductividad_electrica     SoilGrids   0.05
  cobertura_actual_auxiliar ndvi                        Sentinel-2  0.01
  Suma = 1.00  (pesos indicativos maiz_amarillo_duro; varían por cultivo)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FASES maiz_amarillo_duro (7 fases, MIDAGRI/SENAMHI escala VE-R6)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  germinacion_emergencia    15 d  VE        peso=0.08
  desarrollo_vegetativo     45 d  V1-Vn     peso=0.22
  panojamiento              12 d  VT        peso=0.15
  espigamiento_floracion    12 d  R1        peso=0.28  <- fase critica agua/T
  llenado_grano_lechoso     20 d  R3        peso=0.15
  llenado_grano_pastoso     15 d  R4        peso=0.08
  madurez_cosecha           21 d  R6        peso=0.04
  Total: 140 dias (ciclo invierno Lima costa)  Suma pesos = 1.00

POLITICAS CRITICAS:
  maiz_amarillo_duro / aptitud_altitudinal: PENALIZE 0.65
    (fuera de 0-600 msnm para valles costenos; MIDAGRI/SENASA)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MANDARINA MURCOTT — fuentes documentales
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SENASA  Guia BPA Mandarina (2020)
  MIDAGRI / AgroRural  Guia cultivo mandarina (extraccion nutricional 20t)
  Estudio local W. Murcott en Irrigacion Santa Rosa, Sayan, Lima
    (induccion floral, cuajado, plantas 5 anos, patron Citrumelo, riego goteo)

FASES mandarina_murcott (8 fases — frutal perenne, ciclo anual de produccion):
  instalacion_establecimiento     30 d  peso=0.05  (pretemporada/remodelacion)
  brotacion_desarrollo_vegetativo 45 d  peso=0.12
  induccion_floral                30 d  peso=0.20  <- critica: necesita noches frias
  floracion                       25 d  peso=0.22  <- critica: agua y temperatura
  cuajado_fruto                   30 d  peso=0.18  <- critica: estres reduce cuajado
  crecimiento_llenado_fruto       90 d  peso=0.13
  maduracion_cosecha              45 d  peso=0.08
  postcosecha                     20 d  peso=0.02
  Total: 315 dias ciclo productivo  Suma pesos = 1.00

NOVEDAD clave vs maiz: riesgo_frio durante induccion_floral usa trapecio INVERTIDO
  (temperaturas minimas bajas son DESEABLES para la induccion floral en citricos)
  deficit_hidrico durante induccion_floral usa trapecio con optimo en rango medio
  (algo de deficit hidrico favorece la induccion; en floracion/cuajado el deficit es danino)

POLITICA CRITICA:
  mandarina_murcott / aptitud_altitudinal: PENALIZE 0.65
    (>1200 msnm; valles costenos Lima 0-800 msnm, estudio Sayan ~300 msnm)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MARACUYA CRIOLLA AMARILLA — fuentes documentales
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Gerencia Regional Agraria La Libertad — Cultivo de Maracuya (flavicarpa)
  INIA/MIDAGRI — Folleto Cultivo Maracuya 2010

FASES maracuya_criolla_amarilla (10 fases, ciclo productivo ~1 año):
  vivero_propagacion             60 d  peso=0.05
  trasplante_establecimiento     30 d  peso=0.06
  crecimiento_conduccion         60 d  peso=0.10
  formacion_poda                 30 d  peso=0.08
  floracion                      30 d  peso=0.22  <- critica; 24-28°C y noches calidas
  polinizacion_fecundacion       20 d  peso=0.20  <- critica; Xylocopa 7/ha
  crecimiento_fruto              55 d  peso=0.15  <- 50-60 dias post-antesis
  maduracion_cosecha             20 d  peso=0.08
  postcosecha_comercializacion   15 d  peso=0.03
  renovacion_mantenimiento       30 d  peso=0.03
  Total: ~350 dias  Suma pesos = 1.00

NOVEDAD vs maiz/mandarina:
  - temperatura optima estrecha: 24-28°C (mas ajustada que maiz)
  - >28°C restricts flowering and reduces buds (La Libertad source)
  - suelos pesados -> fusariosis: contenido_arcilla PENALIZE 0.70
  - pH 5.5-7.0 EXPLICITO (fuente La Libertad)
  - floracion abre 13-18h; polinizacion por Xylocopa (no abejas); no riego aspersion
  - flavicarpa hasta 1000m (general hasta 1300m) -> altitud PENALIZE 0.65

POLITICAS CRITICAS:
  maracuya_criolla_amarilla / aptitud_altitudinal: PENALIZE 0.65
    (flavicarpa prefiere 0-1000 msnm; tolera hasta 1300 msnm; La Libertad)
  maracuya_criolla_amarilla / contenido_arcilla: PENALIZE 0.70
    (suelos pesados y poco permeables favorecen fusariosis; La Libertad)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PALTA HASS — fuentes documentales
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SENAMHI — Ficha Agroclimática Palto Hass (cdn.www.gob.pe 2021)
  INIA    — Folleto Cultivo de Palto (repositorio.inia.gob.pe)
  MIDAGRI / AgroRural — Manual BPA Palto (repositorio.midagri.gob.pe)

FASES palta_hass (9 fases — frutal perenne, ciclo anual de produccion):
  instalacion_establecimiento     60 d  peso=0.06
  brotacion_foliacion             45 d  peso=0.08
  induccion_floral                30 d  peso=0.17  <- T baja + leve deficit hidrico
  floracion                       25 d  peso=0.24  <- fase mas critica; 20-25°C dia, 10°C noche
  cuajado_fruto                   30 d  peso=0.20  <- solo 0.1% flores -> fruto; sin estres
  crecimiento_desarrollo_fruto    90 d  peso=0.14  <- agua constante; K, Ca por fase
  maduracion_cosecha              45 d  peso=0.06
  postcosecha                     20 d  peso=0.02
  renovacion_mantenimiento        30 d  peso=0.03
  Total: 375 dias ciclo productivo  Suma pesos = 1.00

NOVEDAD vs maiz/mandarina/maracuya:
  - altitud SIN politica critica: SENAMHI reconoce 0-2700 m; para Lima costa es contextual
  - pH con tres rangos conflictivos: SENAMHI 6.5-7.5 / MIDAGRI 6.5-7.0 / INIA 5.5-6.8
    -> union conservadora (5.0, 5.5, 7.5, 8.0); nota documental en technical_notes
  - drenaje CRITICO: asfixia radical -> Phytophthora cinnamomi -> contenido_arcilla PENALIZE
  - induccion_floral: T baja + deficit leve (como mandarina pero mas suave; no inversion total)
  - floracion/cuajado: T optima estrecha 20-25°C (SENAMHI); >35°C daña floracion
  - deficit_hidrico en floracion/cuajado: umbral muy bajo (0-150 mm); estres = caida floral

POLITICA CRITICA:
  palta_hass / contenido_arcilla: PENALIZE 0.65
    (suelos pesados -> mal drenaje -> asfixia radical -> Phytophthora cinnamomi; INIA/MIDAGRI)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
UVA DE MESA SWEET GLOBE — fuentes documentales
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SENAMHI — Ficha Agroclimática Vid (cdn.www.gob.pe 2024)
  MIDAGRI  — Ficha Técnica Requerimientos Agroclimáticos Vid (repositorio.midagri.gob.pe)
  AgroRural/MIDAGRI — Guía Vid (repositorio MIDAGRI)
  UNALM/ALICIA — Manejo Sweet Globe en Pacanga-Chepén, La Libertad (repositorio.lamolina)
  SENASA — Guía BPA Uva
  Bloom Fresh — Sweet Globe / IFG TEN (override varietal, no fuente peruana)

AVISO: la fuente local más específica de Sweet Globe (UNALM) es de Pacanga-Chepén
(La Libertad), no de Lima costa. Los umbrales son válidos para costa norte;
trasladar a costa central requiere ajuste con técnico local.

FASES uva_de_mesa_sweet_globe (13 fases — vid perenne, ciclo anual):
  instalacion_establecimiento     90 d  peso=0.04
  reposo_vegetativo               45 d  peso=0.04  <- T baja DESEADA; dormancia vid
  poda_produccion                 20 d  peso=0.06  <- carga de yemas define produccion
  hinchazon_yemas                 15 d  peso=0.04  <- SENAMHI: 8-12°C inicia brotacion
  brotacion_desarrollo_brotes     30 d  peso=0.09
  aparicion_inflorescencias       20 d  peso=0.07
  floracion                       15 d  peso=0.20  <- CRITICA: 18-24°C; <15.5 o >30 risky
  cuajado_fruto                   20 d  peso=0.16  <- CRITICA; deficit = aborto de bayas
  crecimiento_baya                60 d  peso=0.14  <- calibre 18-24mm Sweet Globe
  maduracion                      30 d  peso=0.10  <- 20°C dia / 15°C noche (SENAMHI Brix)
  cosecha                         15 d  peso=0.03  <- >16°Brix UNALM; 18-20°Brix Bloom
  postcosecha_exportacion         10 d  peso=0.02  <- hasta 90 dias postcosecha (UNALM)
  renovacion_mantenimiento        30 d  peso=0.01
  Total: ~400 dias ciclo  Suma pesos = 1.00

NOVEDADES vs cultivos anteriores:
  - 13 fases: el crop con mas fases del sistema
  - reposo_vegetativo: T baja DESEADA (como mandarina induccion_floral) para dormancia
    aptitud_termica (4,8,16,20) y riesgo_frio (2,4,12,18) usan rango bajo
  - hinchazon_yemas: SENAMHI documenta 8-12°C como umbral de inicio de brotacion
  - floracion: T optima 18-24°C MUY ESTRECHA (SENAMHI); <15.5°C o >30°C reducen floracion
  - pH: SENAMHI 5.5-8.5 (rango mas amplio documentado); se usa casi completo (5.0-8.5)
  - contenido_arena preferencia mayor: "arenoso / franco arenoso" (SENAMHI)
  - deficit_hidrico reposo_vegetativo: leve deficit beneficia dormancia
  - Bloom Fresh como override varietal (calibre, Brix); no prevalece sobre fuentes peruanas

POLITICA CRITICA:
  uva_de_mesa_sweet_globe / contenido_arcilla: PENALIZE 0.65
    (arcilla pesada -> mal drenaje -> enfermedades fungicas; vid muy sensible; SENAMHI/MIDAGRI)
"""

from __future__ import annotations

import argparse
import math
import os
import pathlib
import sys
from collections.abc import Callable
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import bindparam, create_engine, text
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

from seed_demo_rulebooks import RulebookRepositoryLike, SeededRulebook, require_database_url  # noqa: E402


# ─── Cultivos disponibles ─────────────────────────────────────────────────────

PROD_CROPS: dict[str, str] = {
    "maiz_amarillo_duro":        "Maiz Amarillo Duro",
    "mandarina_murcott":         "Mandarina Murcott",
    "maracuya_criolla_amarilla": "Maracuya Criolla Amarilla",
    "palta_hass":                "Palta Hass",
    "uva_de_mesa_sweet_globe":   "Uva de Mesa Sweet Globe",
}


# ─── Criterios ────────────────────────────────────────────────────────────────

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
    "salinidad_suelo",
    "cobertura_actual_auxiliar",
)

_SOIL_CRITERIA = frozenset({
    "reaccion_suelo_ph",
    "contenido_arcilla",
    "contenido_arena",
    "carbono_organico_suelo",
})

_INTERVENTION_CLASS: dict[str, InterventionClass] = {
    "aptitud_termica":           InterventionClass.MITIGABLE,
    "riesgo_frio":               InterventionClass.MITIGABLE,
    "riesgo_calor":              InterventionClass.MITIGABLE,
    "disponibilidad_hidrica":    InterventionClass.CORRECTABLE,
    "deficit_hidrico":           InterventionClass.CORRECTABLE,
    "aptitud_altitudinal":       InterventionClass.STRUCTURAL,
    "aptitud_topografica":       InterventionClass.MITIGABLE,
    "reaccion_suelo_ph":         InterventionClass.CORRECTABLE,
    "contenido_arcilla":         InterventionClass.CORRECTABLE,
    "contenido_arena":           InterventionClass.CORRECTABLE,
    "carbono_organico_suelo":    InterventionClass.CORRECTABLE,
    "salinidad_suelo":           InterventionClass.CORRECTABLE,
    "cobertura_actual_auxiliar": InterventionClass.STRUCTURAL,
}


# ─── Dataset keys ─────────────────────────────────────────────────────────────

_ERA5   = "ECMWF/ERA5_LAND/MONTHLY_AGGR"
_CHIRPS = "UCSB-CHG/CHIRPS/DAILY"
_SRTM   = "USGS/SRTMGL1_003"
_S2     = "COPERNICUS/S2_SR_HARMONIZED"
_OLM_PH   = "OpenLandMap/SOL/SOL_PH-H2O_USDA-4C1A2A_M/v02"
_OLM_CLAY = "OpenLandMap/SOL/SOL_CLAY-WFRACTION_USDA-3A1A1A_M/v02"
_OLM_SAND = "OpenLandMap/SOL/SOL_SAND-WFRACTION_USDA-3A1A1A_M/v02"
_OLM_OC   = "OpenLandMap/SOL/SOL_ORGANIC-CARBON_USDA-6A1C_M/v02"
_ISRIC_ECE = "projects/soilgrids-isric/ece"  # SoilGrids ECe — verificar con gee_smoke_test


# ─── Extraction bindings (idénticos al seed de viabilidad potencial) ──────────

_BINDING_TEMP_MEDIA = ExtractionBinding(
    variable_name="temperatura_media_c", dataset_key=_ERA5,
    band="temperature_2m", unit="celsius",
    temporal_resolution="monthly", scale=11132.0,
    reducer="mean", aggregation_method="mean", fallback_allowed=True,
)
_BINDING_TEMP_MIN = ExtractionBinding(
    variable_name="temperatura_minima_c", dataset_key=_ERA5,
    band="temperature_2m_min", unit="celsius",
    temporal_resolution="monthly", scale=11132.0,
    reducer="mean", aggregation_method="mean", fallback_allowed=True,
)
_BINDING_TEMP_MAX = ExtractionBinding(
    variable_name="temperatura_maxima_c", dataset_key=_ERA5,
    band="temperature_2m_max", unit="celsius",
    temporal_resolution="monthly", scale=11132.0,
    reducer="mean", aggregation_method="mean", fallback_allowed=True,
)
_BINDING_PRECIP = ExtractionBinding(
    variable_name="precipitacion_acumulada_mm", dataset_key=_CHIRPS,
    band="precipitation", unit="mm",
    temporal_resolution="daily", scale=5566.0,
    reducer="mean", aggregation_method="sum", fallback_allowed=True,
)
_BINDING_DEFICIT = ExtractionBinding(
    variable_name="deficit_hidrico_mm", dataset_key=_ERA5,
    band="deficit_hidrico_mm", unit="mm",
    temporal_resolution="derived", scale=11132.0,
    reducer="mean", aggregation_method="sum", fallback_allowed=True,
)
_BINDING_ELEVACION = ExtractionBinding(
    variable_name="elevacion_m", dataset_key=_SRTM,
    band="elevation", unit="m",
    temporal_resolution="static", scale=30.0,
    reducer="mean", aggregation_method="mean", fallback_allowed=True,
)
_BINDING_PENDIENTE = ExtractionBinding(
    variable_name="pendiente_grados", dataset_key=_SRTM,
    band="slope", unit="degrees",
    temporal_resolution="static", scale=30.0,
    reducer="mean", aggregation_method="mean", fallback_allowed=True,
)
_BINDING_PH = ExtractionBinding(
    variable_name="ph_suelo", dataset_key=_OLM_PH,
    band="topsoil_0_30cm_mean", unit="pH",
    temporal_resolution="static", scale=250.0,
    reducer="mean", aggregation_method="mean", fallback_allowed=True,
)
_BINDING_CLAY = ExtractionBinding(
    variable_name="arcilla_pct", dataset_key=_OLM_CLAY,
    band="topsoil_0_30cm_mean", unit="%",
    temporal_resolution="static", scale=250.0,
    reducer="mean", aggregation_method="mean", fallback_allowed=True,
)
_BINDING_SAND = ExtractionBinding(
    variable_name="arena_pct", dataset_key=_OLM_SAND,
    band="topsoil_0_30cm_mean", unit="%",
    temporal_resolution="static", scale=250.0,
    reducer="mean", aggregation_method="mean", fallback_allowed=True,
)
_BINDING_OC = ExtractionBinding(
    variable_name="carbono_organico_suelo", dataset_key=_OLM_OC,
    band="topsoil_0_30cm_mean", unit="g/kg",
    temporal_resolution="static", scale=250.0,
    reducer="mean", aggregation_method="mean", fallback_allowed=True,
)
_BINDING_CE = ExtractionBinding(
    variable_name="conductividad_electrica_ds_m", dataset_key=_ISRIC_ECE,
    band="ece_0-5cm_mean", unit="dS/m",
    temporal_resolution="static", scale=250.0,
    reducer="mean", aggregation_method="mean", fallback_allowed=True,
)
_BINDING_NDVI = ExtractionBinding(
    variable_name="ndvi", dataset_key=_S2,
    band="ndvi", unit="index",
    temporal_resolution="monthly", scale=10.0,
    reducer="mean", aggregation_method="mean", fallback_allowed=True,
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
    "salinidad_suelo":           _BINDING_CE,
    "cobertura_actual_auxiliar": _BINDING_NDVI,
}


# ─── Helper ───────────────────────────────────────────────────────────────────

def _deg(pct: float) -> float:
    """Convert slope percentage to degrees."""
    return round(math.atan(pct / 100.0) * (180.0 / math.pi), 2)


def _same(trap: tuple[float, float, float, float], n: int) -> tuple:
    """Repeat the same trapezoid for n phases."""
    return (trap,) * n


# ─── ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#     MAIZ AMARILLO DURO — Zea mays L. — valles costenos Peru (0-600 msnm)
# ─── ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_MAD_DOC_SOURCE = (
    "SENASA Guia BPA Maiz Amarillo Duro (2020); "
    "MIDAGRI Ficha Tecnica 09 Cultivo MAD (repositorio.midagri.gob.pe); "
    "SENAMHI Estudio Clima MAD Costa Central (senamhi.gob.pe/load/file/01401SENA-10.pdf); "
    "INIA variedades INIA-605/609/619. "
    "Umbrales derivados de documentacion oficial peruana; no son guia agronomica validada completa."
)

# 7 fases fenologicas: (nombre, duracion_dias)
_MAD_PHASES: tuple[tuple[str, int], ...] = (
    ("germinacion_emergencia",   15),   # VE
    ("desarrollo_vegetativo",    45),   # V1-Vn
    ("panojamiento",             12),   # VT
    ("espigamiento_floracion",   12),   # R1  <- critica agua y temperatura
    ("llenado_grano_lechoso",    20),   # R3
    ("llenado_grano_pastoso",    15),   # R4
    ("madurez_cosecha",          21),   # R6
)

# Pesos por fase (deben sumar 1.0); floración = peso mayor
# Fuente: literatura agronómica sobre etapas críticas del maíz
_MAD_PHASE_WEIGHTS: tuple[float, ...] = (
    0.08,  # germinacion_emergencia
    0.22,  # desarrollo_vegetativo
    0.15,  # panojamiento
    0.28,  # espigamiento_floracion  <- fase mas critica hídrica y termica
    0.15,  # llenado_grano_lechoso
    0.08,  # llenado_grano_pastoso
    0.04,  # madurez_cosecha
)

# Pesos AHP por criterio (deben sumar 1.0)
_MAD_AHP_WEIGHTS: dict[str, float] = {
    "aptitud_termica":           0.13,  # 24-30°C optimo; critico por fase
    "riesgo_frio":               0.06,  # min 18°C floración (SENASA)
    "riesgo_calor":              0.08,  # >30°C afecta raices y polen (SENASA)
    "disponibilidad_hidrica":    0.12,  # Lima irrigada; a=0 no penaliza secano
    "deficit_hidrico":           0.10,  # deficit tipico Lima; compensado por riego
    "aptitud_altitudinal":       0.12,  # 0-600 msnm valles costenos (MIDAGRI)
    "aptitud_topografica":       0.06,  # mecanizacion e irrigacion
    "reaccion_suelo_ph":         0.09,  # conflicto: SENASA 5.5-6.0 / MIDAGRI 6.1-7.8
    "contenido_arcilla":         0.07,  # franco, franco arcilloso (SENASA/MIDAGRI)
    "contenido_arena":           0.05,  # franco arcillo arenoso tolerable
    "carbono_organico_suelo":    0.05,  # "alto contenido MO" (MIDAGRI >4%)
    "salinidad_suelo":           0.05,  # FAO Paper 29: umbral ECe 1.7 dS/m; costa irrigada
    "cobertura_actual_auxiliar": 0.02,  # auxiliar NDVI; no determina viabilidad
}

# Politica critica: altitud fuera de 0-600m aplica penalizacion
_MAD_CRITICAL_SPECS: dict[str, tuple[CriticalPolicy, float | None]] = {
    "aptitud_altitudinal": (CriticalPolicy.PENALIZE, 0.65),
}

# ─── Trapecios por criterio ───────────────────────────────────────────────────
# Orden de fases: [germinacion, desarrollo, panojamiento, floracion, lechoso, pastoso, cosecha]
# Temperaturas en °C. Fuente base: SENASA BPA 2020, SENAMHI 2010.

# aptitud_termica (temperatura_media_c)
# germinacion: suelo 10°C en aumento (SENASA); proxy aire ~ 16°C
# desarrollo: optimo 24-30°C (SENASA); tolera hasta 36°C con irrigacion
# panojamiento: similar a desarrollo; inicio sensibilidad termica
# floracion: 18-28°C optimo; "al menos 18°C" (SENASA); >30°C afecta sincronizacion
# lechoso: 18-28°C; maiz en llenado tolera algo mas de calor
# pastoso: 16-28°C; demanda hidrica decrece
# cosecha: amplio; planta en secado, menos sensible
_MAD_T_MED: tuple = (
    (10, 16, 28, 34),  # germinacion_emergencia
    (14, 20, 30, 36),  # desarrollo_vegetativo
    (16, 22, 30, 36),  # panojamiento
    (14, 18, 28, 34),  # espigamiento_floracion  <- estrecho; 18°C minimo
    (12, 18, 28, 34),  # llenado_grano_lechoso
    (10, 16, 28, 34),  # llenado_grano_pastoso
    ( 8, 14, 30, 36),  # madurez_cosecha
)

# riesgo_frio (temperatura_minima_c)
# floracion: "al menos 18°C para favorecer floración" (SENASA) -> b=16, c=22
_MAD_T_MIN: tuple = (
    ( 6, 10, 18, 24),  # germinacion_emergencia
    ( 8, 12, 20, 26),  # desarrollo_vegetativo
    (10, 14, 22, 26),  # panojamiento
    (12, 16, 22, 26),  # espigamiento_floracion  <- 18°C minimo real
    (10, 14, 20, 26),  # llenado_grano_lechoso
    ( 8, 12, 18, 24),  # llenado_grano_pastoso
    ( 6, 10, 18, 24),  # madurez_cosecha
)

# riesgo_calor (temperatura_maxima_c)
# floracion: "temperaturas muy elevadas afectan emision de polen y pistilos" (SENASA)
# desarrollo: ">30°C afecta raices y absorcion de agua" (SENASA)
_MAD_T_MAX: tuple = (
    (16, 24, 30, 36),  # germinacion_emergencia
    (18, 24, 32, 38),  # desarrollo_vegetativo   <- >30°C afecta raices
    (20, 26, 32, 38),  # panojamiento
    (16, 22, 28, 34),  # espigamiento_floracion   <- estrecho; pollen sensible
    (18, 24, 32, 38),  # llenado_grano_lechoso
    (16, 22, 32, 38),  # llenado_grano_pastoso
    (14, 20, 34, 40),  # madurez_cosecha          <- mas tolerante al calor al secar
)

# disponibilidad_hidrica (precipitacion_acumulada_mm mensual)
# Lima costera: ~15mm/año natural. Cultivo irrigado. a=b=0 para no penalizar
# zonas irrigadas. VIA no modela riego directo; la brecha hidrica es para recomendaciones.
_MAD_PRECIP = _same((0, 0, 600, 1400), len(_MAD_PHASES))

# deficit_hidrico (deficit_hidrico_mm mensual)
# Lima: deficit natural ~1185mm/año pero compensado con riego.
# No excluir Lima por deficit alto; el riego lo gestiona el agricultor.
_MAD_DEFICIT = _same((0, 0, 600, 1400), len(_MAD_PHASES))

# aptitud_altitudinal (elevacion_m)
# Valles costenos: 0-600 msnm (MIDAGRI); optimo amplio 0-600m; declive 600-900m
# Politica critica PENALIZE 0.65 si membresía=0 (>900m)
_MAD_ELEV = _same((0, 0, 600, 900), len(_MAD_PHASES))

# aptitud_topografica (pendiente_grados)
# Maiz mecanizable: <8% pendiente optima; 8-20% marginal (mecanizacion dificil)
_MAD_PEND = _same((0.0, 0.0, _deg(8), _deg(20)), len(_MAD_PHASES))

# reaccion_suelo_ph (ph real post-conversion OLM raw*0.1)
# Conflicto documental: SENASA 5.5-6.0 / MIDAGRI 6.1-7.8
# Trapecio union conservador: (4.5, 5.5, 7.2, 8.0)
# Nota: no se consolida en un unico rango para no inventar conciliacion no documentada
_MAD_PH = _same((4.5, 5.5, 7.2, 8.0), len(_MAD_PHASES))

# contenido_arcilla (arcilla_pct real post-conversion OLM raw*0.1)
# Texturas validas: franco (~15-25%), franco arcilloso (~25-40%), franco arcillo arenoso
_MAD_CLAY = _same((5, 15, 40, 60), len(_MAD_PHASES))

# contenido_arena (arena_pct real post-conversion OLM raw*0.1)
# Franco: 35-65% arena; franco arcillo arenoso: hasta 70%
_MAD_SAND = _same((15, 35, 65, 80), len(_MAD_PHASES))

# carbono_organico_suelo (g/kg real post-conversion OLM raw*0.2)
# "Alto contenido de materia organica" (SENASA/MIDAGRI >4% MO = ~23 g/kg OC)
# Lima costera tipicamente ~3-5 g/kg OC; ese rango estara en zona baja del trapecio
_MAD_OC = _same((2, 10, 40, 70), len(_MAD_PHASES))

# salinidad_suelo (conductividad_electrica ECe dS/m — SoilGrids ISRIC)
# Maiz: sensitivo a sal; FAO Paper 29: umbral ECe=1.7 dS/m, rendimiento cae ~12%/dS/m extra
# Valles costeros Lima pueden tener ligera salinidad (<2 dS/m en suelos irrigados)
_MAD_CE = _same((0.0, 0.0, 1.7, 4.0), len(_MAD_PHASES))

# cobertura_actual_auxiliar (ndvi Sentinel-2)
# Auxiliar de contexto; amplio trapecio para no colapsar por barbecho o suelo preparado
_MAD_NDVI = _same((-0.10, 0.05, 0.90, 1.00), len(_MAD_PHASES))


# ─── ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#     MANDARINA MURCOTT — Citrus reticulata 'Murcott' — valles costenos Lima
# ─── ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_MCT_DOC_SOURCE = (
    "SENASA Guia BPA Mandarina (2020); "
    "MIDAGRI/AgroRural Guia cultivo mandarina (extraccion nutricional 20t); "
    "Estudio local W. Murcott en Irrigacion Santa Rosa, Sayan, Lima "
    "(induccion floral, cuajado, plantas 5 anos, patron Citrumelo, riego goteo). "
    "Umbrales derivados de documentacion oficial peruana y ensayo local; "
    "no son guia agronomica completa ni validada."
)

# 8 fases fenologicas del ciclo productivo anual: (nombre, duracion_dias)
_MCT_PHASES: tuple[tuple[str, int], ...] = (
    ("instalacion_establecimiento",     30),   # pretemporada / ajuste predial
    ("brotacion_desarrollo_vegetativo", 45),   # brotacion activa
    ("induccion_floral",                30),   # CRITICA: noches frias o estres hidrico
    ("floracion",                       25),   # CRITICA: agua continua, sin estres
    ("cuajado_fruto",                   30),   # CRITICA: no estres hidrico
    ("crecimiento_llenado_fruto",       90),   # demanda hidrica alta
    ("maduracion_cosecha",              45),   # calidad Brix/acidez
    ("postcosecha",                     20),   # manejo poscosecha
)

# Pesos por fase: induccion + floracion + cuajado concentran el 60% del peso
_MCT_PHASE_WEIGHTS: tuple[float, ...] = (
    0.05,  # instalacion_establecimiento
    0.12,  # brotacion_desarrollo_vegetativo
    0.20,  # induccion_floral            <- necesita frio nocturno
    0.22,  # floracion                   <- mas critica del ciclo
    0.18,  # cuajado_fruto
    0.13,  # crecimiento_llenado_fruto
    0.08,  # maduracion_cosecha
    0.02,  # postcosecha
)

# Pesos AHP por criterio
_MCT_AHP_WEIGHTS: dict[str, float] = {
    "aptitud_termica":           0.12,  # 25-30°C optimo general (SENASA)
    "riesgo_frio":               0.10,  # CLAVE: noches frias inducen floracion
    "riesgo_calor":              0.08,  # >35°C danino; otoño calido reduce induccion
    "disponibilidad_hidrica":    0.11,  # frutal perenne; irrigado; agua constante
    "deficit_hidrico":           0.09,  # complejo: bueno en induccion, malo en floracion
    "aptitud_altitudinal":       0.10,  # valles costenos 0-800 msnm (Sayan ~300m)
    "aptitud_topografica":       0.08,  # drenaje importante; barreras de viento
    "reaccion_suelo_ph":         0.07,  # rango sin fuente explícita; moderado
    "contenido_arcilla":         0.07,  # suelo suelto (SENASA); no exceso arcilla
    "contenido_arena":           0.06,  # drenaje; franco a franco arenoso
    "carbono_organico_suelo":    0.05,  # materia organica para perenne
    "salinidad_suelo":           0.05,  # FAO Paper 29: citricos muy sensibles ECe <1.7 dS/m
    "cobertura_actual_auxiliar": 0.02,  # auxiliar NDVI
}

_MCT_CRITICAL_SPECS: dict[str, tuple[CriticalPolicy, float | None]] = {
    "aptitud_altitudinal": (CriticalPolicy.PENALIZE, 0.65),
}

# ─── Trapecios mandarina_murcott — 8 fases ────────────────────────────────────
# Orden fases: [instalacion, brotacion, induccion, floracion, cuajado, crecimiento, maduracion, postcosecha]

# aptitud_termica (temperatura_media_c °C)
# induccion: COOLER range — induccion requiere temperaturas mas bajas (SENASA/Sayan)
# floracion y cuajado: moderado-calido para fructificacion
# crecimiento_llenado: optimo 22-30°C para desarrollo de fruto
_MCT_T_MED: tuple = (
    (12, 18, 30, 36),  # instalacion_establecimiento    — amplio
    (16, 20, 30, 34),  # brotacion_desarrollo_vegetativo — activo; calido
    (10, 14, 22, 26),  # induccion_floral               — ESTRECHO/BAJO; frio favorece
    (14, 18, 28, 32),  # floracion                      — moderado
    (16, 20, 28, 32),  # cuajado_fruto                  — calido moderado
    (18, 22, 30, 34),  # crecimiento_llenado_fruto      — calido para desarrollo
    (16, 20, 28, 32),  # maduracion_cosecha             — moderado para calidad
    ( 8, 14, 30, 36),  # postcosecha                    — amplio; campo ya cosechado
)

# riesgo_frio (temperatura_minima_c °C)
# NOVEDAD: induccion_floral usa rango BAJO porque noches frias son DESEABLES
# (4-15°C nocturno = optimo para induccion floral en citricos; Sayan/SENASA)
# En otras fases: trapecio standard — proteger de heladas, no demasiado frio
_MCT_T_MIN: tuple = (
    ( 8, 12, 20, 26),  # instalacion_establecimiento
    (10, 14, 20, 26),  # brotacion_desarrollo_vegetativo
    ( 4,  8, 15, 22),  # induccion_floral  <- INVERTIDO: 8-15°C nocturno = OPTIMO
    (10, 14, 20, 26),  # floracion          — proteger de frio durante floracion
    (10, 14, 20, 26),  # cuajado_fruto
    (10, 14, 20, 26),  # crecimiento_llenado_fruto
    ( 8, 12, 20, 26),  # maduracion_cosecha
    ( 2,  6, 20, 26),  # postcosecha        — amplio
)

# riesgo_calor (temperatura_maxima_c °C)
# induccion: ESTRECHO — otoño/invierno calido impide induccion (Sayan)
# general: 32-38°C limite; cítricos toleran algo de calor
_MCT_T_MAX: tuple = (
    (20, 26, 32, 38),  # instalacion_establecimiento
    (22, 28, 34, 40),  # brotacion_desarrollo_vegetativo
    (18, 24, 28, 34),  # induccion_floral  <- ESTRECHO; calor impide induccion
    (20, 26, 32, 38),  # floracion
    (20, 26, 32, 38),  # cuajado_fruto
    (22, 28, 34, 40),  # crecimiento_llenado_fruto
    (20, 26, 32, 38),  # maduracion_cosecha
    (18, 24, 34, 40),  # postcosecha
)

# disponibilidad_hidrica (precipitacion_acumulada_mm mensual)
# Frutal perenne irrigado; a=b=0 no penaliza Lima costera
_MCT_PRECIP = _same((0, 0, 800, 1600), len(_MCT_PHASES))

# deficit_hidrico (deficit_hidrico_mm mensual)
# FASE ESPECIAL — induccion_floral: un deficit MODERADO es DESEABLE (Sayan: 17 dias estres)
# floracion/cuajado: deficit = danino -> trapecio estrecho con optimo en 0
# otras fases: moderado
_MCT_DEFICIT: tuple = (
    (  0,   0, 400, 1000),  # instalacion_establecimiento
    (  0,   0, 300,  800),  # brotacion_desarrollo_vegetativo
    ( 50, 100, 400,  700),  # induccion_floral  <- OPTIMO con deficit moderado
    (  0,   0, 200,  600),  # floracion          <- minimo deficit; irrigar fuerte
    (  0,   0, 200,  600),  # cuajado_fruto      <- igual; critico para cuajado
    (  0,   0, 300,  700),  # crecimiento_llenado_fruto
    (  0,   0, 400,  900),  # maduracion_cosecha
    (  0,   0, 600, 1400),  # postcosecha        — amplio
)

# aptitud_altitudinal (elevacion_m)
# Mandarina costera Lima: 0-800 msnm (Sayan ~300m); tolera hasta 1200m
_MCT_ELEV = _same((0, 0, 800, 1200), len(_MCT_PHASES))

# aptitud_topografica (pendiente_grados)
# Citricos toleran pendiente; drenaje importante; barreras de viento en zona alta
_MCT_PEND = _same((0.0, 0.0, _deg(10), _deg(25)), len(_MCT_PHASES))

# reaccion_suelo_ph
# SENASA no da rango pH explicito; literatura cítricos: pH 5.5-7.5
# Trapecio conservador mas amplio para reflejar incertidumbre documental
_MCT_PH = _same((5.0, 5.5, 7.0, 8.0), len(_MCT_PHASES))

# contenido_arcilla — suelo suelto (SENASA); no arcilloso pesado
_MCT_CLAY = _same((5, 10, 35, 55), len(_MCT_PHASES))

# contenido_arena — franco, buen drenaje; algo de arena es positivo
_MCT_SAND = _same((15, 25, 65, 80), len(_MCT_PHASES))

# carbono_organico_suelo — frutal perenne requiere buen sustrato organico
_MCT_OC = _same((2, 8, 40, 70), len(_MCT_PHASES))

# salinidad_suelo (ECe dS/m — SoilGrids ISRIC)
# Citricos: muy sensibles a sal; FAO Paper 29: umbral ECe=1.7 dS/m, ~16%/dS/m extra
# Mandarina mas sensible que naranja; suelos costeros irrigados con riesgo sodico
_MCT_CE = _same((0.0, 0.0, 1.7, 3.5), len(_MCT_PHASES))

# cobertura_actual_auxiliar (ndvi)
_MCT_NDVI = _same((-0.10, 0.05, 0.90, 1.00), len(_MCT_PHASES))


# ─── ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#     MARACUYA CRIOLLA AMARILLA — Passiflora edulis f. flavicarpa — 0-1000 msnm
# ─── ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_MRC_DOC_SOURCE = (
    "Gerencia Regional Agraria La Libertad — Cultivo de Maracuya (Passiflora edulis f. flavicarpa); "
    "INIA/MIDAGRI Folleto Cultivo Maracuya 2010. "
    "Umbrales derivados de documentacion oficial peruana; no son guia agronomica completa ni validada."
)

# 10 fases fenologicas: (nombre, duracion_dias)
_MRC_PHASES: tuple[tuple[str, int], ...] = (
    ("vivero_propagacion",           60),   # semilla o esquejes en vivero
    ("trasplante_establecimiento",   30),   # instalacion en campo definitivo
    ("crecimiento_conduccion",       60),   # brotacion y guiado en espaldera
    ("formacion_poda",               30),   # poda de formacion inicial
    ("floracion",                    30),   # CRITICA: 24-28°C; flores 13-18h
    ("polinizacion_fecundacion",     20),   # CRITICA: Xylocopa; no riego aspersion
    ("crecimiento_fruto",            55),   # 50-60 dias post-antesis (La Libertad)
    ("maduracion_cosecha",           20),   # 130g, 36% jugo, 13-18°Brix
    ("postcosecha_comercializacion", 15),   # manejo y comercializacion
    ("renovacion_mantenimiento",     30),   # poda de renovacion y mantenimiento
)

# Pesos por fase: floracion + polinizacion concentran 42% del peso
_MRC_PHASE_WEIGHTS: tuple[float, ...] = (
    0.05,  # vivero_propagacion
    0.06,  # trasplante_establecimiento
    0.10,  # crecimiento_conduccion
    0.08,  # formacion_poda
    0.22,  # floracion                   <- mas critica: T 24-28°C + polinizadores
    0.20,  # polinizacion_fecundacion    <- critica: Xylocopa; sin riego aspersion
    0.15,  # crecimiento_fruto
    0.08,  # maduracion_cosecha
    0.03,  # postcosecha_comercializacion
    0.03,  # renovacion_mantenimiento
)

# Pesos AHP por criterio
_MRC_AHP_WEIGHTS: dict[str, float] = {
    "aptitud_termica":           0.13,  # 24-28°C critico; mas estrecho que maiz/mandarina
    "riesgo_frio":               0.07,  # T min bajas reducen fructificacion
    "riesgo_calor":              0.09,  # >28°C restringe flores y reduce botones (La Libertad)
    "disponibilidad_hidrica":    0.10,  # "suministro frecuente" pero sin encharcamiento
    "deficit_hidrico":           0.09,  # estres en floracion/fecundacion reduce cuajado
    "aptitud_altitudinal":       0.10,  # flavicarpa 0-1000 msnm; tolera hasta 1300m
    "aptitud_topografica":       0.08,  # drenaje CRITICO; suelo pesado -> fusariosis
    "reaccion_suelo_ph":         0.09,  # EXPLICITO: 5.5-7.0 (Gerencia La Libertad)
    "contenido_arcilla":         0.09,  # suelos pesados -> fusariosis (La Libertad)
    "contenido_arena":           0.06,  # franco arenoso; buen drenaje
    "carbono_organico_suelo":    0.03,  # "suelos fertiles" sin rango especifico
    "salinidad_suelo":           0.05,  # FAO Paper 29: umbral ECe ~1.5 dS/m; moderadamente sensible
    "cobertura_actual_auxiliar": 0.02,  # auxiliar NDVI
}

# Politicas criticas: altitud (flavicarpa) + arcilla (fusariosis)
_MRC_CRITICAL_SPECS: dict[str, tuple[CriticalPolicy, float | None]] = {
    "aptitud_altitudinal": (CriticalPolicy.PENALIZE, 0.65),
    "contenido_arcilla":   (CriticalPolicy.PENALIZE, 0.70),
}

# ─── Trapecios maracuya_criolla_amarilla — 10 fases ──────────────────────────
# Orden fases: [vivero, trasplante, conduccion, formacion, floracion, polinizacion,
#               crecimiento, maduracion, postcosecha, renovacion]

# aptitud_termica (temperatura_media_c °C)
# Optimo 24-28°C (La Libertad); floracion/polinizacion con rango estrecho
# Otras fases: algo mas amplio pero centrado en 22-28°C
_MRC_T_MED: tuple = (
    (16, 20, 30, 36),  # vivero_propagacion           — amplio; vivero flexible
    (18, 22, 30, 34),  # trasplante_establecimiento
    (18, 22, 30, 34),  # crecimiento_conduccion
    (18, 22, 30, 34),  # formacion_poda
    (18, 22, 26, 30),  # floracion                    <- ESTRECHO; 24-28°C critico
    (18, 22, 26, 30),  # polinizacion_fecundacion     <- igual; T clave Xylocopa
    (18, 22, 30, 34),  # crecimiento_fruto
    (16, 20, 30, 34),  # maduracion_cosecha
    ( 8, 14, 30, 36),  # postcosecha_comercializacion — amplio
    (14, 18, 30, 36),  # renovacion_mantenimiento
)

# riesgo_frio (temperatura_minima_c °C)
# "T bajas de invierno reducen numero de frutos" (La Libertad)
# floracion/polinizacion: noches calidas necesarias para actividad de Xylocopa
_MRC_T_MIN: tuple = (
    (10, 14, 22, 26),  # vivero_propagacion
    (12, 16, 22, 26),  # trasplante_establecimiento
    (12, 16, 22, 26),  # crecimiento_conduccion
    (12, 16, 22, 26),  # formacion_poda
    (14, 18, 22, 26),  # floracion                    <- noches calidas; Xylocopa activo
    (14, 18, 22, 26),  # polinizacion_fecundacion     <- igual
    (12, 16, 22, 26),  # crecimiento_fruto
    (10, 14, 20, 26),  # maduracion_cosecha
    ( 6, 10, 20, 26),  # postcosecha_comercializacion — amplio
    (10, 14, 20, 26),  # renovacion_mantenimiento
)

# riesgo_calor (temperatura_maxima_c °C)
# "temperaturas superiores restringen flores y reducen botones" (La Libertad)
# floracion/polinizacion: estrecho; >28°C compromete cuajado y actividad de Xylocopa
_MRC_T_MAX: tuple = (
    (24, 28, 34, 38),  # vivero_propagacion
    (22, 26, 34, 38),  # trasplante_establecimiento
    (22, 26, 34, 38),  # crecimiento_conduccion
    (22, 26, 34, 38),  # formacion_poda
    (20, 24, 28, 32),  # floracion                    <- ESTRECHO; >28°C restringe flores
    (20, 24, 28, 32),  # polinizacion_fecundacion     <- igual; calor excesivo mata Xylocopa
    (22, 26, 32, 36),  # crecimiento_fruto
    (20, 24, 32, 36),  # maduracion_cosecha
    (18, 22, 34, 40),  # postcosecha_comercializacion — amplio
    (20, 24, 34, 38),  # renovacion_mantenimiento
)

# disponibilidad_hidrica (precipitacion_acumulada_mm mensual)
# "suministro frecuente pero evitar encharcamiento"; cultivo irrigado
_MRC_PRECIP = _same((0, 0, 600, 1400), len(_MRC_PHASES))

# deficit_hidrico (deficit_hidrico_mm mensual)
# estres hidrico durante floracion/polinizacion -> aborto de flores y frutos
# Maracuya NO necesita estres para induccion (a diferencia de mandarina)
_MRC_DEFICIT: tuple = (
    (  0,   0, 400, 1000),  # vivero_propagacion
    (  0,   0, 300,  800),  # trasplante_establecimiento
    (  0,   0, 400, 1000),  # crecimiento_conduccion
    (  0,   0, 400, 1000),  # formacion_poda
    (  0,   0, 200,  600),  # floracion                <- CRITICO; estres = aborto floral
    (  0,   0, 200,  600),  # polinizacion_fecundacion <- igual; agua critica post-antesis
    (  0,   0, 300,  700),  # crecimiento_fruto        <- agua para llenado
    (  0,   0, 400,  900),  # maduracion_cosecha
    (  0,   0, 600, 1400),  # postcosecha_comercializacion — amplio
    (  0,   0, 400, 1000),  # renovacion_mantenimiento
)

# aptitud_altitudinal (elevacion_m)
# flavicarpa: 0-1000 msnm optimo (La Libertad); tolera hasta 1300m
# PENALIZE 0.65 aplicado cuando membresia=0 (>1300m)
_MRC_ELEV = _same((0, 0, 1000, 1300), len(_MRC_PHASES))

# aptitud_topografica (pendiente_grados)
# Drenaje CRITICO: suelos pesados con mal drenaje -> fusariosis y pudricion radical
# Ligera pendiente favorable; >25% dificultad de labores
_MRC_PEND = _same((0.0, 0.0, _deg(12), _deg(25)), len(_MRC_PHASES))

# reaccion_suelo_ph
# EXPLICITO: pH 5.5-7.0 (Gerencia Regional La Libertad)
# Trapecio mas ajustado que maiz/mandarina por tener fuente especifica
_MRC_PH = _same((4.5, 5.5, 7.0, 7.8), len(_MRC_PHASES))

# contenido_arcilla (arcilla_pct)
# "suelos pesados y poco permeables favorecen fusariosis y pudricion radical" (La Libertad)
# Franco arenoso preferido (5-20% arcilla); PENALIZE 0.70 si membresia=0 (>45%)
_MRC_CLAY = _same((5, 8, 25, 45), len(_MRC_PHASES))

# contenido_arena (arena_pct)
# Franco arenoso = 60-70% arena; buen drenaje previene fusariosis
_MRC_SAND = _same((25, 40, 75, 85), len(_MRC_PHASES))

# carbono_organico_suelo (g/kg)
# "suelos fertiles" sin rango especifico documentado; moderado
_MRC_OC = _same((2, 6, 35, 65), len(_MRC_PHASES))

# salinidad_suelo (ECe dS/m — SoilGrids ISRIC)
# Maracuya: moderadamente sensible; FAO Paper 29: umbral ECe ~1.5 dS/m
# Prefiere suelos con buena lixiviacion; salinidad alta agrava fusariosis
_MRC_CE = _same((0.0, 0.0, 1.5, 3.5), len(_MRC_PHASES))

# cobertura_actual_auxiliar (ndvi)
_MRC_NDVI = _same((-0.10, 0.05, 0.90, 1.00), len(_MRC_PHASES))


# ─── ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#     PALTA HASS — Persea americana Mill. var. Hass — 0-2700 msnm (SENAMHI)
# ─── ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_PHH_DOC_SOURCE = (
    "SENAMHI Ficha Agroclimática Palto Hass (cdn.www.gob.pe 2021); "
    "INIA Folleto Cultivo de Palto (repositorio.inia.gob.pe); "
    "MIDAGRI/AgroRural Manual BPA Palto (repositorio.midagri.gob.pe). "
    "pH con tres rangos conflictivos: SENAMHI 6.5-7.5 / MIDAGRI 6.5-7.0 / INIA 5.5-6.8; "
    "trapecio usa union conservadora (5.0-7.5). "
    "Altitud sin politica critica: SENAMHI reconoce aptitud 0-2700 msnm; "
    "para costa Lima se trata como criterio contextual, no de descarte. "
    "Umbrales derivados de documentacion oficial peruana; no son guia agronomica completa."
)

# 9 fases fenologicas del ciclo productivo anual: (nombre, duracion_dias)
_PHH_PHASES: tuple[tuple[str, int], ...] = (
    ("instalacion_establecimiento",   60),   # planton, patron, injerto, suelo, riego inicial
    ("brotacion_foliacion",           45),   # emision hojas nuevas; vigor; plagas en brotes
    ("induccion_floral",              30),   # CRITICA: T baja + leve deficit activan induccion
    ("floracion",                     25),   # CRITICA: 20-25°C dia, 10°C noche (SENAMHI); viento
    ("cuajado_fruto",                 30),   # CRITICA: solo 0.1% flores -> fruto; sin estres
    ("crecimiento_desarrollo_fruto",  90),   # agua constante; K, Ca por fase; 200-300g fruto
    ("maduracion_cosecha",            45),   # pedunculo palido; materia seca/aceite 18-22%
    ("postcosecha",                   20),   # cadena frio; seleccion; trazabilidad
    ("renovacion_mantenimiento",      30),   # poda formacion/mantenimiento; sanidad ramas
)

# Pesos por fase: floracion + cuajado + induccion concentran 61% del peso
_PHH_PHASE_WEIGHTS: tuple[float, ...] = (
    0.06,  # instalacion_establecimiento
    0.08,  # brotacion_foliacion
    0.17,  # induccion_floral           <- T baja + deficit leve; precondicion floracion
    0.24,  # floracion                  <- fase mas critica; T estrecha; polinizacion
    0.20,  # cuajado_fruto              <- 0.1% flores -> fruto; estres = caida masiva
    0.14,  # crecimiento_desarrollo_fruto
    0.06,  # maduracion_cosecha
    0.02,  # postcosecha
    0.03,  # renovacion_mantenimiento
)

# Pesos AHP por criterio
_PHH_AHP_WEIGHTS: dict[str, float] = {
    "aptitud_termica":           0.14,  # 20-25°C dia optimo (SENAMHI); estrecho en floracion
    "riesgo_frio":               0.08,  # Hass: daño a -1.1°C; 10°C noche fecundacion (SENAMHI)
    "riesgo_calor":              0.10,  # >35°C daña floracion/fructificacion (SENAMHI)
    "disponibilidad_hidrica":    0.09,  # disponibilidad hidrica permanente; goteo recomendado
    "deficit_hidrico":           0.10,  # estres en floracion/cuajado = caida de flores y frutos
    "aptitud_altitudinal":       0.08,  # contextual: 0-2700m SENAMHI; no descarte para Lima
    "aptitud_topografica":       0.09,  # drenaje CRITICO; pendiente modera encharcamiento
    "reaccion_suelo_ph":         0.07,  # tres rangos conflictivos; peso moderado
    "contenido_arcilla":         0.09,  # pesado -> mal drenaje -> Phytophthora cinnamomi
    "contenido_arena":           0.05,  # franco-arcilloso arenoso (SENAMHI); drenaje
    "carbono_organico_suelo":    0.04,  # "fertilidad media a alta"; 30 kg MO/planta (MIDAGRI)
    "salinidad_suelo":           0.05,  # FAO Paper 29: aguacate muy sensible ECe <1.5 dS/m
    "cobertura_actual_auxiliar": 0.02,  # auxiliar NDVI
}

# Politica critica: solo arcilla (drenaje -> Phytophthora); altitud SIN politica critica
_PHH_CRITICAL_SPECS: dict[str, tuple[CriticalPolicy, float | None]] = {
    "contenido_arcilla": (CriticalPolicy.PENALIZE, 0.65),
}

# ─── Trapecios palta_hass — 9 fases ──────────────────────────────────────────
# Orden fases: [instalacion, brotacion, induccion, floracion, cuajado,
#               crecimiento, maduracion, postcosecha, renovacion]

# aptitud_termica (temperatura_media_c °C)
# floracion/cuajado: optimo ESTRECHO 20-25°C (SENAMHI fecundacion y cuajado)
# induccion: COOLER — T baja activa induccion floral en palto
# MIDAGRI: 12-26°C apto; 10-32°C moderado; >32°C no apto
_PHH_T_MED: tuple = (
    (10, 14, 28, 32),  # instalacion_establecimiento   — amplio; planton tolerante
    (12, 16, 28, 32),  # brotacion_foliacion
    (10, 14, 22, 26),  # induccion_floral              <- COOLER; T baja activa induccion
    (16, 20, 25, 30),  # floracion                     <- ESTRECHO; 20-25°C fecundacion
    (16, 20, 25, 30),  # cuajado_fruto                 <- mismo; T critica cuajado
    (14, 18, 28, 32),  # crecimiento_desarrollo_fruto  — moderado; 12-26°C apto
    (12, 16, 28, 32),  # maduracion_cosecha
    ( 8, 12, 30, 36),  # postcosecha                   — amplio
    (10, 14, 28, 34),  # renovacion_mantenimiento      — amplio
)

# riesgo_frio (temperatura_minima_c °C)
# Hass: daño a -1.1°C (muy sensible); 10°C nocturno para buena fecundacion (SENAMHI)
# induccion: rango bajo preferido — noches frescas favorecen induccion floral en palto
# floracion: ~10°C nocturno optimo (SENAMHI)
_PHH_T_MIN: tuple = (
    ( 4,  8, 18, 24),  # instalacion_establecimiento
    ( 6, 10, 18, 24),  # brotacion_foliacion
    ( 4,  8, 16, 22),  # induccion_floral              <- rango bajo; noches frescas = induccion
    ( 8, 10, 18, 22),  # floracion                     <- 10°C nocturno optimo (SENAMHI)
    ( 8, 10, 18, 22),  # cuajado_fruto                 <- igual; T nocturna critica
    ( 6, 10, 18, 24),  # crecimiento_desarrollo_fruto
    ( 4,  8, 18, 24),  # maduracion_cosecha
    ( 0,  4, 18, 26),  # postcosecha                   — amplio
    ( 4,  8, 18, 26),  # renovacion_mantenimiento
)

# riesgo_calor (temperatura_maxima_c °C)
# ">35°C afecta floracion, polinizacion y desprendimiento de frutos" (SENAMHI)
# "MIDAGRI: >32°C no apto"
# floracion/cuajado: ESTRECHO; calor extremo = caida de flores y frutos
_PHH_T_MAX: tuple = (
    (20, 26, 32, 38),  # instalacion_establecimiento
    (20, 26, 32, 38),  # brotacion_foliacion
    (18, 24, 30, 36),  # induccion_floral              <- ligeramente mas estrecho
    (16, 22, 28, 34),  # floracion                     <- ESTRECHO; >35°C daña floracion
    (16, 22, 28, 34),  # cuajado_fruto                 <- mismo; calor = desprendimiento
    (18, 24, 32, 38),  # crecimiento_desarrollo_fruto
    (18, 24, 32, 38),  # maduracion_cosecha
    (16, 22, 34, 40),  # postcosecha                   — amplio
    (18, 24, 34, 40),  # renovacion_mantenimiento
)

# disponibilidad_hidrica (precipitacion_acumulada_mm mensual)
# "disponibilidad hidrica permanente"; frutal perenne irrigado
# riego goteo recomendado; 150 L/semana plantas >3 años (MIDAGRI)
_PHH_PRECIP = _same((0, 0, 800, 1600), len(_PHH_PHASES))

# deficit_hidrico (deficit_hidrico_mm mensual)
# induccion: leve deficit puede activar induccion floral (similar a mandarina pero mas suave)
# floracion/cuajado: CRITICO — umbral muy bajo; estres = caida masiva de flores y frutos
_PHH_DEFICIT: tuple = (
    (  0,   0, 400, 1000),  # instalacion_establecimiento
    (  0,   0, 300,  800),  # brotacion_foliacion
    ( 30,  80, 350,  700),  # induccion_floral          <- leve deficit modela activacion
    (  0,   0, 150,  500),  # floracion                 <- CRITICO; minimo deficit; goteo fuerte
    (  0,   0, 150,  500),  # cuajado_fruto             <- CRITICO; mismo; estres = caida frutos
    (  0,   0, 300,  700),  # crecimiento_desarrollo_fruto
    (  0,   0, 400,  900),  # maduracion_cosecha
    (  0,   0, 600, 1400),  # postcosecha               — amplio
    (  0,   0, 400, 1000),  # renovacion_mantenimiento
)

# aptitud_altitudinal (elevacion_m)
# SENAMHI: 0-2700 msnm (mas amplio que todos los cultivos anteriores)
# INIA recomienda 500-2500m pero SENAMHI reconoce costa 0m
# SIN politica critica: "altitud contextual, no de descarte" (decision documental)
_PHH_ELEV = _same((0, 0, 2000, 2700), len(_PHH_PHASES))

# aptitud_topografica (pendiente_grados)
# Pendiente moderada es POSITIVA para drenaje (previene encharcamiento y Phytophthora)
# Palto tolera mas pendiente que maiz (no mecanizacion intensiva)
_PHH_PEND = _same((0.0, 0.0, _deg(15), _deg(30)), len(_PHH_PHASES))

# reaccion_suelo_ph
# CONFLICTO DOCUMENTAL: SENAMHI 6.5-7.5 / MIDAGRI 6.5-7.0 / INIA 5.5-6.8
# Union conservadora: (5.0, 5.5, 7.5, 8.0); nota en doc_source
# No se consolida en un rango unico para no inventar conciliacion no documentada
_PHH_PH = _same((5.0, 5.5, 7.5, 8.0), len(_PHH_PHASES))

# contenido_arcilla (arcilla_pct)
# "suelo profundo y bien drenado" clave; "exceso de humedad favorece enfermedades radiculares"
# Suelos pesados -> mal drenaje -> asfixia radical -> Phytophthora cinnamomi (INIA/MIDAGRI)
# Textura franca/franco-arcilloso-arenosa; PENALIZE 0.65 si membresia=0 (>50% arcilla)
_PHH_CLAY = _same((5, 10, 30, 50), len(_PHH_PHASES))

# contenido_arena (arena_pct)
# Franco-arcilloso arenoso (SENAMHI): mas arena facilita drenaje
_PHH_SAND = _same((20, 35, 70, 85), len(_PHH_PHASES))

# carbono_organico_suelo (g/kg)
# "fertilidad media a alta apta"; 30 kg/planta compost+guano en instalacion (MIDAGRI)
_PHH_OC = _same((3, 8, 40, 70), len(_PHH_PHASES))

# salinidad_suelo (ECe dS/m — SoilGrids ISRIC)
# Aguacate/palta: muy sensible a sal; FAO Paper 29: umbral ECe=1.5 dS/m, ~19%/dS/m extra
# Lima costera: suelos irrigados con acumulacion de sales; lavado necesario si CE>2
_PHH_CE = _same((0.0, 0.0, 1.5, 3.0), len(_PHH_PHASES))

# cobertura_actual_auxiliar (ndvi)
_PHH_NDVI = _same((-0.10, 0.05, 0.90, 1.00), len(_PHH_PHASES))


# ─── ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#     UVA DE MESA SWEET GLOBE — Vitis vinifera L. var. Sweet Globe / IFG TEN
# ─── ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_SGV_DOC_SOURCE = (
    "SENAMHI Ficha Agroclimática Vid (cdn.www.gob.pe 2024); "
    "MIDAGRI Ficha Técnica Requerimientos Agroclimáticos Vid (repositorio.midagri.gob.pe); "
    "AgroRural/MIDAGRI Guía Vid; "
    "UNALM/ALICIA Manejo Sweet Globe Pacanga-Chepén La Libertad (repositorio.lamolina.edu.pe); "
    "SENASA Guía BPA Uva; "
    "Bloom Fresh Sweet Globe / IFG TEN (override varietal; no fuente peruana). "
    "AVISO: fuente local Sweet Globe es de costa norte (La Libertad), no de Lima costa. "
    "pH 5.5-8.5 (SENAMHI; rango muy amplio para vid; se usa unión casi completa). "
    "Umbrales derivados de documentación oficial peruana; no son guía agronómica completa."
)

# 13 fases fenologicas — vid perenne, ciclo productivo anual: (nombre, duracion_dias)
_SGV_PHASES: tuple[tuple[str, int], ...] = (
    ("instalacion_establecimiento",  90),  # terreno, hoyos, plantas, patron, estructura, riego
    ("reposo_vegetativo",            45),  # FRIO DESEADO: dormancia; T baja activa; Lima es reto
    ("poda_produccion",              20),  # define carga de yemas; estructura productiva
    ("hinchazon_yemas",              15),  # SENAMHI: 8-12°C inicia brotacion; inicio fenologico
    ("brotacion_desarrollo_brotes",  30),  # vigor, agua, nutricion, sanidad brotes
    ("aparicion_inflorescencias",    20),  # fertilidad de yemas; uniformidad; carga potencial
    ("floracion",                    15),  # CRITICA: 18-24°C; <15.5 o >30°C reduce floracion
    ("cuajado_fruto",                20),  # CRITICA: deficit = aborto; carga de racimos
    ("crecimiento_baya",             60),  # calibre 18-24mm (Bloom); agua + K; sanidad
    ("maduracion",                   30),  # 20°C dia / 15°C noche (SENAMHI); >16°Brix UNALM
    ("cosecha",                      15),  # seleccion; trazabilidad; ventana comercial
    ("postcosecha_exportacion",      10),  # cadena frio; hasta 90 dias (UNALM/ALICIA)
    ("renovacion_mantenimiento",     30),  # poda sanitaria; madera; preparacion siguiente campaña
)

# Pesos por fase: floracion + cuajado concentran 36%; con crecimiento_baya suman 50%
_SGV_PHASE_WEIGHTS: tuple[float, ...] = (
    0.04,  # instalacion_establecimiento
    0.04,  # reposo_vegetativo
    0.06,  # poda_produccion
    0.04,  # hinchazon_yemas
    0.09,  # brotacion_desarrollo_brotes
    0.07,  # aparicion_inflorescencias
    0.20,  # floracion                   <- fase mas critica; T 18-24°C muy estrecha
    0.16,  # cuajado_fruto              <- deficit = aborto masivo de bayas
    0.14,  # crecimiento_baya           <- calibre 18-24mm; Sweet Globe override
    0.10,  # maduracion                 <- Brix y condicion de cosecha; 20°C/15°C noche
    0.03,  # cosecha
    0.02,  # postcosecha_exportacion
    0.01,  # renovacion_mantenimiento
)

# Pesos AHP por criterio
_SGV_AHP_WEIGHTS: dict[str, float] = {
    "aptitud_termica":           0.15,  # por fase: reposo frio / floracion 18-24°C / maduracion 20°C
    "riesgo_frio":               0.08,  # <15.5°C reduce floracion (SENAMHI); dormancia DESEADA
    "riesgo_calor":              0.11,  # >30°C reduce floracion; >34°C quema hojas y racimos
    "disponibilidad_hidrica":    0.08,  # disponibilidad permanente; irrigado
    "deficit_hidrico":           0.09,  # floracion/cuajado CRITICOS; reposo: leve deficit ok
    "aptitud_altitudinal":       0.07,  # vid crece en muchas altitudes Peru; contextual
    "aptitud_topografica":       0.08,  # drenaje critico; pendiente favorece drenaje
    "reaccion_suelo_ph":         0.06,  # SENAMHI: 5.5-8.5 (muy amplio); peso moderado
    "contenido_arcilla":         0.08,  # arenoso/franco arenoso (SENAMHI); arcilla -> hongos
    "contenido_arena":           0.07,  # "arenoso / franco arenoso" SENAMHI; mayor peso que otros
    "carbono_organico_suelo":    0.06,  # fertilidad; 5-10 kg compost plantacion (AgroRural)
    "salinidad_suelo":           0.05,  # FAO Paper 29: vid moderadamente sensible ECe ~1.5 dS/m
    "cobertura_actual_auxiliar": 0.02,  # auxiliar NDVI
}

# Politica critica: solo arcilla; altitud sin politica critica (vid crece en muchos pisos)
_SGV_CRITICAL_SPECS: dict[str, tuple[CriticalPolicy, float | None]] = {
    "contenido_arcilla": (CriticalPolicy.PENALIZE, 0.65),
}

# ─── Trapecios uva_de_mesa_sweet_globe — 13 fases ────────────────────────────
# Orden fases: [instalacion, reposo, poda, hinchazon, brotacion, inflorescencias,
#               floracion, cuajado, crecimiento, maduracion, cosecha, postcosecha, renovacion]

# aptitud_termica (temperatura_media_c °C)
# NOVEDAD: reposo_vegetativo usa RANGO BAJO (T fria deseada para dormancia vid)
# hinchazon: 8-12°C inicia brotacion (SENAMHI); floracion: 18-24°C estricto
# maduracion: 20°C dia optimo (SENAMHI: "20°C favorece mayor peso de bayas")
_SGV_T_MED: tuple = (
    (12, 16, 28, 34),  # instalacion_establecimiento  — amplio
    ( 4,  8, 16, 20),  # reposo_vegetativo            <- BAJO; T fria DESEADA para dormancia
    ( 8, 12, 20, 26),  # poda_produccion              — periodo frio invierno
    ( 8, 12, 22, 28),  # hinchazon_yemas              <- 8-12°C inicia brotacion (SENAMHI)
    (12, 16, 26, 32),  # brotacion_desarrollo_brotes
    (14, 18, 26, 32),  # aparicion_inflorescencias
    (14, 18, 24, 30),  # floracion                    <- ESTRECHO; 18-24°C optimo (SENAMHI)
    (16, 20, 26, 32),  # cuajado_fruto
    (18, 22, 28, 34),  # crecimiento_baya             — calor moderado para desarrollo
    (16, 20, 26, 32),  # maduracion                   <- 20°C dia optimo; Brix acumulacion
    (14, 18, 28, 34),  # cosecha
    ( 4,  8, 22, 28),  # postcosecha_exportacion      — amplio; campo cosechado
    ( 8, 12, 24, 30),  # renovacion_mantenimiento
)

# riesgo_frio (temperatura_minima_c °C)
# reposo_vegetativo: RANGO BAJO — noches frias DESEADAS para dormancia vid
#   (igual que mandarina induccion_floral pero por motivo diferente: dormancia)
# floracion: >15.5°C nocturno necesario (SENAMHI: <15.5°C reduce floracion)
# maduracion: 15°C noche optimo (SENAMHI: "15°C nocturno favorece mayor peso de bayas")
_SGV_T_MIN: tuple = (
    ( 6, 10, 18, 24),  # instalacion_establecimiento
    ( 2,  4, 12, 18),  # reposo_vegetativo            <- BAJO; noches frias DESEADAS dormancia
    ( 4,  6, 14, 20),  # poda_produccion              — periodo invernal
    ( 6,  8, 16, 22),  # hinchazon_yemas              — aun frescas
    ( 8, 12, 18, 24),  # brotacion_desarrollo_brotes
    (10, 14, 20, 26),  # aparicion_inflorescencias
    (10, 14, 20, 26),  # floracion                    <- >15.5°C necesario; (14=b critico)
    (10, 14, 20, 26),  # cuajado_fruto
    (10, 14, 20, 26),  # crecimiento_baya             — noches templadas para desarrollo
    (10, 14, 20, 26),  # maduracion                   <- 15°C noche optimo (SENAMHI)
    ( 8, 12, 18, 24),  # cosecha
    ( 2,  4, 16, 22),  # postcosecha_exportacion      — amplio
    ( 4,  6, 16, 22),  # renovacion_mantenimiento
)

# riesgo_calor (temperatura_maxima_c °C)
# reposo_vegetativo: calor PENALIZA; noches calidas = no dormancia
# floracion: ESTRECHO; >30°C reduce floracion (SENAMHI); >34°C quema con viento (MIDAGRI)
# maduracion: calor excesivo reduce acumulacion de Brix y firmeza
_SGV_T_MAX: tuple = (
    (20, 26, 32, 38),  # instalacion_establecimiento
    (10, 14, 22, 28),  # reposo_vegetativo            <- BAJO; calor en invierno impide dormancia
    (12, 16, 24, 30),  # poda_produccion
    (14, 18, 26, 32),  # hinchazon_yemas
    (18, 24, 30, 36),  # brotacion_desarrollo_brotes
    (18, 24, 30, 36),  # aparicion_inflorescencias
    (14, 18, 24, 30),  # floracion                    <- ESTRECHO; >30°C reduce floracion (SENAMHI)
    (16, 22, 28, 34),  # cuajado_fruto
    (18, 24, 30, 36),  # crecimiento_baya
    (16, 22, 28, 34),  # maduracion                   <- calor excesivo afecta Brix y calidad
    (14, 20, 30, 36),  # cosecha
    ( 6, 10, 22, 28),  # postcosecha_exportacion      — amplio
    (12, 16, 26, 32),  # renovacion_mantenimiento
)

# disponibilidad_hidrica (precipitacion_acumulada_mm mensual)
# Vid irrigada en costa; riego tecnificado recomendado para uva de mesa exportable
_SGV_PRECIP = _same((0, 0, 600, 1400), len(_SGV_PHASES))

# deficit_hidrico (deficit_hidrico_mm mensual)
# reposo: leve deficit BENEFICIA dormancia (similar a mandarina/palta en induccion)
# floracion/cuajado: CRITICO — deficit = aborto de flores y bayas
# crecimiento_baya: importante — deficit afecta calibre (18-24mm Sweet Globe)
# maduracion: exceso de agua tambien afecta condicion; trapecio moderado
_SGV_DEFICIT: tuple = (
    (  0,   0, 400, 1000),  # instalacion_establecimiento
    ( 50, 100, 500, 1000),  # reposo_vegetativo          <- leve deficit ayuda dormancia
    (  0,   0, 400, 1000),  # poda_produccion
    (  0,   0, 300,  800),  # hinchazon_yemas
    (  0,   0, 300,  700),  # brotacion_desarrollo_brotes
    (  0,   0, 250,  600),  # aparicion_inflorescencias
    (  0,   0, 200,  500),  # floracion                   <- CRITICO; deficit = mala floracion
    (  0,   0, 200,  500),  # cuajado_fruto               <- CRITICO; deficit = aborto bayas
    (  0,   0, 250,  600),  # crecimiento_baya            <- afecta calibre Sweet Globe
    (  0,   0, 300,  700),  # maduracion
    (  0,   0, 400,  900),  # cosecha
    (  0,   0, 600, 1400),  # postcosecha_exportacion     — amplio
    (  0,   0, 400, 1000),  # renovacion_mantenimiento
)

# aptitud_altitudinal (elevacion_m)
# Vid peruana crece en muchos pisos: costa (0-500m), sierra baja (1000-2000m),
#   valles interandinos (hasta 2500m en Arequipa, Junin, etc.)
# Sin politica critica: altitud contextual segun zona objetivo
_SGV_ELEV = _same((0, 0, 1500, 2400), len(_SGV_PHASES))

# aptitud_topografica (pendiente_grados)
# Drenaje critico; pendiente moderada favorece drenaje y reduce riesgo fungico
# Vid de mesa tolera algo de pendiente; estructura de conduccion requiere cierta uniformidad
_SGV_PEND = _same((0.0, 0.0, _deg(15), _deg(30)), len(_SGV_PHASES))

# reaccion_suelo_ph
# SENAMHI: 5.5-8.5 — el rango mas amplio de los 5 cultivos
# No se estrecha sin fuente especifica de Sweet Globe para Lima; usar casi completo
_SGV_PH = _same((5.0, 5.5, 8.0, 8.5), len(_SGV_PHASES))

# contenido_arcilla (arcilla_pct)
# SENAMHI: "arenoso / franco arenoso" — menor arcilla = mejor drenaje = menos hongos
# PENALIZE 0.65 si membresia=0 (>45% arcilla -> drenaje deficiente -> enfermedades)
_SGV_CLAY = _same((5, 8, 25, 45), len(_SGV_PHASES))

# contenido_arena (arena_pct)
# "arenoso / franco arenoso" (SENAMHI): mayor preferencia por arena que cualquier otro cultivo
# Mas arena = mejor drenaje = menos presion fungica = mejor calidad de fruto
_SGV_SAND = _same((35, 50, 80, 90), len(_SGV_PHASES))

# carbono_organico_suelo (g/kg)
# "fertilidad del suelo"; 5-10 kg compost en plantacion (AgroRural/MIDAGRI)
_SGV_OC = _same((2, 5, 35, 65), len(_SGV_PHASES))

# salinidad_suelo (ECe dS/m — SoilGrids ISRIC)
# Vid: moderadamente sensible; FAO Paper 29: umbral ECe ~1.5 dS/m, ~9.6%/dS/m extra
# Mas tolerante que citricos/palta; algunos portainjertos incrementan tolerancia
_SGV_CE = _same((0.0, 0.0, 1.5, 5.0), len(_SGV_PHASES))

# cobertura_actual_auxiliar (ndvi)
_SGV_NDVI = _same((-0.10, 0.05, 0.90, 1.00), len(_SGV_PHASES))


# ─── Tabla de trapecios ───────────────────────────────────────────────────────

_TRAP: dict[tuple[str, str], tuple] = {
    ("maiz_amarillo_duro", "aptitud_termica"):           _MAD_T_MED,
    ("maiz_amarillo_duro", "riesgo_frio"):               _MAD_T_MIN,
    ("maiz_amarillo_duro", "riesgo_calor"):              _MAD_T_MAX,
    ("maiz_amarillo_duro", "disponibilidad_hidrica"):    _MAD_PRECIP,
    ("maiz_amarillo_duro", "deficit_hidrico"):           _MAD_DEFICIT,
    ("maiz_amarillo_duro", "aptitud_altitudinal"):       _MAD_ELEV,
    ("maiz_amarillo_duro", "aptitud_topografica"):       _MAD_PEND,
    ("maiz_amarillo_duro", "reaccion_suelo_ph"):         _MAD_PH,
    ("maiz_amarillo_duro", "contenido_arcilla"):         _MAD_CLAY,
    ("maiz_amarillo_duro", "contenido_arena"):           _MAD_SAND,
    ("maiz_amarillo_duro", "carbono_organico_suelo"):    _MAD_OC,
    ("maiz_amarillo_duro", "salinidad_suelo"):           _MAD_CE,
    ("maiz_amarillo_duro", "cobertura_actual_auxiliar"): _MAD_NDVI,

    # ── Mandarina Murcott ─────────────────────────────────────────────────────
    ("mandarina_murcott", "aptitud_termica"):           _MCT_T_MED,
    ("mandarina_murcott", "riesgo_frio"):               _MCT_T_MIN,
    ("mandarina_murcott", "riesgo_calor"):              _MCT_T_MAX,
    ("mandarina_murcott", "disponibilidad_hidrica"):    _MCT_PRECIP,
    ("mandarina_murcott", "deficit_hidrico"):           _MCT_DEFICIT,
    ("mandarina_murcott", "aptitud_altitudinal"):       _MCT_ELEV,
    ("mandarina_murcott", "aptitud_topografica"):       _MCT_PEND,
    ("mandarina_murcott", "reaccion_suelo_ph"):         _MCT_PH,
    ("mandarina_murcott", "contenido_arcilla"):         _MCT_CLAY,
    ("mandarina_murcott", "contenido_arena"):           _MCT_SAND,
    ("mandarina_murcott", "carbono_organico_suelo"):    _MCT_OC,
    ("mandarina_murcott", "salinidad_suelo"):           _MCT_CE,
    ("mandarina_murcott", "cobertura_actual_auxiliar"): _MCT_NDVI,

    # ── Maracuya Criolla Amarilla ─────────────────────────────────────────────
    ("maracuya_criolla_amarilla", "aptitud_termica"):           _MRC_T_MED,
    ("maracuya_criolla_amarilla", "riesgo_frio"):               _MRC_T_MIN,
    ("maracuya_criolla_amarilla", "riesgo_calor"):              _MRC_T_MAX,
    ("maracuya_criolla_amarilla", "disponibilidad_hidrica"):    _MRC_PRECIP,
    ("maracuya_criolla_amarilla", "deficit_hidrico"):           _MRC_DEFICIT,
    ("maracuya_criolla_amarilla", "aptitud_altitudinal"):       _MRC_ELEV,
    ("maracuya_criolla_amarilla", "aptitud_topografica"):       _MRC_PEND,
    ("maracuya_criolla_amarilla", "reaccion_suelo_ph"):         _MRC_PH,
    ("maracuya_criolla_amarilla", "contenido_arcilla"):         _MRC_CLAY,
    ("maracuya_criolla_amarilla", "contenido_arena"):           _MRC_SAND,
    ("maracuya_criolla_amarilla", "carbono_organico_suelo"):    _MRC_OC,
    ("maracuya_criolla_amarilla", "salinidad_suelo"):           _MRC_CE,
    ("maracuya_criolla_amarilla", "cobertura_actual_auxiliar"): _MRC_NDVI,

    # ── Palta Hass ────────────────────────────────────────────────────────────
    ("palta_hass", "aptitud_termica"):           _PHH_T_MED,
    ("palta_hass", "riesgo_frio"):               _PHH_T_MIN,
    ("palta_hass", "riesgo_calor"):              _PHH_T_MAX,
    ("palta_hass", "disponibilidad_hidrica"):    _PHH_PRECIP,
    ("palta_hass", "deficit_hidrico"):           _PHH_DEFICIT,
    ("palta_hass", "aptitud_altitudinal"):       _PHH_ELEV,
    ("palta_hass", "aptitud_topografica"):       _PHH_PEND,
    ("palta_hass", "reaccion_suelo_ph"):         _PHH_PH,
    ("palta_hass", "contenido_arcilla"):         _PHH_CLAY,
    ("palta_hass", "contenido_arena"):           _PHH_SAND,
    ("palta_hass", "carbono_organico_suelo"):    _PHH_OC,
    ("palta_hass", "salinidad_suelo"):           _PHH_CE,
    ("palta_hass", "cobertura_actual_auxiliar"): _PHH_NDVI,

    # ── Uva de Mesa Sweet Globe ───────────────────────────────────────────────
    ("uva_de_mesa_sweet_globe", "aptitud_termica"):           _SGV_T_MED,
    ("uva_de_mesa_sweet_globe", "riesgo_frio"):               _SGV_T_MIN,
    ("uva_de_mesa_sweet_globe", "riesgo_calor"):              _SGV_T_MAX,
    ("uva_de_mesa_sweet_globe", "disponibilidad_hidrica"):    _SGV_PRECIP,
    ("uva_de_mesa_sweet_globe", "deficit_hidrico"):           _SGV_DEFICIT,
    ("uva_de_mesa_sweet_globe", "aptitud_altitudinal"):       _SGV_ELEV,
    ("uva_de_mesa_sweet_globe", "aptitud_topografica"):       _SGV_PEND,
    ("uva_de_mesa_sweet_globe", "reaccion_suelo_ph"):         _SGV_PH,
    ("uva_de_mesa_sweet_globe", "contenido_arcilla"):         _SGV_CLAY,
    ("uva_de_mesa_sweet_globe", "contenido_arena"):           _SGV_SAND,
    ("uva_de_mesa_sweet_globe", "carbono_organico_suelo"):    _SGV_OC,
    ("uva_de_mesa_sweet_globe", "salinidad_suelo"):           _SGV_CE,
    ("uva_de_mesa_sweet_globe", "cobertura_actual_auxiliar"): _SGV_NDVI,
}


# ─── Pesos AHP y fases por cultivo ───────────────────────────────────────────

_AHP_WEIGHTS: dict[str, dict[str, float]] = {
    "maiz_amarillo_duro":        _MAD_AHP_WEIGHTS,
    "mandarina_murcott":         _MCT_AHP_WEIGHTS,
    "maracuya_criolla_amarilla": _MRC_AHP_WEIGHTS,
    "palta_hass":                _PHH_AHP_WEIGHTS,
    "uva_de_mesa_sweet_globe":   _SGV_AHP_WEIGHTS,
}

_PHASE_WEIGHTS: dict[str, tuple[float, ...]] = {
    "maiz_amarillo_duro":        _MAD_PHASE_WEIGHTS,
    "mandarina_murcott":         _MCT_PHASE_WEIGHTS,
    "maracuya_criolla_amarilla": _MRC_PHASE_WEIGHTS,
    "palta_hass":                _PHH_PHASE_WEIGHTS,
    "uva_de_mesa_sweet_globe":   _SGV_PHASE_WEIGHTS,
}

_PHASES_BY_CROP: dict[str, tuple[tuple[str, int], ...]] = {
    "maiz_amarillo_duro":        _MAD_PHASES,
    "mandarina_murcott":         _MCT_PHASES,
    "maracuya_criolla_amarilla": _MRC_PHASES,
    "palta_hass":                _PHH_PHASES,
    "uva_de_mesa_sweet_globe":   _SGV_PHASES,
}

_CRITICAL_SPECS: dict[str, dict[str, tuple[CriticalPolicy, float | None]]] = {
    "maiz_amarillo_duro":        _MAD_CRITICAL_SPECS,
    "mandarina_murcott":         _MCT_CRITICAL_SPECS,
    "maracuya_criolla_amarilla": _MRC_CRITICAL_SPECS,
    "palta_hass":                _PHH_CRITICAL_SPECS,
    "uva_de_mesa_sweet_globe":   _SGV_CRITICAL_SPECS,
}

_DOC_SOURCES: dict[str, str] = {
    "maiz_amarillo_duro":        _MAD_DOC_SOURCE,
    "mandarina_murcott":         _MCT_DOC_SOURCE,
    "maracuya_criolla_amarilla": _MRC_DOC_SOURCE,
    "palta_hass":                _PHH_DOC_SOURCE,
    "uva_de_mesa_sweet_globe":   _SGV_DOC_SOURCE,
}

_MAD_SOIL_TECHNICAL_NOTES: dict[str, str] = {
    "contenido_arcilla": (
        "Trapecio actual maiz_amarillo_duro=(5,15,40,60), sin cambio de valores. "
        "No se hallo en fuentes peruanas (MIDAGRI, INIA) ni internacionales "
        "(FAO/GAEZ) un rango cuantitativo (%) recomendado para maiz. Las fuentes "
        "describen textura por clases cualitativas: \"franco\", \"franco arcilloso "
        "arenoso\", \"franco arcilloso\" (MIDAGRI Ficha Agroclimatica MAD pag.2; "
        "Manual Tecnico INIA pag.59). El trapecio actual es una traduccion "
        "operacional de estas clases texturales a rangos USDA/FAO estandar, NO un "
        "umbral cuantitativo citado de fuente maicera especifica. Dato de calicata "
        "La Molina 2007 (SENAMHI, pag.45: arena 36%, limo 46%, arcilla 18%) es una "
        "medicion puntual de perfil de suelo, no un rango recomendado, y no se usa "
        "como umbral."
    ),
    "contenido_arena": (
        "Trapecio actual maiz_amarillo_duro=(15,35,65,80), sin cambio de valores. "
        "No se hallo en fuentes peruanas (MIDAGRI, INIA) ni internacionales "
        "(FAO/GAEZ) un rango cuantitativo (%) recomendado para maiz. Las fuentes "
        "describen textura por clases cualitativas: \"franco\", \"franco arcilloso "
        "arenoso\", \"franco arcilloso\" (MIDAGRI Ficha Agroclimatica MAD pag.2; "
        "Manual Tecnico INIA pag.59). El trapecio actual es una traduccion "
        "operacional de estas clases texturales a rangos USDA/FAO estandar, NO un "
        "umbral cuantitativo citado de fuente maicera especifica. Dato de calicata "
        "La Molina 2007 (SENAMHI, pag.45: arena 36%, limo 46%, arcilla 18%) es una "
        "medicion puntual de perfil de suelo, no un rango recomendado, y no se usa "
        "como umbral."
    ),
    "carbono_organico_suelo": (
        "Trapecio actual maiz_amarillo_duro=(2,10,40,70) g/kg COS, sin cambio de "
        "valores. Anclas verificadas: MIDAGRI Ficha Agroclimatica MAD (Peru): "
        "materia organica alta >4%. INIA Manejo Agronomico Selva Baja (Peru): "
        "materia organica 2,0-4,0%. Discrepancia entre fuentes peruanas "
        "posiblemente por diferencia agroecologica costa/selva; MAD costa se "
        "referencia principalmente a MIDAGRI. Conversion MO->COS via factor 1,72 "
        "(Fertiberia, fuente general de analisis de suelo, no especifica de maiz). "
        "Puntos no cubiertos exactamente por fuente se mantienen por consistencia "
        "operativa."
    ),
}

_MCT_SOIL_TECHNICAL_NOTES: dict[str, str] = {
    "contenido_arcilla": (
        "Trapecio actual mandarina_murcott=(5,10,35,55), sin cambio de valores. "
        "Ancla citricola verificada: evitar arcilla superior a 35% segun ILSA, "
        "\"Como cultivar y fertilizar los citricos\" (Italia), que indica evitar "
        "suelos con valores de arcilla superiores al 35%. El rango estructural "
        "12-18% aparece en fuente general de suelos/Infoagro y en la sintesis "
        "tecnica, pero no se hallo como umbral citricola primario. Los puntos "
        "intermedios 5,10 y 55 se adoptan por consistencia con clasificacion "
        "textural estandar y manejo de drenaje, sin fuente cuantitativa primaria "
        "que los fije exactamente. Contexto: fuentes internacionales de "
        "citricultura/suelo (Italia, Espana, Florida); no se hallo fuente "
        "cuantitativa peruana de textura para citricos. Referencia general "
        "adoptada por convergencia documental."
    ),
    "contenido_arena": (
        "Trapecio actual mandarina_murcott=(15,25,65,80), sin cambio de valores. "
        "No se hallo en el corpus una fuente primaria citricola que fije "
        "textualmente 23-86% de arena ni marginal >90% como rango cuantitativo "
        "para mandarina/citricos. La referencia textual verificada es cualitativa: "
        "citricos prefieren suelos francos, franco-arenosos o franco-arcillosos, "
        "bien drenados. Los puntos del trapecio se adoptan por consistencia con "
        "clasificacion textural estandar y necesidad de drenaje, no por un umbral "
        "cuantitativo primario exacto. Contexto: fuentes internacionales de "
        "citricultura/suelo (Espana, Italia, Florida y documentos generales); no "
        "se hallo fuente cuantitativa peruana de textura para citricos. Referencia "
        "general adoptada por convergencia documental."
    ),
    "carbono_organico_suelo": (
        "Trapecio actual mandarina_murcott=(2,8,40,70) g/kg COS, sin cambio de "
        "valores. Anclas verificadas: materia organica no inferior al 2% en ILSA, "
        "\"Como cultivar y fertilizar los citricos\" (Italia), y aporte de materia "
        "organica si el suelo no llega al 2% en BOE 137/2004 (Espana). Conversion "
        "verificada en Fertiberia/Analisis de Tierra Frutales: la materia organica "
        "contiene aprox. 58% de carbono y el carbono organico se calcula dividiendo "
        "la materia organica por 1,72. Por esa conversion, 2% MO equivale aprox. a "
        "1,16% COS, es decir 11,6 g/kg COS. No se hallo fuente primaria que fije "
        "exactamente todos los puntos 2,8,40,70 g/kg; se mantienen por consistencia "
        "operativa del modelo y clasificacion general de fertilidad. Contexto: "
        "fuentes internacionales (Espana, Italia, Florida); no se hallo fuente "
        "cuantitativa peruana de carbono organico para citricos. Referencia general "
        "adoptada por convergencia documental."
    ),
}


# ─── Seeding functions ────────────────────────────────────────────────────────


def seed_prod_rulebooks(
    session_factory: Callable,
    crops_to_seed: dict[str, str],
    cleanup_func: Callable[[Session, list[str]], None] | None = None,
    repository_factory: Callable[[Session], RulebookRepositoryLike] | None = None,
) -> list[SeededRulebook]:
    """Replace existing prod rulebooks and publish one active version per crop."""

    session = session_factory()
    try:
        resolved_cleanup = cleanup_func or _remove_existing_prod_rulebooks
        resolved_repository_factory = repository_factory or SqlAlchemyRulebookRepository
        resolved_cleanup(session, list(crops_to_seed.keys()))
        seeded = _create_and_publish(resolved_repository_factory(session), crops_to_seed)
        session.commit()
        return seeded
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _create_and_publish(
    repository: RulebookRepositoryLike,
    crops: dict[str, str],
) -> list[SeededRulebook]:
    service = RulebookCommandService(repository=repository)
    seeded: list[SeededRulebook] = []
    for crop_id, display_name in crops.items():
        criteria, phases, requirements = build_prod_rulebook_parts(crop_id)
        rulebook = service.create_rulebook(
            crop_id=crop_id,
            criteria=criteria,
            phases=phases,
            phase_requirements=requirements,
        )
        service.publish_rulebook(rulebook.id)
        seeded.append(SeededRulebook(
            crop_id=rulebook.crop_id,
            display_name=display_name,
            rulebook_id=rulebook.id,
            version=rulebook.version,
            status=rulebook.status.value,
        ))
    return seeded


def build_prod_rulebook_parts(
    crop_id: str,
) -> tuple[list[Criterion], list[PhenologicalPhase], list[PhaseRequirement]]:
    """Build production rulebook graph for one crop."""

    if crop_id not in PROD_CROPS:
        raise ValueError(f"Cultivo de produccion desconocido: {crop_id!r}")

    phases_spec = _PHASES_BY_CROP[crop_id]
    phase_weights = _PHASE_WEIGHTS[crop_id]
    ahp_weights = _AHP_WEIGHTS[crop_id]
    critical_specs = _CRITICAL_SPECS.get(crop_id, {})
    doc_source = _DOC_SOURCES[crop_id]

    criteria = [
        _build_criterion(crop_id, name, ahp_weights, critical_specs, doc_source)
        for name in _CRITERIA
    ]
    phases = [
        PhenologicalPhase(
            id=_stable_id(crop_id, "phase", phase_name),
            name=phase_name,
            duration_days=duration_days,
            sequence_order=index,
        )
        for index, (phase_name, duration_days) in enumerate(phases_spec, start=1)
    ]
    requirements = [
        _build_requirement(crop_id, criterion, phase, phase_idx, phase_weights)
        for criterion in criteria
        for phase_idx, phase in enumerate(phases)
    ]
    return criteria, phases, requirements


# ─── Builders ─────────────────────────────────────────────────────────────────


def _build_criterion(
    crop_id: str,
    criterion_name: str,
    ahp_weights: dict[str, float],
    critical_specs: dict[str, tuple[CriticalPolicy, float | None]],
    doc_source: str,
) -> Criterion:
    binding = _CRITERION_BINDING[criterion_name]

    if criterion_name in critical_specs:
        policy, penalty_factor = critical_specs[criterion_name]
        is_critical = True
    else:
        policy = None
        penalty_factor = None
        is_critical = False

    if criterion_name == "cobertura_actual_auxiliar":
        role_note = (
            "variable auxiliar NDVI (Sentinel-2). Peso 0.02; no determina viabilidad. "
            "Trapecio amplio: no colapsa por barbecho ni suelo preparado. "
            "Clasificado STRUCTURAL por convencion para suprimir recomendacion; "
            "no es un impedimento estructural real de la parcela (cf. aptitud_altitudinal). "
            "Deuda de modelado: considerar valor NON_ACTIONABLE en iteracion futura."
        )
    elif criterion_name == "salinidad_suelo":
        role_note = (
            "criterio edafico estatico (SoilGrids ISRIC ECe, ece_0-5cm_mean, ~250m). "
            "Umbral FAO Paper 29 (Ayers & Westcott 1985); valores en dS/m. "
            "Sin politica critica; costa irrigada Peru tipicamente <4 dS/m."
        )
    elif criterion_name in _SOIL_CRITERIA:
        role_note = (
            f"criterio edafico estatico (OpenLandMap ~250m, topsoil_0_30cm_mean). "
            f"Sin politica critica; piso minimo de membresia no critica previene colapso WGM."
        )
    elif criterion_name in ("aptitud_altitudinal", "aptitud_topografica"):
        role_note = "criterio estructural estatico (SRTM)."
    elif criterion_name in ("disponibilidad_hidrica", "deficit_hidrico"):
        role_note = (
            "criterio climatico-hidrico (ERA5-Land / CHIRPS). "
            "Clasificado CORRECTABLE bajo asuncion de acceso a riego. "
            "En contexto de secano sin fuente de agua accesible, "
            "este criterio podria ser de facto STRUCTURAL."
        )
    else:
        role_note = "criterio climatico (ERA5-Land / CHIRPS)."

    extra_technical_note = ""
    if crop_id == "maiz_amarillo_duro" and criterion_name in _MAD_SOIL_TECHNICAL_NOTES:
        extra_technical_note = f" {_MAD_SOIL_TECHNICAL_NOTES[criterion_name]}"
    if crop_id == "mandarina_murcott" and criterion_name in _MCT_SOIL_TECHNICAL_NOTES:
        extra_technical_note = f" {_MCT_SOIL_TECHNICAL_NOTES[criterion_name]}"

    return Criterion(
        id=_stable_id(crop_id, "criterion", criterion_name),
        name=criterion_name,
        is_critical=is_critical,
        critical_policy=policy,
        penalty_factor=penalty_factor,
        ahp_weight=ahp_weights[criterion_name],
        intervention_class=_INTERVENTION_CLASS[criterion_name],
        doc_source=doc_source,
        technical_notes=(
            f"prod_rulebook_v1 {crop_id}. "
            f"Criterio '{criterion_name}' -> {binding.variable_name} ({binding.dataset_key}). "
            f"{role_note}"
            f"{extra_technical_note}"
        ),
    )


def _build_requirement(
    crop_id: str,
    criterion: Criterion,
    phase: PhenologicalPhase,
    phase_idx: int,
    phase_weights: tuple[float, ...],
) -> PhaseRequirement:
    trap = _TRAP[(crop_id, criterion.name)][phase_idx]
    binding = _CRITERION_BINDING[criterion.name]
    return PhaseRequirement(
        id=_stable_id(crop_id, "requirement", criterion.name, phase.name),
        criterion_id=criterion.id,
        phase_id=phase.id,
        membership_fn=MembershipFunction(a=float(trap[0]), b=float(trap[1]), c=float(trap[2]), d=float(trap[3])),
        phase_weight=phase_weights[phase_idx],
        temporal_periods=[
            TemporalPeriod(
                period_key=f"{phase.name}_climate",
                temporal_weight=1.0,
            )
        ],
        extraction_binding=binding,
    )


# ─── Cleanup ──────────────────────────────────────────────────────────────────


def _remove_existing_prod_rulebooks(session: Session, crop_ids: list[str]) -> None:
    """Delete existing prod rulebooks by crop_id so seeding is idempotent."""

    session.execute(
        text(
            """
            DELETE FROM transactional.rulebook_phase_requirements
            WHERE criterion_id IN (
                SELECT c.id FROM transactional.rulebook_criteria c
                JOIN transactional.rulebooks r ON r.id = c.rulebook_id
                WHERE r.crop_id IN :crop_ids
            )
            OR phase_id IN (
                SELECT p.id FROM transactional.rulebook_phases p
                JOIN transactional.rulebooks r ON r.id = p.rulebook_id
                WHERE r.crop_id IN :crop_ids
            )
            """
        ).bindparams(bindparam("crop_ids", expanding=True)),
        {"crop_ids": crop_ids},
    )
    session.execute(
        text(
            """
            DELETE FROM transactional.rulebook_phases
            WHERE rulebook_id IN (
                SELECT id FROM transactional.rulebooks WHERE crop_id IN :crop_ids
            )
            """
        ).bindparams(bindparam("crop_ids", expanding=True)),
        {"crop_ids": crop_ids},
    )
    session.execute(
        text(
            """
            DELETE FROM transactional.rulebook_criteria
            WHERE rulebook_id IN (
                SELECT id FROM transactional.rulebooks WHERE crop_id IN :crop_ids
            )
            """
        ).bindparams(bindparam("crop_ids", expanding=True)),
        {"crop_ids": crop_ids},
    )
    session.execute(
        text("DELETE FROM transactional.rulebooks WHERE crop_id IN :crop_ids").bindparams(
            bindparam("crop_ids", expanding=True)
        ),
        {"crop_ids": crop_ids},
    )


# ─── CLI ──────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="seed_prod_rulebooks.py",
        description="Seed production rulebooks for VIA real crops.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--only",
        metavar="CROP_ID",
        help=f"Seed only this crop. Valid: {', '.join(PROD_CROPS)}",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    if args.only is not None:
        if args.only not in PROD_CROPS:
            print(
                f"ERROR: Cultivo desconocido '{args.only}'. "
                f"Validos: {', '.join(PROD_CROPS)}",
                file=sys.stderr,
            )
            sys.exit(1)
        crops_to_seed = {args.only: PROD_CROPS[args.only]}
    else:
        crops_to_seed = dict(PROD_CROPS)

    database_url = require_database_url()
    engine = create_engine(database_url, future=True)
    try:
        session_factory = sessionmaker(bind=engine, class_=Session, autoflush=False, expire_on_commit=False)
        seeded = seed_prod_rulebooks(session_factory, crops_to_seed)
    finally:
        engine.dispose()

    print("Seeded production rulebooks:")
    for item in seeded:
        print(f"  {item.crop_id} ({item.display_name}): {item.status} v{item.version} {item.rulebook_id}")
    print()
    print("FUENTES: SENASA BPA 2020 / MIDAGRI Ficha Tecnica 09 / SENAMHI 2010 / INIA variedades")
    print("AVISO: umbrales derivados de documentacion oficial; no son guia agronomica completa.")


# ─── UUID estables ────────────────────────────────────────────────────────────


def _stable_id(crop_id: str, *parts: str) -> UUID:
    return uuid5(NAMESPACE_URL, ":".join(("via-prod-rulebook-v1", crop_id, *parts)))


if __name__ == "__main__":
    main()
