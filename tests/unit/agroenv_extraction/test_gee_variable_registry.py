"""Unit tests for the GEE variable registry."""

from __future__ import annotations

import pytest

from via.bounded_contexts.agroenv_extraction.infrastructure.gee_variable_registry import (
    GeeVariableDefinition,
    GeeVariableType,
    get_variable_definition,
    list_variable_names,
    list_variable_names_by_category,
)

_ERA5 = "ECMWF/ERA5_LAND/MONTHLY_AGGR"
_CHIRPS = "UCSB-CHG/CHIRPS/DAILY"
_TERRACLIMATE = "IDAHO_EPSCOR/TERRACLIMATE"

# ─── Variable sets ────────────────────────────────────────────────────────────

_REMOTE_SENSING_VARS = {"nir_reflectancia", "ndvi", "savi", "ndmi"}
_TOPO_VARS = {"elevacion_m", "pendiente_grados"}
_CLIMATE_VARS = {
    "temperatura_minima_c",
    "temperatura_maxima_c",
    "temperatura_media_c",
    "precipitacion_acumulada_mm",
    "evapotranspiracion_referencia_mm",
    "deficit_hidrico_mm",
}
_SOIL_VARS = {
    "ph_suelo",
    "arcilla_pct",
    "arena_pct",
    "carbono_organico_suelo",
    "textura_suelo_clase",
}
_ALL_VARS = _REMOTE_SENSING_VARS | _TOPO_VARS | _CLIMATE_VARS | _SOIL_VARS


# ─── Registration completeness ────────────────────────────────────────────────


def test_all_seventeen_variables_are_registered() -> None:
    assert set(list_variable_names()) == _ALL_VARS


def test_list_variable_names_contains_seventeen_entries() -> None:
    assert len(list_variable_names()) == 17


def test_evapotranspiracion_real_is_not_registered() -> None:
    """evapotranspiracion_real_mm was retired — must not appear in the active registry."""
    assert get_variable_definition("evapotranspiracion_real_mm") is None


def test_unknown_variable_returns_none() -> None:
    assert get_variable_definition("no_existe") is None


def test_unknown_variable_empty_string_returns_none() -> None:
    assert get_variable_definition("") is None


# ─── No active climate variable uses TerraClimate ────────────────────────────


def test_no_climate_variable_uses_terraclimate() -> None:
    """All active climate variables must use ERA5-Land or CHIRPS — not TerraClimate."""
    for name in _CLIMATE_VARS:
        defn = get_variable_definition(name)
        assert defn is not None
        assert defn.dataset_key != _TERRACLIMATE, (
            f"{name} still points to TerraClimate: {defn.dataset_key!r}"
        )


# ─── Individual variable definitions: remote sensing ─────────────────────────


def test_nir_reflectancia_is_simple_band() -> None:
    defn = get_variable_definition("nir_reflectancia")
    assert defn is not None
    assert defn.variable_type == GeeVariableType.SIMPLE_BAND
    assert defn.dataset_key == "COPERNICUS/S2_SR_HARMONIZED"
    assert defn.result_band == "B8"
    assert "B8" in defn.source_bands
    assert defn.default_scale == 10.0


def test_ndvi_is_derived_index() -> None:
    defn = get_variable_definition("ndvi")
    assert defn is not None
    assert defn.variable_type == GeeVariableType.DERIVED_INDEX
    assert defn.dataset_key == "COPERNICUS/S2_SR_HARMONIZED"
    assert "B8" in defn.source_bands
    assert "B4" in defn.source_bands
    assert defn.result_band == "ndvi"
    assert defn.default_scale == 10.0
    assert defn.formula_note is not None


def test_savi_is_derived_index() -> None:
    defn = get_variable_definition("savi")
    assert defn is not None
    assert defn.variable_type == GeeVariableType.DERIVED_INDEX
    assert defn.dataset_key == "COPERNICUS/S2_SR_HARMONIZED"
    assert "B8" in defn.source_bands
    assert "B4" in defn.source_bands
    assert defn.result_band == "savi"
    assert defn.default_scale == 10.0
    assert defn.formula_note is not None
    assert "L=0.5" in defn.formula_note or "L" in defn.formula_note


