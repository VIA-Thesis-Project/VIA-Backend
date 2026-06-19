"""Unit tests for the multi-variable dispatch in GeeExtractionClient."""

from __future__ import annotations

from uuid import uuid4

import pytest

from via.bounded_contexts.agroenv_extraction.application.ports import ExtractionRequest
from via.bounded_contexts.agroenv_extraction.infrastructure.gee_client import (
    SAVI_L,
    GeeExtractionClient,
    GeeExtractionError,
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


def _polygon() -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [[-76.0, -12.0], [-76.0, -12.01], [-75.99, -12.01], [-75.99, -12.0], [-76.0, -12.0]]
        ],
    }


def _request(variable_name: str, band: str, dataset_key: str, scale: float = 10.0) -> ExtractionRequest:
    return ExtractionRequest(
        parcel_id=uuid4(),
        parcel_geometry={"type": "MultiPolygon", "coordinates": [_polygon()["coordinates"]]},
        temporal_window={"start": "2026-01-01", "end": "2026-01-31"},
        variable_name=variable_name,
        criterion_id="test_criterion",
        crop_id="test_crop",
        phase_id="test_phase",
        dataset_key=dataset_key,
        band=band,
        unit="index",
        temporal_resolution="monthly",
        spatial_resolution=None,
        scale=scale,
        reducer="mean",
        aggregation_method="mean",
        quality_mask=None,
        fallback_allowed=True,
        period_key="2026-01",
        period_start="2026-01-01",
        period_end="2026-01-31",
    )


# ─── SAVI_L constant ──────────────────────────────────────────────────────────


def test_savi_l_constant_is_zero_point_five() -> None:
    assert SAVI_L == 0.5


# ─── NDVI: DERIVED_INDEX dispatch ────────────────────────────────────────────


def test_ndvi_extracts_using_normalized_difference() -> None:
    fake_ee = FakeEeModule(value=0.65)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(
        _request("ndvi", band="ndvi", dataset_key="COPERNICUS/S2_SR_HARMONIZED")
    )

    assert result is not None
    assert result.value == 0.65
    assert len(fake_ee.collections) == 1
    assert fake_ee.collections[0].dataset_key == "COPERNICUS/S2_SR_HARMONIZED"
    assert fake_ee.collections[0].image.normalized_difference_called is True
    assert fake_ee.collections[0].image.renamed_band == "ndvi"


def test_ndvi_selects_source_bands_b8_and_b4() -> None:
    fake_ee = FakeEeModule(value=0.40)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(
        _request("ndvi", band="ndvi", dataset_key="COPERNICUS/S2_SR_HARMONIZED")
    )

    selected = fake_ee.collections[0].selected_bands
    assert "B8" in selected
    assert "B4" in selected


# ─── SAVI: DERIVED_INDEX dispatch ─────────────────────────────────────────────


def test_savi_extracts_using_expression() -> None:
    fake_ee = FakeEeModule(value=0.28)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(
        _request("savi", band="savi", dataset_key="COPERNICUS/S2_SR_HARMONIZED")
    )

    assert result is not None
    assert result.value == 0.28
    assert fake_ee.collections[0].image.expression_called is True
    assert fake_ee.collections[0].image.renamed_band == "savi"


def test_savi_expression_contains_l_factor() -> None:
    fake_ee = FakeEeModule(value=0.28)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(
        _request("savi", band="savi", dataset_key="COPERNICUS/S2_SR_HARMONIZED")
    )

    expr = fake_ee.collections[0].image.last_expression
    assert expr is not None
    assert str(SAVI_L) in expr, f"SAVI expression should contain L={SAVI_L}; got: {expr!r}"


def test_savi_source_image_contains_result_of_expression() -> None:
    fake_ee = FakeEeModule(value=0.30)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(
        _request("savi", band="savi", dataset_key="COPERNICUS/S2_SR_HARMONIZED")
    )

    assert fake_ee.collections[0].image.renamed_band == "savi"


# ─── NDMI: DERIVED_INDEX dispatch ─────────────────────────────────────────────


def test_ndmi_extracts_using_normalized_difference_b8_b11() -> None:
    fake_ee = FakeEeModule(value=0.12)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(
        _request("ndmi", band="ndmi", dataset_key="COPERNICUS/S2_SR_HARMONIZED", scale=20.0)
    )

    assert result is not None
    assert result.value == 0.12
    assert fake_ee.collections[0].image.normalized_difference_called is True
    assert fake_ee.collections[0].image.renamed_band == "ndmi"


