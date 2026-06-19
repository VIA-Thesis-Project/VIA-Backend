"""Registry of supported GEE variable definitions for agroenvironmental extraction.

Each entry maps a variable_name to its technical extraction definition.
The GEE client uses this registry to dispatch the correct extraction strategy
without embedding dataset or formula knowledge directly in the client.

Categories:
    remote_sensing — Sentinel-2 spectral variables
    topographic    — SRTM elevation / slope
    climate        — ERA5-Land monthly + CHIRPS daily climatology
    soil           — OpenLandMap static soil properties (~250 m, global)

Climate sources:
    ECMWF/ERA5_LAND/MONTHLY_AGGR  — ~11 km, monthly, global (temperature, PET)
    UCSB-CHG/CHIRPS/DAILY         — ~5.5 km, daily, global (precipitation)
    deficit_hidrico_mm derived as max(0, PET - P) from above

Soil sources (OpenLandMap v02):
    OpenLandMap/SOL/SOL_PH-H2O_USDA-4C1A2A_M/v02         — pH in H2O × 10, depths 0–200 cm
    OpenLandMap/SOL/SOL_CLAY-WFRACTION_USDA-3A1A1A_M/v02  — clay % × 10, depths 0–200 cm
    OpenLandMap/SOL/SOL_SAND-WFRACTION_USDA-3A1A1A_M/v02  — sand % × 10, depths 0–200 cm
    OpenLandMap/SOL/SOL_ORGANIC-CARBON_USDA-6A1C_M/v02    — OC in ×5 g/kg, depths 0–200 cm
    OpenLandMap/SOL/SOL_TEXTURE-CLASS_USDA-TT_M/v02       — USDA texture class 1–12 (integer)
    Band naming: b0=0 cm, b10=10 cm, b30=30 cm, b60=60 cm, b100=100 cm, b200=200 cm
    depth_strategy controls which bands are used — see GeeVariableDefinition.depth_strategy.

Conversion notes:
    ERA5-Land temperatures are in Kelvin; subtract 273.15 to obtain °C (offset field).
    ERA5-Land potential_evaporation_sum is in meters with negative sign convention
    (upward flux); abs() then ×1000 yields positive mm demand (normalize_sign + scale_factor).
    CHIRPS precipitation is already in mm; no conversion needed.
    OpenLandMap pH: raw × 0.1 → real pH units.
    OpenLandMap clay/sand: raw × 0.1 → real % (stored as %×10).
    OpenLandMap OC: raw × 0.2 → g/kg (stored as OC_g_per_kg × 5).
    OpenLandMap texture class: integer 1–12, no conversion.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class GeeVariableType(str, Enum):
    """Classification of a GEE extraction variable by computation strategy."""

    SIMPLE_BAND     = "SIMPLE_BAND"      # single raw band from an ImageCollection
    DERIVED_INDEX   = "DERIVED_INDEX"    # spectral index computed from multiple bands
    TOPO_STATIC     = "TOPO_STATIC"      # single band from a static ee.Image (no date filter)
    TOPO_DERIVED    = "TOPO_DERIVED"     # derived from a static ee.Image (e.g. slope)
    CLIMATE_SIMPLE  = "CLIMATE_SIMPLE"   # single band from a monthly/daily ImageCollection + conversion
    CLIMATE_DERIVED = "CLIMATE_DERIVED"  # derived from multiple registered CLIMATE_SIMPLE variables
    SOIL_STATIC     = "SOIL_STATIC"      # static soil layer from OpenLandMap with depth strategy


@dataclass(frozen=True)
class GeeVariableDefinition:
    """Metadata for one supported GEE variable.

    Fields:
        variable_name:        Canonical name used in RequiredExtractionSpec.
        variable_type:        Extraction strategy dispatcher key.
        dataset_key:          GEE catalog dataset identifier.
        source_bands:         Bands required from the dataset. Empty tuple for CLIMATE_DERIVED.
                              For SOIL_STATIC with topsoil_0_30cm_mean: ("b0", "b10", "b30").
                              For SOIL_STATIC with surface_0cm: ("b0",).
        result_band:          Band/key used to fetch the value from reduceRegion result.
                              For SOIL_STATIC: equals variable_name (image renamed before query).
        unit:                 Physical unit of the extracted value (after all conversions).
        default_reducer:      Default spatial reducer (always applied over parcel geometry).
        default_scale:        Default spatial scale in metres.
        formula_note:         Human-readable formula description (None for raw bands).
        scale_factor:         Multiply raw GEE value to obtain intermediate units (e.g. 1000 m→mm).
                              None means the raw value is already in the desired intermediate units.
                              OpenLandMap soil: 0.1 for pH/clay/sand (stored ×10); 0.2 for OC (stored ×5).
        offset:               Additive offset applied AFTER scale_factor and normalize_sign
                              (e.g. -273.15 to convert Kelvin to Celsius). None means no offset.
        normalize_sign:       If True, take abs() of the value after scale_factor.
                              Used for ERA5 potential_evaporation_sum which is negative.
        temporal_aggregation: How to collapse the time dimension before spatial reduction.
                              "mean" for temperature; "sum" for precipitation/ET/deficit.
        category:             Variable group: "remote_sensing", "topographic", "climate", "soil".
        derived_from:         For CLIMATE_DERIVED: ordered tuple of source variable_names
                              to extract and combine. None for all other types.
        spatial_sampling_strategy: How to resolve the parcel geometry to a sampling region.
                              "polygon_mean"    — reduceRegion over the full parcel polygon (default).
                              "centroid_sample" — sample at the polygon centroid point.
                                 Use for coarse-resolution datasets (ERA5 ~11 km, CHIRPS ~5.5 km,
                                 OpenLandMap ~250 m) where the parcel may be smaller than one pixel.
                              "buffered_mean"   — reserved for future use; not yet implemented.
        depth_strategy:       For SOIL_STATIC only — controls which depth bands to aggregate:
                              "surface_0cm"        — use only the 0 cm band (b0).
                              "topsoil_0_30cm_mean" — arithmetic mean of 0, 10, 30 cm (b0, b10, b30).
                              None for all non-soil variable types.
    """

    variable_name: str
    variable_type: GeeVariableType
    dataset_key: str
    source_bands: tuple[str, ...]
    result_band: str
    unit: str
    default_reducer: str
    default_scale: float
    formula_note: str | None = None
    scale_factor: float | None = None
    offset: float | None = None
    normalize_sign: bool = False
    temporal_aggregation: str = "mean"
    category: str = "remote_sensing"
    derived_from: tuple[str, ...] | None = None
    spatial_sampling_strategy: str = "polygon_mean"
    depth_strategy: str | None = None


_REGISTRY: dict[str, GeeVariableDefinition] = {}


def _reg(*defns: GeeVariableDefinition) -> None:
    for d in defns:
        _REGISTRY[d.variable_name] = d


_reg(
    # ── Sentinel-2 raw band ───────────────────────────────────────────────────
    GeeVariableDefinition(
        variable_name="nir_reflectancia",
        variable_type=GeeVariableType.SIMPLE_BAND,
        dataset_key="COPERNICUS/S2_SR_HARMONIZED",
        source_bands=("B8",),
        result_band="B8",
        unit="reflectance_scaled",
        default_reducer="mean",
        default_scale=10.0,
        formula_note=None,
        category="remote_sensing",
    ),
    # ── Sentinel-2 derived indices ────────────────────────────────────────────
    GeeVariableDefinition(
        variable_name="ndvi",
        variable_type=GeeVariableType.DERIVED_INDEX,
        dataset_key="COPERNICUS/S2_SR_HARMONIZED",
        source_bands=("B8", "B4"),
        result_band="ndvi",
        unit="index",
        default_reducer="mean",
        default_scale=10.0,
        formula_note="(B8 - B4) / (B8 + B4)  range: [-1, 1]",
        category="remote_sensing",
    ),
    GeeVariableDefinition(
        variable_name="savi",
        variable_type=GeeVariableType.DERIVED_INDEX,
        dataset_key="COPERNICUS/S2_SR_HARMONIZED",
        source_bands=("B8", "B4"),
        result_band="savi",
        unit="index",
        default_reducer="mean",
        default_scale=10.0,
        formula_note="((B8 - B4) / (B8 + B4 + L)) * (1 + L)  L=0.5  range: [-1, 1]",
        category="remote_sensing",
    ),
    GeeVariableDefinition(
        variable_name="ndmi",
        variable_type=GeeVariableType.DERIVED_INDEX,
        dataset_key="COPERNICUS/S2_SR_HARMONIZED",
        source_bands=("B8", "B11"),
        result_band="ndmi",
        unit="index",
        default_reducer="mean",
        default_scale=20.0,
        formula_note="(B8 - B11) / (B8 + B11)  range: [-1, 1]",
        category="remote_sensing",
    ),
    # ── SRTM topographic variables ────────────────────────────────────────────
    GeeVariableDefinition(
        variable_name="elevacion_m",
        variable_type=GeeVariableType.TOPO_STATIC,
        dataset_key="USGS/SRTMGL1_003",
        source_bands=("elevation",),
        result_band="elevation",
        unit="m",
        default_reducer="mean",
        default_scale=30.0,
        formula_note=None,
        category="topographic",
    ),
    GeeVariableDefinition(
        variable_name="pendiente_grados",
        variable_type=GeeVariableType.TOPO_DERIVED,
        dataset_key="USGS/SRTMGL1_003",
        source_bands=("elevation",),
        result_band="slope",
        unit="degrees",
        default_reducer="mean",
        default_scale=30.0,
        formula_note="ee.Terrain.slope(ee.Image(dataset_key))",
        category="topographic",
    ),
    # ── ERA5-Land monthly climate variables ───────────────────────────────────
    # Dataset: ECMWF/ERA5_LAND/MONTHLY_AGGR  (~11 132 m, monthly, global, 1950–present)
    # Temperatures in Kelvin; subtract 273.15 to obtain °C (offset field).
    # Available within ~2-3 months of real time; no multi-year lag.
    GeeVariableDefinition(
        variable_name="temperatura_minima_c",
        variable_type=GeeVariableType.CLIMATE_SIMPLE,
        dataset_key="ECMWF/ERA5_LAND/MONTHLY_AGGR",
        source_bands=("temperature_2m_min",),
        result_band="temperature_2m_min",
        unit="celsius",
        default_reducer="mean",
        default_scale=11132.0,
        formula_note="temperature_2m_min - 273.15  [raw: K, monthly min of hourly 2m temp]  temporal: mean over period",
        scale_factor=None,
        offset=-273.15,
        temporal_aggregation="mean",
        category="climate",
        spatial_sampling_strategy="centroid_sample",
    ),
    GeeVariableDefinition(
        variable_name="temperatura_maxima_c",
        variable_type=GeeVariableType.CLIMATE_SIMPLE,
        dataset_key="ECMWF/ERA5_LAND/MONTHLY_AGGR",
        source_bands=("temperature_2m_max",),
        result_band="temperature_2m_max",
        unit="celsius",
        default_reducer="mean",
        default_scale=11132.0,
        formula_note="temperature_2m_max - 273.15  [raw: K, monthly max of hourly 2m temp]  temporal: mean over period",
        scale_factor=None,
        offset=-273.15,
        temporal_aggregation="mean",
        category="climate",
        spatial_sampling_strategy="centroid_sample",
    ),
    GeeVariableDefinition(
        variable_name="temperatura_media_c",
        variable_type=GeeVariableType.CLIMATE_SIMPLE,
        dataset_key="ECMWF/ERA5_LAND/MONTHLY_AGGR",
        source_bands=("temperature_2m",),
        result_band="temperature_2m",
        unit="celsius",
        default_reducer="mean",
        default_scale=11132.0,
        formula_note="temperature_2m - 273.15  [raw: K, monthly mean 2m temp]  temporal: mean over period",
        scale_factor=None,
        offset=-273.15,
        temporal_aggregation="mean",
        category="climate",
        spatial_sampling_strategy="centroid_sample",
    ),
    GeeVariableDefinition(
        variable_name="evapotranspiracion_referencia_mm",
        variable_type=GeeVariableType.CLIMATE_SIMPLE,
        dataset_key="ECMWF/ERA5_LAND/MONTHLY_AGGR",
        source_bands=("potential_evaporation_sum",),
        result_band="potential_evaporation_sum",
        unit="mm",
        default_reducer="mean",
        default_scale=11132.0,
        formula_note=(
            "abs(potential_evaporation_sum) * 1000  "
            "[raw: m, negative ERA5 sign convention — upward flux]  "
            "temporal: sum over period"
        ),
        scale_factor=1000.0,
        normalize_sign=True,
        temporal_aggregation="sum",
        category="climate",
        spatial_sampling_strategy="centroid_sample",
    ),
    # ── CHIRPS daily precipitation ────────────────────────────────────────────
    # Dataset: UCSB-CHG/CHIRPS/DAILY  (~5 566 m, daily, 50°S–50°N, 1981–present)
    # Already in mm; no conversion needed. Near-real-time (~2 week lag).
    GeeVariableDefinition(
        variable_name="precipitacion_acumulada_mm",
        variable_type=GeeVariableType.CLIMATE_SIMPLE,
        dataset_key="UCSB-CHG/CHIRPS/DAILY",
        source_bands=("precipitation",),
        result_band="precipitation",
        unit="mm",
        default_reducer="mean",
        default_scale=5566.0,
        formula_note="precipitation  [raw: mm/day]  temporal: sum over period",
        scale_factor=None,
        temporal_aggregation="sum",
        category="climate",
        spatial_sampling_strategy="centroid_sample",
    ),
    # ── Derived: deficit hídrico ──────────────────────────────────────────────
    # Derived from ERA5-Land PET and CHIRPS P already extracted above.
    # Formula: max(0, evapotranspiracion_referencia_mm - precipitacion_acumulada_mm)
    # Zero when precipitation meets or exceeds evaporative demand.
    GeeVariableDefinition(
        variable_name="deficit_hidrico_mm",
        variable_type=GeeVariableType.CLIMATE_DERIVED,
        dataset_key="ECMWF/ERA5_LAND/MONTHLY_AGGR",   # primary source (for source string)
        source_bands=(),                                # no direct GEE bands — see derived_from
        result_band="deficit_hidrico_mm",
        unit="mm",
        default_reducer="mean",
        default_scale=11132.0,
        formula_note="max(0, evapotranspiracion_referencia_mm - precipitacion_acumulada_mm)",
        temporal_aggregation="sum",
        category="climate",
        derived_from=("evapotranspiracion_referencia_mm", "precipitacion_acumulada_mm"),
    ),
    # ── OpenLandMap static soil variables ─────────────────────────────────────
    # Dataset family: OpenLandMap/SOL/* v02, ~250 m resolution, global static.
    # Band names by depth: b0=0 cm, b10=10 cm, b30=30 cm, b60=60 cm, b100=100 cm, b200=200 cm.
    # Use centroid_sample (250 m pixels can be larger than small parcelas).
    # topsoil_0_30cm_mean averages bands b0+b10+b30 before spatial sampling.
    GeeVariableDefinition(
        variable_name="ph_suelo",
        variable_type=GeeVariableType.SOIL_STATIC,
        dataset_key="OpenLandMap/SOL/SOL_PH-H2O_USDA-4C1A2A_M/v02",
        source_bands=("b0", "b10", "b30"),
        result_band="ph_suelo",
        unit="pH",
        default_reducer="mean",
        default_scale=250.0,
        formula_note="topsoil_0_30cm_mean(b0,b10,b30) × 0.1  [raw: pH×10 in H2O]",
        scale_factor=0.1,
        category="soil",
        depth_strategy="topsoil_0_30cm_mean",
        spatial_sampling_strategy="centroid_sample",
    ),
    GeeVariableDefinition(
        variable_name="arcilla_pct",
        variable_type=GeeVariableType.SOIL_STATIC,
        dataset_key="OpenLandMap/SOL/SOL_CLAY-WFRACTION_USDA-3A1A1A_M/v02",
        source_bands=("b0", "b10", "b30"),
        result_band="arcilla_pct",
        unit="%",
        default_reducer="mean",
        default_scale=250.0,
        formula_note="topsoil_0_30cm_mean(b0,b10,b30) × 0.1  [raw: clay wt fraction %×10]",
        scale_factor=0.1,
        category="soil",
        depth_strategy="topsoil_0_30cm_mean",
        spatial_sampling_strategy="centroid_sample",
    ),
    GeeVariableDefinition(
        variable_name="arena_pct",
        variable_type=GeeVariableType.SOIL_STATIC,
        dataset_key="OpenLandMap/SOL/SOL_SAND-WFRACTION_USDA-3A1A1A_M/v02",
        source_bands=("b0", "b10", "b30"),
        result_band="arena_pct",
        unit="%",
        default_reducer="mean",
        default_scale=250.0,
        formula_note="topsoil_0_30cm_mean(b0,b10,b30) × 0.1  [raw: sand wt fraction %×10]",
        scale_factor=0.1,
        category="soil",
        depth_strategy="topsoil_0_30cm_mean",
        spatial_sampling_strategy="centroid_sample",
    ),
    GeeVariableDefinition(
        variable_name="carbono_organico_suelo",
        variable_type=GeeVariableType.SOIL_STATIC,
        dataset_key="OpenLandMap/SOL/SOL_ORGANIC-CARBON_USDA-6A1C_M/v02",
        source_bands=("b0", "b10", "b30"),
        result_band="carbono_organico_suelo",
        unit="g/kg",
        default_reducer="mean",
        default_scale=250.0,
        formula_note="topsoil_0_30cm_mean(b0,b10,b30) × 0.2  [raw: OC in ×5 g/kg; ÷5=×0.2→g/kg]",
        scale_factor=0.2,
        category="soil",
        depth_strategy="topsoil_0_30cm_mean",
        spatial_sampling_strategy="centroid_sample",
    ),
    GeeVariableDefinition(
        variable_name="textura_suelo_clase",
        variable_type=GeeVariableType.SOIL_STATIC,
        dataset_key="OpenLandMap/SOL/SOL_TEXTURE-CLASS_USDA-TT_M/v02",
        source_bands=("b0",),
        result_band="textura_suelo_clase",
        unit="USDA_class",
        default_reducer="mean",
        default_scale=250.0,
        formula_note="surface_0cm(b0)  [integer 1–12: USDA texture class, no conversion]",
        scale_factor=None,
        category="soil",
        depth_strategy="surface_0cm",
        spatial_sampling_strategy="centroid_sample",
    ),
)


def get_variable_definition(variable_name: str) -> GeeVariableDefinition | None:
    """Return the definition for a named variable, or None if not registered."""
    return _REGISTRY.get(variable_name)


def list_variable_names() -> list[str]:
    """Return all registered variable names in registration order."""
    return list(_REGISTRY)


def list_variable_names_by_category(category: str) -> list[str]:
    """Return variable names filtered by category in registration order."""
    return [name for name, defn in _REGISTRY.items() if defn.category == category]