def test_ndmi_is_derived_index() -> None:
    defn = get_variable_definition("ndmi")
    assert defn is not None
    assert defn.variable_type == GeeVariableType.DERIVED_INDEX
    assert defn.dataset_key == "COPERNICUS/S2_SR_HARMONIZED"
    assert "B8" in defn.source_bands
    assert "B11" in defn.source_bands
    assert defn.result_band == "ndmi"
    assert defn.default_scale == 20.0


def test_elevacion_m_is_topo_static() -> None:
    defn = get_variable_definition("elevacion_m")
    assert defn is not None
    assert defn.variable_type == GeeVariableType.TOPO_STATIC
    assert defn.dataset_key == "USGS/SRTMGL1_003"
    assert defn.result_band == "elevation"
    assert defn.default_scale == 30.0
    assert defn.unit == "m"


def test_pendiente_grados_is_topo_derived() -> None:
    defn = get_variable_definition("pendiente_grados")
    assert defn is not None
    assert defn.variable_type == GeeVariableType.TOPO_DERIVED
    assert defn.dataset_key == "USGS/SRTMGL1_003"
    assert defn.result_band == "slope"
    assert defn.default_scale == 30.0
    assert defn.unit == "degrees"
    assert defn.formula_note is not None


# ─── Dataset grouping ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["nir_reflectancia", "ndvi", "savi", "ndmi"])
def test_sentinel2_variables_share_copernicus_dataset(name: str) -> None:
    defn = get_variable_definition(name)
    assert defn is not None
    assert defn.dataset_key == "COPERNICUS/S2_SR_HARMONIZED"


@pytest.mark.parametrize("name", ["elevacion_m", "pendiente_grados"])
def test_topographic_variables_share_srtm_dataset(name: str) -> None:
    defn = get_variable_definition(name)
    assert defn is not None
    assert defn.dataset_key == "USGS/SRTMGL1_003"


_ERA5_CLIMATE_VARS = [
    "temperatura_minima_c",
    "temperatura_maxima_c",
    "temperatura_media_c",
    "evapotranspiracion_referencia_mm",
    "deficit_hidrico_mm",
]


@pytest.mark.parametrize("name", _ERA5_CLIMATE_VARS)
def test_era5_climate_variables_use_era5_land_dataset(name: str) -> None:
    defn = get_variable_definition(name)
    assert defn is not None
    assert defn.dataset_key == _ERA5, f"{name}: expected ERA5, got {defn.dataset_key!r}"


def test_precipitation_uses_chirps_dataset() -> None:
    defn = get_variable_definition("precipitacion_acumulada_mm")
    assert defn is not None
    assert defn.dataset_key == _CHIRPS


# ─── GeeVariableDefinition is immutable ───────────────────────────────────────


def test_variable_definition_is_frozen() -> None:
    defn = get_variable_definition("ndvi")
    assert defn is not None
    with pytest.raises((AttributeError, TypeError)):
        defn.variable_type = GeeVariableType.SIMPLE_BAND  # type: ignore[misc]


# ─── Source-band vs result-band discipline ────────────────────────────────────


@pytest.mark.parametrize("name", ["ndvi", "savi", "ndmi"])
def test_derived_index_result_band_differs_from_all_source_bands(name: str) -> None:
    defn = get_variable_definition(name)
    assert defn is not None
    assert defn.result_band not in defn.source_bands, (
        f"{name}: result_band {defn.result_band!r} must not appear in source_bands "
        f"{defn.source_bands!r} — they are Sentinel-2 raw band names (e.g. 'B8'), "
        "not index names"
    )


# ─── GeeVariableType enum values ─────────────────────────────────────────────


def test_variable_type_enum_has_seven_members() -> None:
    assert len(GeeVariableType) == 7
    assert {t.value for t in GeeVariableType} == {
        "SIMPLE_BAND",
        "DERIVED_INDEX",
        "TOPO_STATIC",
        "TOPO_DERIVED",
        "CLIMATE_SIMPLE",
        "CLIMATE_DERIVED",
        "SOIL_STATIC",
    }


# ─── Lookup is idempotent ─────────────────────────────────────────────────────


def test_repeated_lookup_returns_same_object() -> None:
    a = get_variable_definition("ndvi")
    b = get_variable_definition("ndvi")
    assert a is b