def test_ndmi_selects_source_bands_b8_and_b11() -> None:
    fake_ee = FakeEeModule(value=0.10)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(
        _request("ndmi", band="ndmi", dataset_key="COPERNICUS/S2_SR_HARMONIZED", scale=20.0)
    )

    selected = fake_ee.collections[0].selected_bands
    assert "B8" in selected
    assert "B11" in selected


# ─── elevacion_m: TOPO_STATIC dispatch ───────────────────────────────────────


def test_elevacion_extracts_from_static_image_without_date_filter() -> None:
    fake_ee = FakeEeModule(value=210.0)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(
        _request("elevacion_m", band="elevation", dataset_key="USGS/SRTMGL1_003", scale=30.0)
    )

    assert result is not None
    assert result.value == 210.0
    assert len(fake_ee.static_images) == 1
    assert fake_ee.static_images[0].dataset_key == "USGS/SRTMGL1_003"
    assert fake_ee.static_images[0].selected_band == "elevation"
    assert not fake_ee.collections, "TOPO_STATIC must not call ee.ImageCollection"


def test_elevacion_source_string_includes_band_name() -> None:
    fake_ee = FakeEeModule(value=180.0)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(
        _request("elevacion_m", band="elevation", dataset_key="USGS/SRTMGL1_003", scale=30.0)
    )

    assert result is not None
    assert result.source == "GEE:USGS/SRTMGL1_003:elevation:polygon_mean:scale=30"


# ─── pendiente_grados: TOPO_DERIVED dispatch ─────────────────────────────────


def test_pendiente_extracts_using_terrain_slope() -> None:
    fake_ee = FakeEeModule(value=9.8)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(
        _request("pendiente_grados", band="slope", dataset_key="USGS/SRTMGL1_003", scale=30.0)
    )

    assert result is not None
    assert result.value == 9.8
    assert fake_ee.terrain_slope_calls == 1
    assert not fake_ee.collections, "TOPO_DERIVED must not call ee.ImageCollection"


def test_pendiente_source_string_includes_slope_band() -> None:
    fake_ee = FakeEeModule(value=11.2)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(
        _request("pendiente_grados", band="slope", dataset_key="USGS/SRTMGL1_003", scale=30.0)
    )

    assert result is not None
    assert result.source == "GEE:USGS/SRTMGL1_003:slope:polygon_mean:scale=30"


# ─── Unknown variable falls back to SIMPLE_BAND ───────────────────────────────


def test_unknown_variable_name_falls_back_to_simple_band_path() -> None:
    fake_ee = FakeEeModule(value=0.88)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(
        _request("custom_variable_xyz", band="B12", dataset_key="some/dataset")
    )

    assert result is not None
    assert result.value == 0.88
    assert len(fake_ee.collections) == 1
    assert fake_ee.collections[0].dataset_key == "some/dataset"
    assert fake_ee.collections[0].selected_band == "B12"


# ─── Dispatch does not call ImageCollection for topo variables ────────────────


@pytest.mark.parametrize("variable_name,band", [("elevacion_m", "elevation"), ("pendiente_grados", "slope")])
def test_topographic_variables_do_not_call_image_collection(variable_name: str, band: str) -> None:
    fake_ee = FakeEeModule(value=100.0)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(
        _request(variable_name, band=band, dataset_key="USGS/SRTMGL1_003", scale=30.0)
    )

    assert not fake_ee.collections, f"{variable_name} must not call ee.ImageCollection"


# ─── Extended FakeEeModule ────────────────────────────────────────────────────


class FakeEeModule:
    """Extended Earth Engine fake supporting ImageCollection, Image, and Terrain."""

    def __init__(self, value: float | None = 1.0) -> None:
        self.value = value
        self.collections: list[FakeImageCollection] = []
        self.static_images: list[FakeStaticImage] = []
        self.terrain_slope_calls = 0
        self.credentials_calls: list = []
        self.initialize_calls: list = []
        self.deadline_calls: list = []
        self.geometry_calls: list = []
        self.reducer_calls: list = []
        self.Geometry = FakeGeometry(self)
        self.Reducer = FakeReducer(self)
        self.data = FakeData(self)
        self.Terrain = FakeTerrain(self)

    def ServiceAccountCredentials(self, service_account, private_key_file) -> str:
        self.credentials_calls.append((service_account, private_key_file))
        return "credentials"

    def Initialize(self, credentials, project=None) -> None:
        self.initialize_calls.append((credentials, project))

    def ImageCollection(self, dataset_key: str) -> "FakeImageCollection":
        collection = FakeImageCollection(self, dataset_key)
        self.collections.append(collection)
        return collection

    def Image(self, dataset_key: str) -> "FakeStaticImage":
        img = FakeStaticImage(self, dataset_key)
        self.static_images.append(img)
        return img


