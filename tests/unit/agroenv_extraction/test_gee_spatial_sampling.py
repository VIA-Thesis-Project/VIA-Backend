"""Tests for spatial_sampling_strategy in the GEE variable registry and centroid extraction.

Objectives covered:
    - Objetivo 1: Registry declares centroid_sample for coarse climate datasets
    - Objetivo 1: Sentinel-2 and SRTM keep polygon_mean
    - Objetivo 2: Source string records strategy and scale
    - Client helper: centroid geometry computed correctly for Polygon and MultiPolygon
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from via.bounded_contexts.agroenv_extraction.application.ports import ExtractionRequest
from via.bounded_contexts.agroenv_extraction.infrastructure.gee_client import (
    GeeExtractionClient,
    GeeExtractionError,
    _centroid_geometry,
    _ring_centroid,
    _sampling_geometry,
)
from via.bounded_contexts.agroenv_extraction.infrastructure.gee_variable_registry import (
    get_variable_definition,
    list_variable_names_by_category,
)
from via.config import load_settings


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _gee_settings():
    return load_settings(
        {
            "GEE_ENABLED": "true",
            "GEE_PROJECT": "via-project",
            "GEE_SERVICE_ACCOUNT": "svc@example.com",
            "GEE_PRIVATE_KEY_FILE": "C:/keys/gee.json",
            "GEE_MAX_RETRIES": "0",
        }
    )


def _polygon_small() -> dict:
    """Polygon smaller than an ERA5 pixel (~11 km) — coordinates for a ~1 km parcel."""
    return {
        "type": "Polygon",
        "coordinates": [
            [[-76.005, -12.005], [-76.005, -12.000], [-76.000, -12.000], [-76.000, -12.005], [-76.005, -12.005]]
        ],
    }


def _multipolygon() -> dict:
    return {
        "type": "MultiPolygon",
        "coordinates": [_polygon_small()["coordinates"]],
    }


def _request(variable_name: str, band: str, dataset_key: str, scale: float) -> ExtractionRequest:
    return ExtractionRequest(
        parcel_id=uuid4(),
        parcel_geometry=_polygon_small(),
        temporal_window={"start": "2025-01-01", "end": "2026-01-01"},
        variable_name=variable_name,
        criterion_id="test",
        crop_id="test_crop",
        phase_id="test_phase",
        dataset_key=dataset_key,
        band=band,
        unit="celsius",
        temporal_resolution="monthly",
        spatial_resolution=None,
        scale=scale,
        reducer="mean",
        aggregation_method="mean",
        quality_mask=None,
        fallback_allowed=True,
        period_key="annual",
        period_start="2025-01-01",
        period_end="2026-01-01",
    )


# ─── Registry: spatial_sampling_strategy ──────────────────────────────────────


def test_climate_variables_use_centroid_sample_strategy() -> None:
    climate_vars = list_variable_names_by_category("climate")
    # CLIMATE_SIMPLE variables (not derived) must use centroid_sample
    simple_climate = [
        name for name in climate_vars
        if get_variable_definition(name) and get_variable_definition(name).derived_from is None
    ]
    assert simple_climate, "Expected at least one CLIMATE_SIMPLE variable"
    for name in simple_climate:
        defn = get_variable_definition(name)
        assert defn.spatial_sampling_strategy == "centroid_sample", (
            f"{name} should use centroid_sample, got {defn.spatial_sampling_strategy!r}"
        )


def test_sentinel2_variables_use_polygon_mean_strategy() -> None:
    sentinel_vars = list_variable_names_by_category("remote_sensing")
    for name in sentinel_vars:
        defn = get_variable_definition(name)
        assert defn.spatial_sampling_strategy == "polygon_mean", (
            f"Sentinel-2 variable {name!r} should use polygon_mean"
        )


def test_srtm_variables_use_polygon_mean_strategy() -> None:
    topo_vars = list_variable_names_by_category("topographic")
    for name in topo_vars:
        defn = get_variable_definition(name)
        assert defn.spatial_sampling_strategy == "polygon_mean", (
            f"SRTM variable {name!r} should use polygon_mean"
        )


def test_era5_temperature_variables_have_centroid_strategy() -> None:
    for name in ("temperatura_media_c", "temperatura_minima_c", "temperatura_maxima_c"):
        defn = get_variable_definition(name)
        assert defn is not None
        assert defn.spatial_sampling_strategy == "centroid_sample"


def test_chirps_precipitation_has_centroid_strategy() -> None:
    defn = get_variable_definition("precipitacion_acumulada_mm")
    assert defn is not None
    assert defn.spatial_sampling_strategy == "centroid_sample"


def test_era5_pet_has_centroid_strategy() -> None:
    defn = get_variable_definition("evapotranspiracion_referencia_mm")
    assert defn is not None
    assert defn.spatial_sampling_strategy == "centroid_sample"


# ─── _ring_centroid helper ─────────────────────────────────────────────────────


def test_ring_centroid_computes_mean_of_vertices() -> None:
    ring = [[-76.0, -12.0], [-76.0, -12.1], [-75.9, -12.1], [-75.9, -12.0], [-76.0, -12.0]]
    lon, lat = _ring_centroid(ring)
    assert lon == pytest.approx(-75.95, abs=1e-6)
    assert lat == pytest.approx(-12.05, abs=1e-6)


def test_ring_centroid_skips_duplicate_closing_vertex() -> None:
    ring = [[-76.0, -12.0], [-74.0, -12.0], [-75.0, -10.0], [-76.0, -12.0]]
    # Only 3 unique points: (-76,-12), (-74,-12), (-75,-10)
    lon, lat = _ring_centroid(ring)
    assert lon == pytest.approx((-76.0 + -74.0 + -75.0) / 3, abs=1e-6)
    assert lat == pytest.approx((-12.0 + -12.0 + -10.0) / 3, abs=1e-6)


def test_ring_centroid_raises_on_empty_ring() -> None:
    with pytest.raises(GeeExtractionError, match="Empty ring"):
        _ring_centroid([])


# ─── _centroid_geometry helper ─────────────────────────────────────────────────


class _FakeEe:
    class Geometry:
        @staticmethod
        def Point(lon_lat: list) -> tuple:
            return ("Point", lon_lat)

        @staticmethod
        def Polygon(c): return ("Polygon", c)

        @staticmethod
        def MultiPolygon(c): return ("MultiPolygon", c)


def test_centroid_geometry_returns_point_for_polygon() -> None:
    geometry_dict = {
        "type": "Polygon",
        "coordinates": [
            [[-76.0, -12.0], [-76.0, -12.1], [-75.9, -12.1], [-75.9, -12.0], [-76.0, -12.0]]
        ],
    }
    result = _centroid_geometry(_FakeEe, geometry_dict)
    kind, lon_lat = result
    assert kind == "Point"
    assert len(lon_lat) == 2
    assert lon_lat[0] == pytest.approx(-75.95, abs=1e-3)
    assert lon_lat[1] == pytest.approx(-12.05, abs=1e-3)


def test_centroid_geometry_returns_point_for_multipolygon() -> None:
    geometry_dict = {
        "type": "MultiPolygon",
        "coordinates": [
            [
                [[-76.0, -12.0], [-76.0, -12.1], [-75.9, -12.1], [-75.9, -12.0], [-76.0, -12.0]]
            ]
        ],
    }
    result = _centroid_geometry(_FakeEe, geometry_dict)
    kind, _ = result
    assert kind == "Point"


def test_centroid_geometry_raises_on_unknown_type() -> None:
    with pytest.raises(GeeExtractionError, match="centroid"):
        _centroid_geometry(_FakeEe, {"type": "LineString", "coordinates": []})


def test_centroid_geometry_uses_largest_ring_in_multipolygon() -> None:
    small_ring = [[-70.0, -10.0], [-70.0, -10.01], [-69.99, -10.01], [-69.99, -10.0], [-70.0, -10.0]]
    large_ring = [
        [-76.0, -12.0], [-76.0, -12.2], [-75.8, -12.2],
        [-75.8, -12.1], [-75.9, -12.1], [-75.9, -12.0], [-76.0, -12.0],
    ]
    geometry_dict = {
        "type": "MultiPolygon",
        "coordinates": [[small_ring], [large_ring]],
    }
    result = _centroid_geometry(_FakeEe, geometry_dict)
    kind, lon_lat = result
    assert kind == "Point"
    # centroid should be closer to large_ring's center, not small_ring's
    assert -76.0 < lon_lat[0] < -75.8


# ─── _sampling_geometry dispatch ──────────────────────────────────────────────


def test_sampling_geometry_polygon_mean_returns_original_geometry() -> None:
    geom_obj = ("Polygon", [[]])
    result = _sampling_geometry(_FakeEe, geom_obj, _polygon_small(), "polygon_mean")
    assert result is geom_obj


def test_sampling_geometry_centroid_sample_returns_point() -> None:
    geom_obj = ("Polygon", [[]])
    result = _sampling_geometry(_FakeEe, geom_obj, _polygon_small(), "centroid_sample")
    kind, _ = result
    assert kind == "Point"


# ─── GEE client: centroid used for climate, polygon for Sentinel-2/SRTM ────────


class FakeEeWithGeomTracking:
    """Tracks which geometry type is passed to reduceRegion for each extraction."""

    def __init__(self, value: float = 1.0) -> None:
        self.value = value
        self.collections: list = []
        self.static_images: list = []
        self.terrain_slope_calls = 0
        self.credentials_calls: list = []
        self.initialize_calls: list = []
        self.deadline_calls: list = []
        self.geometry_calls: list = []
        self.reduce_region_geometries: list = []
        self.reducer_calls: list = []
        self.Geometry = _FakeGeometryTracking(self)
        self.Reducer = _FakeReducer(self)
        self.data = _FakeData(self)
        self.Terrain = _FakeTerrain(self)

    def ServiceAccountCredentials(self, sa, pk): return "creds"
    def Initialize(self, creds, project=None): self.initialize_calls.append((creds, project))

    def ImageCollection(self, dataset_key: str) -> "_FakeCollection":
        col = _FakeCollection(self, dataset_key)
        self.collections.append(col)
        return col

    def Image(self, dataset_key: str) -> "_FakeStaticImg":
        img = _FakeStaticImg(self, dataset_key)
        self.static_images.append(img)
        return img


class _FakeGeometryTracking:
    def __init__(self, ee: FakeEeWithGeomTracking) -> None:
        self._ee = ee
        self.point_calls: list = []

    def Polygon(self, c): return ("Polygon", c)
    def MultiPolygon(self, c): return ("MultiPolygon", c)

    def Point(self, lon_lat: list) -> tuple:
        self.point_calls.append(lon_lat)
        return ("Point", lon_lat)


class _FakeReducer:
    def __init__(self, ee): self._ee = ee
    def mean(self): return "mean"


class _FakeData:
    def __init__(self, ee): pass
    def setDeadline(self, ms): pass


class _FakeTerrain:
    def __init__(self, ee): self._ee = ee
    def slope(self, image): return _FakeTopoImg(self._ee)


class _FakeCollection:
    def __init__(self, ee, dataset_key):
        self._ee = ee
        self.dataset_key = dataset_key
        self._image = _FakeImg(ee)

    def filterDate(self, *a): return self
    def select(self, *a): return self
    def map(self, fn): return self
    def mean(self): return self._image
    def sum(self): return self._image
    def min(self): return self._image
    def max(self): return self._image


class _FakeImg:
    def __init__(self, ee): self._ee = ee

    def normalizedDifference(self, bands): return self
    def expression(self, expr, band_map): return self
    def rename(self, name): return self
    def select(self, band): return self

    def reduceRegion(self, reducer=None, geometry=None, **kw):
        self._ee.reduce_region_geometries.append(geometry)
        return _FakeRegion(self._ee.value)


class _FakeStaticImg:
    def __init__(self, ee, dataset_key):
        self._ee = ee
        self.dataset_key = dataset_key

    def select(self, band): return self

    def reduceRegion(self, reducer=None, geometry=None, **kw):
        self._ee.reduce_region_geometries.append(geometry)
        return _FakeRegion(self._ee.value)


class _FakeTopoImg:
    def __init__(self, ee): self._ee = ee

    def reduceRegion(self, reducer=None, geometry=None, **kw):
        self._ee.reduce_region_geometries.append(geometry)
        return _FakeRegion(self._ee.value)


class _FakeRegion:
    def __init__(self, value): self._value = value
    def get(self, band): return _FakeVal(self._value)


class _FakeVal:
    def __init__(self, value): self._value = value
    def getInfo(self): return self._value


@pytest.mark.parametrize("variable_name,band,dataset_key,scale", [
    ("temperatura_media_c",          "temperature_2m",           "ECMWF/ERA5_LAND/MONTHLY_AGGR", 11132.0),
    ("temperatura_minima_c",         "temperature_2m_min",       "ECMWF/ERA5_LAND/MONTHLY_AGGR", 11132.0),
    ("temperatura_maxima_c",         "temperature_2m_max",       "ECMWF/ERA5_LAND/MONTHLY_AGGR", 11132.0),
    ("precipitacion_acumulada_mm",   "precipitation",            "UCSB-CHG/CHIRPS/DAILY",        5566.0),
    ("evapotranspiracion_referencia_mm", "potential_evaporation_sum", "ECMWF/ERA5_LAND/MONTHLY_AGGR", 11132.0),
])
def test_climate_variables_use_centroid_geometry_in_reduce_region(
    variable_name: str, band: str, dataset_key: str, scale: float,
) -> None:
    """For coarse-resolution climate datasets the client passes a Point, not a polygon, to reduceRegion."""
    fake_ee = FakeEeWithGeomTracking(value=293.15)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(_request(variable_name, band, dataset_key, scale))

    assert fake_ee.reduce_region_geometries, "reduceRegion must have been called"
    geom = fake_ee.reduce_region_geometries[0]
    assert geom[0] == "Point", (
        f"{variable_name} should sample at a Point centroid, got {geom[0]!r}"
    )


@pytest.mark.parametrize("variable_name,band,dataset_key,scale", [
    ("ndvi",         "ndvi",      "COPERNICUS/S2_SR_HARMONIZED", 10.0),
    ("elevacion_m",  "elevation", "USGS/SRTMGL1_003",            30.0),
    ("pendiente_grados", "slope", "USGS/SRTMGL1_003",            30.0),
])
def test_sentinel2_srtm_use_polygon_geometry_in_reduce_region(
    variable_name: str, band: str, dataset_key: str, scale: float,
) -> None:
    """Fine-resolution datasets (Sentinel-2, SRTM) use the full polygon geometry."""
    fake_ee = FakeEeWithGeomTracking(value=0.5)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(_request(variable_name, band, dataset_key, scale))

    assert fake_ee.reduce_region_geometries, "reduceRegion must have been called"
    geom = fake_ee.reduce_region_geometries[0]
    assert geom[0] in {"Polygon", "MultiPolygon"}, (
        f"{variable_name} should use polygon geometry, got {geom[0]!r}"
    )


def test_era5_small_parcela_centroid_returns_value_not_none() -> None:
    """Simulates a parcel smaller than an ERA5 pixel: centroid sampling always returns a value."""
    fake_ee = FakeEeWithGeomTracking(value=293.15)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(
        _request("temperatura_media_c", "temperature_2m", "ECMWF/ERA5_LAND/MONTHLY_AGGR", 11132.0)
    )

    assert result is not None
    assert result.value == pytest.approx(293.15 - 273.15, abs=1e-3)


def test_source_string_includes_strategy_and_scale_for_climate() -> None:
    """Objetivo 2: trazabilidad del muestreo en el campo source."""
    fake_ee = FakeEeWithGeomTracking(value=293.15)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(
        _request("temperatura_media_c", "temperature_2m", "ECMWF/ERA5_LAND/MONTHLY_AGGR", 11132.0)
    )

    assert result is not None
    assert "centroid_sample" in result.source, (
        f"Source must record sampling strategy; got {result.source!r}"
    )
    assert "scale=11132" in result.source, (
        f"Source must record scale; got {result.source!r}"
    )


def test_source_string_includes_polygon_mean_for_topo() -> None:
    fake_ee = FakeEeWithGeomTracking(value=350.0)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(
        _request("elevacion_m", "elevation", "USGS/SRTMGL1_003", 30.0)
    )

    assert result is not None
    assert "polygon_mean" in result.source
    assert "scale=30" in result.source