# ─── ERA5-Land temperature variables (Kelvin → °C) ───────────────────────────


@pytest.mark.parametrize("name,band", [
    ("temperatura_minima_c", "temperature_2m_min"),
    ("temperatura_maxima_c", "temperature_2m_max"),
    ("temperatura_media_c",  "temperature_2m"),
])
def test_era5_temperature_variables_correct_band(name: str, band: str) -> None:
    defn = get_variable_definition(name)
    assert defn is not None
    assert band in defn.source_bands
    assert defn.result_band == band


@pytest.mark.parametrize("name", [
    "temperatura_minima_c",
    "temperatura_maxima_c",
    "temperatura_media_c",
])
def test_era5_temperature_has_kelvin_offset(name: str) -> None:
    defn = get_variable_definition(name)
    assert defn is not None
    assert defn.offset is not None
    assert abs(defn.offset - (-273.15)) < 1e-9, (
        f"{name}: offset should be -273.15 (K→°C), got {defn.offset}"
    )


@pytest.mark.parametrize("name", [
    "temperatura_minima_c",
    "temperatura_maxima_c",
    "temperatura_media_c",
])
def test_era5_temperature_has_no_scale_factor(name: str) -> None:
    """ERA5 temperature needs only the offset, no multiplicative scale."""
    defn = get_variable_definition(name)
    assert defn is not None
    assert defn.scale_factor is None


@pytest.mark.parametrize("name", [
    "temperatura_minima_c",
    "temperatura_maxima_c",
    "temperatura_media_c",
])
def test_era5_temperature_unit_is_celsius(name: str) -> None:
    defn = get_variable_definition(name)
    assert defn is not None
    assert defn.unit == "celsius"


def test_temperatura_media_is_climate_simple() -> None:
    """temperatura_media_c is now CLIMATE_SIMPLE (direct band from ERA5 temperature_2m)."""
    defn = get_variable_definition("temperatura_media_c")
    assert defn is not None
    assert defn.variable_type == GeeVariableType.CLIMATE_SIMPLE


@pytest.mark.parametrize("name", [
    "temperatura_minima_c",
    "temperatura_maxima_c",
    "temperatura_media_c",
])
def test_era5_temperature_uses_mean_temporal_aggregation(name: str) -> None:
    defn = get_variable_definition(name)
    assert defn is not None
    assert defn.temporal_aggregation == "mean"


# ─── ERA5-Land PET variable ───────────────────────────────────────────────────


def test_pet_uses_era5_band() -> None:
    defn = get_variable_definition("evapotranspiracion_referencia_mm")
    assert defn is not None
    assert "potential_evaporation_sum" in defn.source_bands
    assert defn.result_band == "potential_evaporation_sum"


def test_pet_scale_factor_is_1000() -> None:
    """ERA5 PET is in meters; ×1000 converts to mm."""
    defn = get_variable_definition("evapotranspiracion_referencia_mm")
    assert defn is not None
    assert defn.scale_factor == 1000.0


def test_pet_normalize_sign_is_true() -> None:
    """ERA5 potential_evaporation_sum is negative by convention; abs() gives positive demand."""
    defn = get_variable_definition("evapotranspiracion_referencia_mm")
    assert defn is not None
    assert defn.normalize_sign is True


def test_pet_has_no_offset() -> None:
    """PET needs abs()*1000 but no additive offset."""
    defn = get_variable_definition("evapotranspiracion_referencia_mm")
    assert defn is not None
    assert defn.offset is None


def test_pet_uses_sum_temporal_aggregation() -> None:
    defn = get_variable_definition("evapotranspiracion_referencia_mm")
    assert defn is not None
    assert defn.temporal_aggregation == "sum"


def test_pet_unit_is_mm() -> None:
    defn = get_variable_definition("evapotranspiracion_referencia_mm")
    assert defn is not None
    assert defn.unit == "mm"


# ─── CHIRPS precipitation ─────────────────────────────────────────────────────


def test_precipitation_uses_chirps_band() -> None:
    defn = get_variable_definition("precipitacion_acumulada_mm")
    assert defn is not None
    assert "precipitation" in defn.source_bands
    assert defn.result_band == "precipitation"