class FakeTerrain:
    def __init__(self, ee: FakeEeModule) -> None:
        self._ee = ee

    def slope(self, image: object) -> "FakeTopoImage":
        self._ee.terrain_slope_calls += 1
        return FakeTopoImage(self._ee)


class FakeData:
    def __init__(self, ee: FakeEeModule) -> None:
        self._ee = ee

    def setDeadline(self, milliseconds: int) -> None:
        self._ee.deadline_calls.append(milliseconds)


class FakeGeometry:
    def __init__(self, ee: FakeEeModule) -> None:
        self._ee = ee

    def Polygon(self, coordinates: object) -> tuple:
        self._ee.geometry_calls.append(("Polygon", coordinates))
        return ("Polygon", coordinates)

    def MultiPolygon(self, coordinates: object) -> tuple:
        self._ee.geometry_calls.append(("MultiPolygon", coordinates))
        return ("MultiPolygon", coordinates)

    def Point(self, lon_lat: list) -> tuple:
        self._ee.geometry_calls.append(("Point", lon_lat))
        return ("Point", lon_lat)


class FakeReducer:
    def __init__(self, ee: FakeEeModule) -> None:
        self._ee = ee

    def mean(self) -> str:
        self._ee.reducer_calls.append("mean")
        return "mean"

    def median(self) -> str:
        self._ee.reducer_calls.append("median")
        return "median"

    def min(self) -> str:
        self._ee.reducer_calls.append("min")
        return "min"

    def max(self) -> str:
        self._ee.reducer_calls.append("max")
        return "max"


class FakeImageCollection:
    """Fake ImageCollection supporting multi-band selection and index computation."""

    def __init__(self, ee: FakeEeModule, dataset_key: str) -> None:
        self._ee = ee
        self.dataset_key = dataset_key
        self.date_filter: tuple | None = None
        self.selected_bands: list[str] = []
        self.selected_band: str | None = None
        self.map_called = False
        self.image = FakeComputedImage(ee)

    def filterDate(self, start: str, end: str) -> "FakeImageCollection":
        self.date_filter = (start, end)
        return self

    def select(self, bands) -> "FakeImageCollection":
        if isinstance(bands, list):
            self.selected_bands = bands
            self.selected_band = bands[0] if bands else None
        else:
            self.selected_band = bands
            self.selected_bands = [bands]
        return self

    def map(self, func):
        self.map_called = True
        return self

    def mean(self) -> "FakeComputedImage":
        self.image.reducer_method = "mean"
        return self.image

    def median(self) -> "FakeComputedImage":
        self.image.reducer_method = "median"
        return self.image

    def min(self) -> "FakeComputedImage":
        self.image.reducer_method = "min"
        return self.image

    def max(self) -> "FakeComputedImage":
        self.image.reducer_method = "max"
        return self.image


class FakeComputedImage:
    """Fake image that supports normalizedDifference, expression, rename, and reduceRegion."""

    def __init__(self, ee: FakeEeModule) -> None:
        self._ee = ee
        self.reducer_method: str | None = None
        self.normalized_difference_called = False
        self.expression_called = False
        self.last_expression: str | None = None
        self.renamed_band: str | None = None

    def normalizedDifference(self, bands: list[str]) -> "FakeComputedImage":
        self.normalized_difference_called = True
        return self

    def expression(self, expr: str, band_map: dict) -> "FakeComputedImage":
        self.expression_called = True
        self.last_expression = expr
        return self

    def rename(self, name: str) -> "FakeComputedImage":
        self.renamed_band = name
        return self

    def select(self, band: str) -> "FakeComputedImage":
        return self

    def reduceRegion(self, **kwargs) -> "FakeRegion":
        return FakeRegion(self._ee.value)


class FakeStaticImage:
    """Fake ee.Image for topographic static datasets."""

    def __init__(self, ee: FakeEeModule, dataset_key: str) -> None:
        self._ee = ee
        self.dataset_key = dataset_key
        self.selected_band: str | None = None

    def select(self, band: str) -> "FakeStaticImage":
        self.selected_band = band
        return self

    def reduceRegion(self, **kwargs) -> "FakeRegion":
        return FakeRegion(self._ee.value)


class FakeTopoImage:
    """Fake slope image returned by ee.Terrain.slope()."""

    def __init__(self, ee: FakeEeModule) -> None:
        self._ee = ee

    def reduceRegion(self, **kwargs) -> "FakeRegion":
        return FakeRegion(self._ee.value)


class FakeRegion:
    def __init__(self, value: float | None) -> None:
        self._value = value

    def get(self, band: str) -> "FakeValue":
        return FakeValue(self._value)


class FakeValue:
    def __init__(self, value: float | None) -> None:
        self._value = value

    def getInfo(self) -> float | None:
        return self._value
