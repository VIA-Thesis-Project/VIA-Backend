"""Unit tests for OpenLandMap soil variables: registry, GEE client dispatch, and seed coherence.

Covers:
    - Registry recognition of 5 soil variables (SOIL_STATIC type, category, metadata)
    - depth_strategy field: surface_0cm and topsoil_0_30cm_mean
    - GEE client dispatch: SOIL_STATIC routes to _extract_soil
    - Topsoil depth averaging (b0 + b10 + b30) / 3 before scale_factor
    - Scale factor conversions: pH/clay/sand (×0.1), OC (×0.2), texture (None=pass through)
    - centroid_sample strategy for all soil variables
    - Missing value (None raw) propagation
    - Seed AHP weights: sum = 1.00, soil group = 0.27, climate = 0.48
    - textura_suelo_clase NOT a seed criterion
    - Data sufficiency policy: soil missing (0.27) < threshold (0.30) → PARCIAL
    - Soil (0.27) + one climate (≥0.07) missing → ≥0.34 → potential NO_CONCLUYENTE
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest

from via.bounded_contexts.agroenv_extraction.application.ports import ExtractionRequest
from via.bounded_contexts.agroenv_extraction.infrastructure.gee_client import (
    GeeExtractionClient,
    GeeExtractionError,
    _extract_soil,
)
from via.bounded_contexts.agroenv_extraction.infrastructure.gee_variable_registry import (
    GeeVariableType,
    get_variable_definition,
    list_variable_names_by_category,
)
from via.config import load_settings

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from seed_potential_viability_rulebooks import (  # noqa: E402
    _AHP_WEIGHTS,
    _CRITERIA,
    _SOIL_CRITERIA,
)


# ─── Constants ────────────────────────────────────────────────────────────────

_OLM_PH   = "OpenLandMap/SOL/SOL_PH-H2O_USDA-4C1A2A_M/v02"
_OLM_CLAY = "OpenLandMap/SOL/SOL_CLAY-WFRACTION_USDA-3A1A1A_M/v02"
_OLM_SAND = "OpenLandMap/SOL/SOL_SAND-WFRACTION_USDA-3A1A1A_M/v02"
_OLM_OC   = "OpenLandMap/SOL/SOL_ORGANIC-CARBON_USDA-6A1C_M/v02"
_OLM_TEX  = "OpenLandMap/SOL/SOL_TEXTURE-CLASS_USDA-TT_M/v02"

_TOPSOIL_VARS = ("ph_suelo", "arcilla_pct", "arena_pct", "carbono_organico_suelo")
_SURFACE_VARS = ("textura_suelo_clase",)
_ALL_SOIL_VARS = _TOPSOIL_VARS + _SURFACE_VARS


# ─── FakeSoilEE ───────────────────────────────────────────────────────────────


class _FakeRef:
    def __init__(self, value: float | int | None) -> None:
        self._value = value

    def getInfo(self) -> float | int | None:
        return self._value


class _FakeRegion:
    def __init__(self, value: float | int | None) -> None:
        self._value = value

    def get(self, band: str) -> _FakeRef:
        return _FakeRef(self._value)


class _FakeBandImage:
    """Represents a single-band image — supports arithmetic ops and reduceRegion."""

    def __init__(self, value: float | int | None) -> None:
        self._value = value

    def add(self, other: "_FakeBandImage") -> "_FakeBandImage":
        if self._value is None or other._value is None:
            return _FakeBandImage(None)
        return _FakeBandImage(self._value + other._value)

    def divide(self, n: int | float) -> "_FakeBandImage":
        if self._value is None:
            return _FakeBandImage(None)
        return _FakeBandImage(self._value / n)

    def rename(self, name: str) -> "_FakeBandImage":
        return _FakeBandImage(self._value)

    def reduceRegion(self, **kwargs) -> _FakeRegion:
        return _FakeRegion(self._value)


class FakeSoilImage:
    """Fake ee.Image for an OpenLandMap static image with per-band raw values."""

    def __init__(self, band_values: dict[str, float | int | None]) -> None:
        self._band_values = band_values

    def select(self, band: str) -> _FakeBandImage:
        return _FakeBandImage(self._band_values.get(band))


class _FakeGeometry:
    def __init__(self) -> None:
        self.point_calls: list[tuple] = []
        self.polygon_calls: list[object] = []

    def Point(self, coords: object) -> tuple:
        self.point_calls.append(coords)
        return ("Point", coords)

    def Polygon(self, coordinates: object) -> tuple:
        self.polygon_calls.append(coordinates)
        return ("Polygon", coordinates)

    def MultiPolygon(self, coordinates: object) -> tuple:
        return ("MultiPolygon", coordinates)


class _FakeReducer:
    def mean(self) -> str:
        return "mean"

    def median(self) -> str:
        return "median"

    def min(self) -> str:
        return "min"

    def max(self) -> str:
        return "max"


class _FakeData:
    def setDeadline(self, ms: int) -> None:
        pass


class FakeSoilEE:
    """Minimal fake earth-engine module for testing soil extraction paths."""

    def __init__(self, band_values: dict[str, float | int | None] | None = None) -> None:
        self._band_values: dict[str, float | int | None] = band_values or {}
        self.geometry_calls: list = []
        self.image_calls: list[str] = []
        self.Geometry = _FakeGeometry()
        self.Reducer = _FakeReducer()
        self.data = _FakeData()
        self.initialize_calls: list = []
        self.credentials_calls: list = []
        self.deadline_calls: list = []

    def ServiceAccountCredentials(self, svc: str, key: str) -> str:
        self.credentials_calls.append((svc, key))
        return "cred"

    def Initialize(self, cred: str, project: str | None = None) -> None:
        self.initialize_calls.append((cred, project))

    def Image(self, dataset_key: str) -> FakeSoilImage:
        self.image_calls.append(dataset_key)
        return FakeSoilImage(self._band_values)

    def ImageCollection(self, dataset_key: str) -> object:
        raise AssertionError(f"ImageCollection should not be called for soil variables; got {dataset_key!r}")


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _gee_settings(**overrides):
    base = {
        "GEE_ENABLED": "true",
        "GEE_PROJECT": "via-project",
        "GEE_SERVICE_ACCOUNT": "svc@example.com",
        "GEE_PRIVATE_KEY_FILE": "C:/keys/gee.json",
        "GEE_MAX_RETRIES": "0",
    }
    base.update(overrides)
    return load_settings(base)


def _polygon() -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [[-76.005, -12.005], [-76.005, -12.000], [-76.000, -12.000], [-76.000, -12.005], [-76.005, -12.005]]
        ],
    }


def _soil_request(variable_name: str) -> ExtractionRequest:
    return ExtractionRequest(
        parcel_id=uuid4(),
        parcel_geometry=_polygon(),
        temporal_window={"start": "2025-01-01", "end": "2026-01-01"},
        variable_name=variable_name,
        criterion_id="test",
        crop_id="test_crop",
        phase_id="test_phase",
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
        period_key="static",
        period_start="2025-01-01",
        period_end="2026-01-01",
    )


# ─── Registry: SOIL_STATIC recognition ───────────────────────────────────────


@pytest.mark.parametrize("name", _ALL_SOIL_VARS)
def test_soil_variable_is_registered(name: str) -> None:
    assert get_variable_definition(name) is not None


@pytest.mark.parametrize("name", _ALL_SOIL_VARS)
def test_soil_variable_type_is_soil_static(name: str) -> None:
    defn = get_variable_definition(name)
    assert defn is not None
    assert defn.variable_type == GeeVariableType.SOIL_STATIC


@pytest.mark.parametrize("name", _ALL_SOIL_VARS)
def test_soil_variable_category_is_soil(name: str) -> None:
    defn = get_variable_definition(name)
    assert defn is not None
    assert defn.category == "soil"


@pytest.mark.parametrize("name", _ALL_SOIL_VARS)
def test_soil_variable_uses_centroid_sample(name: str) -> None:
    defn = get_variable_definition(name)
    assert defn is not None
    assert defn.spatial_sampling_strategy == "centroid_sample", (
        f"{name}: expected centroid_sample, got {defn.spatial_sampling_strategy!r}"
    )


@pytest.mark.parametrize("name", _ALL_SOIL_VARS)
def test_soil_variable_scale_is_250m(name: str) -> None:
    defn = get_variable_definition(name)
    assert defn is not None
    assert defn.default_scale == 250.0


# ─── Registry: Dataset keys ───────────────────────────────────────────────────


def test_ph_suelo_dataset_key() -> None:
    defn = get_variable_definition("ph_suelo")
    assert defn is not None
    assert defn.dataset_key == _OLM_PH


def test_arcilla_pct_dataset_key() -> None:
    defn = get_variable_definition("arcilla_pct")
    assert defn is not None
    assert defn.dataset_key == _OLM_CLAY


def test_arena_pct_dataset_key() -> None:
    defn = get_variable_definition("arena_pct")
    assert defn is not None
    assert defn.dataset_key == _OLM_SAND


def test_carbono_organico_dataset_key() -> None:
    defn = get_variable_definition("carbono_organico_suelo")
    assert defn is not None
    assert defn.dataset_key == _OLM_OC


def test_textura_suelo_dataset_key() -> None:
    defn = get_variable_definition("textura_suelo_clase")
    assert defn is not None
    assert defn.dataset_key == _OLM_TEX


# ─── Registry: depth_strategy ─────────────────────────────────────────────────


@pytest.mark.parametrize("name", _TOPSOIL_VARS)
def test_topsoil_variable_uses_topsoil_0_30cm_mean_strategy(name: str) -> None:
    defn = get_variable_definition(name)
    assert defn is not None
    assert defn.depth_strategy == "topsoil_0_30cm_mean"


def test_textura_uses_surface_0cm_strategy() -> None:
    defn = get_variable_definition("textura_suelo_clase")
    assert defn is not None
    assert defn.depth_strategy == "surface_0cm"


@pytest.mark.parametrize("name", _TOPSOIL_VARS)
def test_topsoil_variable_has_three_source_bands(name: str) -> None:
    defn = get_variable_definition(name)
    assert defn is not None
    assert len(defn.source_bands) == 3
    assert "b0" in defn.source_bands
    assert "b10" in defn.source_bands
    assert "b30" in defn.source_bands


def test_textura_has_single_source_band_b0() -> None:
    defn = get_variable_definition("textura_suelo_clase")
    assert defn is not None
    assert defn.source_bands == ("b0",)


# ─── Registry: scale factors ──────────────────────────────────────────────────


@pytest.mark.parametrize("name", ("ph_suelo", "arcilla_pct", "arena_pct"))
def test_ph_clay_sand_scale_factor_is_0_1(name: str) -> None:
    defn = get_variable_definition(name)
    assert defn is not None
    assert defn.scale_factor == pytest.approx(0.1)


def test_carbono_organico_scale_factor_is_0_2() -> None:
    defn = get_variable_definition("carbono_organico_suelo")
    assert defn is not None
    assert defn.scale_factor == pytest.approx(0.2)


def test_textura_scale_factor_is_none() -> None:
    defn = get_variable_definition("textura_suelo_clase")
    assert defn is not None
    assert defn.scale_factor is None


# ─── Registry: result_band equals variable_name ───────────────────────────────


@pytest.mark.parametrize("name", _ALL_SOIL_VARS)
def test_soil_result_band_equals_variable_name(name: str) -> None:
    defn = get_variable_definition(name)
    assert defn is not None
    assert defn.result_band == name, (
        f"{name}: result_band should equal variable_name for predictable reduceRegion key"
    )


# ─── Registry: category listing ───────────────────────────────────────────────


def test_soil_category_returns_five_variables() -> None:
    soil_names = list_variable_names_by_category("soil")
    assert len(soil_names) == 5
    assert set(soil_names) == set(_ALL_SOIL_VARS)


# ─── Client: _extract_soil — direct function tests ────────────────────────────


def _make_ph_defn():
    return get_variable_definition("ph_suelo")


def _make_tex_defn():
    return get_variable_definition("textura_suelo_clase")


def _make_oc_defn():
    return get_variable_definition("carbono_organico_suelo")


def test_extract_soil_topsoil_averages_three_bands_and_applies_scale() -> None:
    """ph_suelo: raw b0=75, b10=73, b30=71 → mean=73 → ×0.1 = 7.3"""
    fake_ee = FakeSoilEE(band_values={"b0": 75, "b10": 73, "b30": 71})
    defn = _make_ph_defn()
    geometry = ("Point", [-76.0, -12.0])
    reducer = "mean"

    result = _extract_soil(fake_ee, defn, geometry, reducer, 250.0)

    assert result == pytest.approx((75 + 73 + 71) / 3 * 0.1, abs=1e-9)


def test_extract_soil_topsoil_ph_known_values() -> None:
    """Lima costera estimate: pH raw ~75 → 7.5 real pH units."""
    fake_ee = FakeSoilEE(band_values={"b0": 75, "b10": 75, "b30": 75})
    defn = _make_ph_defn()

    result = _extract_soil(fake_ee, defn, "geom", "mean", 250.0)

    assert result == pytest.approx(7.5)


def test_extract_soil_oc_scale_factor_0_2() -> None:
    """OC: raw stored as ×5 g/kg; scale_factor=0.2 (÷5) gives real g/kg."""
    fake_ee = FakeSoilEE(band_values={"b0": 20, "b10": 20, "b30": 20})
    defn = _make_oc_defn()

    result = _extract_soil(fake_ee, defn, "geom", "mean", 250.0)

    assert result == pytest.approx(4.0)


def test_extract_soil_surface_0cm_uses_only_b0() -> None:
    """textura_suelo_clase (surface_0cm): only b0=7 should be used; b10/b30 ignored."""
    fake_ee = FakeSoilEE(band_values={"b0": 7, "b10": 99, "b30": 99})
    defn = _make_tex_defn()

    result = _extract_soil(fake_ee, defn, "geom", "mean", 250.0)

    assert result == 7


def test_extract_soil_texture_no_scale_factor_passes_raw() -> None:
    """textura_suelo_clase: scale_factor=None → integer class returned as-is."""
    fake_ee = FakeSoilEE(band_values={"b0": 5})
    defn = _make_tex_defn()

    result = _extract_soil(fake_ee, defn, "geom", "mean", 250.0)

    assert result == 5


def test_extract_soil_missing_value_returns_none() -> None:
    """When GEE returns None (no data), _extract_soil returns None."""
    fake_ee = FakeSoilEE(band_values={"b0": None, "b10": None, "b30": None})
    defn = _make_ph_defn()

    result = _extract_soil(fake_ee, defn, "geom", "mean", 250.0)

    assert result is None


def test_extract_soil_calls_ee_image_with_correct_dataset_key() -> None:
    fake_ee = FakeSoilEE(band_values={"b0": 70, "b10": 70, "b30": 70})
    defn = _make_ph_defn()

    _extract_soil(fake_ee, defn, "geom", "mean", 250.0)

    assert len(fake_ee.image_calls) == 1
    assert fake_ee.image_calls[0] == _OLM_PH


def test_extract_soil_invalid_depth_strategy_raises() -> None:
    """An unsupported depth_strategy must raise GeeExtractionError."""
    import dataclasses

    defn = get_variable_definition("ph_suelo")
    assert defn is not None
    bad_defn = dataclasses.replace(defn, depth_strategy="unknown_strategy")
    fake_ee = FakeSoilEE(band_values={"b0": 70})

    with pytest.raises(GeeExtractionError, match="unsupported depth_strategy"):
        _extract_soil(fake_ee, bad_defn, "geom", "mean", 250.0)


# ─── Client: dispatch routing (SOIL_STATIC does not call ImageCollection) ─────


def test_soil_client_does_not_call_image_collection() -> None:
    """SOIL_STATIC dispatch uses ee.Image, not ee.ImageCollection."""
    fake_ee = FakeSoilEE(band_values={"b0": 75, "b10": 75, "b30": 75})
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(_soil_request("ph_suelo"))

    assert result is not None
    assert result.value == pytest.approx(7.5)
    # Image was called; ImageCollection was never called
    assert fake_ee.image_calls == [_OLM_PH]


def test_soil_client_uses_centroid_sample() -> None:
    """For centroid_sample, ee.Geometry.Point must be called with the polygon centroid."""
    fake_ee = FakeSoilEE(band_values={"b0": 75, "b10": 75, "b30": 75})
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(_soil_request("ph_suelo"))

    assert len(fake_ee.Geometry.point_calls) == 1, (
        "centroid_sample should call ee.Geometry.Point exactly once"
    )


def test_soil_client_texture_returns_integer_class() -> None:
    """textura_suelo_clase has no scale_factor; client returns the raw integer class."""
    fake_ee = FakeSoilEE(band_values={"b0": 7})
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)
    request = _soil_request("textura_suelo_clase")

    result = client.extract_variable(request)

    assert result is not None
    assert result.value == 7


def test_soil_client_missing_returns_none_when_fallback_allowed() -> None:
    fake_ee = FakeSoilEE(band_values={"b0": None, "b10": None, "b30": None})
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(_soil_request("ph_suelo"))

    assert result is None


# ─── Seed coherence: AHP weights ──────────────────────────────────────────────


def test_ahp_weights_sum_to_one() -> None:
    total = sum(_AHP_WEIGHTS.values())
    assert total == pytest.approx(1.0, abs=1e-9), (
        f"AHP weights sum to {total}, expected 1.0"
    )


def test_ahp_weights_has_twelve_criteria() -> None:
    assert len(_AHP_WEIGHTS) == 12


def test_soil_criteria_group_sums_to_0_27() -> None:
    soil_keys = {"reaccion_suelo_ph", "contenido_arcilla", "contenido_arena", "carbono_organico_suelo"}
    soil_total = sum(_AHP_WEIGHTS[k] for k in soil_keys)
    assert soil_total == pytest.approx(0.27, abs=1e-9)


def test_climate_criteria_group_sums_to_0_48() -> None:
    climate_keys = {"aptitud_termica", "riesgo_frio", "riesgo_calor", "disponibilidad_hidrica", "deficit_hidrico"}
    climate_total = sum(_AHP_WEIGHTS[k] for k in climate_keys)
    assert climate_total == pytest.approx(0.48, abs=1e-9)


def test_topo_criteria_group_sums_to_0_20() -> None:
    topo_keys = {"aptitud_altitudinal", "aptitud_topografica"}
    topo_total = sum(_AHP_WEIGHTS[k] for k in topo_keys)
    assert topo_total == pytest.approx(0.20, abs=1e-9)


def test_ndvi_auxiliary_weight_is_0_05() -> None:
    assert _AHP_WEIGHTS["cobertura_actual_auxiliar"] == pytest.approx(0.05)


def test_reaccion_suelo_ph_weight_is_0_10() -> None:
    assert _AHP_WEIGHTS["reaccion_suelo_ph"] == pytest.approx(0.10)


def test_carbono_organico_weight_is_0_04() -> None:
    assert _AHP_WEIGHTS["carbono_organico_suelo"] == pytest.approx(0.04)


# ─── Seed coherence: criteria list ───────────────────────────────────────────


def test_seed_criteria_has_twelve_items() -> None:
    assert len(_CRITERIA) == 12


def test_soil_criteria_present_in_criteria_tuple() -> None:
    criteria_set = set(_CRITERIA)
    for soil_criterion in ("reaccion_suelo_ph", "contenido_arcilla", "contenido_arena", "carbono_organico_suelo"):
        assert soil_criterion in criteria_set, f"{soil_criterion!r} missing from _CRITERIA"


def test_textura_suelo_clase_is_not_a_seed_criterion() -> None:
    """textura_suelo_clase is categorical (integer 1–12); not eligible for trapezoidal membership."""
    assert "textura_suelo_clase" not in _CRITERIA


def test_ndvi_is_a_seed_criterion_as_auxiliary() -> None:
    assert "cobertura_actual_auxiliar" in _CRITERIA


# ─── Seed coherence: _SOIL_CRITERIA set ──────────────────────────────────────


def test_soil_criteria_frozenset_has_four_items() -> None:
    assert len(_SOIL_CRITERIA) == 4


def test_soil_criteria_frozenset_content() -> None:
    assert _SOIL_CRITERIA == frozenset({
        "reaccion_suelo_ph",
        "contenido_arcilla",
        "contenido_arena",
        "carbono_organico_suelo",
    })


def test_textura_not_in_soil_criteria_frozenset() -> None:
    assert "textura_suelo_clase" not in _SOIL_CRITERIA


# ─── Data sufficiency policy (weight threshold arithmetic) ────────────────────


def test_soil_all_missing_weight_below_threshold() -> None:
    """Soil all missing = 0.27 < 0.30 → should not alone trigger NO_CONCLUYENTE."""
    soil_weight = sum(
        _AHP_WEIGHTS.get(criterion, 0.0)
        for criterion in (
            "reaccion_suelo_ph", "contenido_arcilla", "contenido_arena", "carbono_organico_suelo"
        )
    )
    assert soil_weight == pytest.approx(0.27)
    assert soil_weight < 0.30, (
        "Soil-only missing weight must be < 0.30 threshold so system stays PARCIAL, not NO_CONCLUYENTE"
    )


def test_soil_plus_riesgo_frio_missing_exceeds_threshold() -> None:
    """Soil (0.27) + riesgo_frio (0.07) missing = 0.34 ≥ 0.30 → NO_CONCLUYENTE territory."""
    soil_weight = 0.27
    riesgo_frio_weight = _AHP_WEIGHTS["riesgo_frio"]
    combined = soil_weight + riesgo_frio_weight
    assert combined >= 0.30, (
        f"Combined missing weight {combined} should trigger NO_CONCLUYENTE (≥0.30)"
    )


def test_ph_only_missing_weight_below_threshold() -> None:
    """Only pH missing (0.10) < 0.30 → PARCIAL."""
    assert _AHP_WEIGHTS["reaccion_suelo_ph"] < 0.30


def test_carbono_only_missing_weight_well_below_threshold() -> None:
    """Only OC missing (0.04) << 0.30 — smallest soil weight, easily tolerated."""
    assert _AHP_WEIGHTS["carbono_organico_suelo"] < 0.30
    assert _AHP_WEIGHTS["carbono_organico_suelo"] == pytest.approx(0.04)