def test_precipitation_has_no_scale_or_offset() -> None:
    """CHIRPS precipitation is already in mm; no conversion needed."""
    defn = get_variable_definition("precipitacion_acumulada_mm")
    assert defn is not None
    assert defn.scale_factor is None
    assert defn.offset is None
    assert defn.normalize_sign is False


def test_precipitation_uses_sum_temporal_aggregation() -> None:
    defn = get_variable_definition("precipitacion_acumulada_mm")
    assert defn is not None
    assert defn.temporal_aggregation == "sum"


def test_precipitation_unit_is_mm() -> None:
    defn = get_variable_definition("precipitacion_acumulada_mm")
    assert defn is not None
    assert defn.unit == "mm"


# ─── Deficit hídrico derivado ─────────────────────────────────────────────────


def test_deficit_is_climate_derived() -> None:
    defn = get_variable_definition("deficit_hidrico_mm")
    assert defn is not None
    assert defn.variable_type == GeeVariableType.CLIMATE_DERIVED


def test_deficit_has_derived_from() -> None:
    defn = get_variable_definition("deficit_hidrico_mm")
    assert defn is not None
    assert defn.derived_from is not None
    assert "evapotranspiracion_referencia_mm" in defn.derived_from
    assert "precipitacion_acumulada_mm" in defn.derived_from


def test_deficit_formula_note_mentions_max_zero() -> None:
    defn = get_variable_definition("deficit_hidrico_mm")
    assert defn is not None
    assert defn.formula_note is not None
    assert "max" in defn.formula_note.lower()
    assert "0" in defn.formula_note


def test_deficit_has_no_source_bands() -> None:
    """Derived variables have no direct GEE bands."""
    defn = get_variable_definition("deficit_hidrico_mm")
    assert defn is not None
    assert defn.source_bands == ()


def test_deficit_unit_is_mm() -> None:
    defn = get_variable_definition("deficit_hidrico_mm")
    assert defn is not None
    assert defn.unit == "mm"


# ─── ERA5-Land spatial scale ──────────────────────────────────────────────────


@pytest.mark.parametrize("name", _ERA5_CLIMATE_VARS)
def test_era5_variables_use_era5_scale(name: str) -> None:
    defn = get_variable_definition(name)
    assert defn is not None
    assert defn.default_scale == 11132.0, f"{name}: expected 11132.0, got {defn.default_scale}"


def test_chirps_uses_chirps_scale() -> None:
    defn = get_variable_definition("precipitacion_acumulada_mm")
    assert defn is not None
    assert defn.default_scale == 5566.0


# ─── Category filtering ───────────────────────────────────────────────────────


def test_list_by_category_climate_returns_six() -> None:
    names = list_variable_names_by_category("climate")
    assert len(names) == 6
    assert set(names) == _CLIMATE_VARS


def test_list_by_category_topographic_returns_two() -> None:
    names = list_variable_names_by_category("topographic")
    assert set(names) == _TOPO_VARS


def test_list_by_category_remote_sensing_returns_four() -> None:
    names = list_variable_names_by_category("remote_sensing")
    assert set(names) == _REMOTE_SENSING_VARS


def test_legacy_variables_keep_defaults_for_new_fields() -> None:
    """Variables registered before new fields were added should use safe defaults."""
    defn = get_variable_definition("ndvi")
    assert defn is not None
    assert defn.scale_factor is None
    assert defn.offset is None
    assert defn.normalize_sign is False
    assert defn.temporal_aggregation == "mean"
    assert defn.category == "remote_sensing"
    assert defn.derived_from is None


def test_topo_variables_have_no_new_climate_fields() -> None:
    for name in _TOPO_VARS:
        defn = get_variable_definition(name)
        assert defn is not None
        assert defn.offset is None
        assert defn.normalize_sign is False
        assert defn.derived_from is None


def test_list_by_category_soil_returns_five() -> None:
    names = list_variable_names_by_category("soil")
    assert len(names) == 5
    assert set(names) == _SOIL_VARS


def test_soil_variables_have_no_offset_or_normalize_sign() -> None:
    for name in _SOIL_VARS:
        defn = get_variable_definition(name)
        assert defn is not None
        assert defn.offset is None
        assert defn.normalize_sign is False
        assert defn.category == "soil"
