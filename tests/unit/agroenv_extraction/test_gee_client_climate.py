"""Unit tests for GEE climate variable dispatch in GeeExtractionClient.

Covers ERA5-Land (temperature, PET) and CHIRPS (precipitation) extraction,
Kelvin→°C conversion, PET sign normalization, and deficit derivation.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from via.bounded_contexts.agroenv_extraction.application.ports import ExtractionRequest
from via.bounded_contexts.agroenv_extraction.infrastructure.gee_client import (
    GeeExtractionClient,
    GeeExtractionError,
)
from via.config import load_settings

_ERA5 = "ECMWF/ERA5_LAND/MONTHLY_AGGR"
_CHIRPS = "UCSB-CHG/CHIRPS/DAILY"


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _gee_settings(max_retries: int = 0):
    return load_settings(
        {
            "GEE_ENABLED": "true",
            "GEE_PROJECT": "via-project",
            "GEE_SERVICE_ACCOUNT": "svc@example.com",
            "GEE_PRIVATE_KEY_FILE": "C:/keys/gee.json",
            "GEE_MAX_RETRIES": str(max_retries),
        }
    )


def _polygon() -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [[-76.0, -12.0], [-76.0, -12.01], [-75.99, -12.01], [-75.99, -12.0], [-76.0, -12.0]]
        ],
    }


def _climate_request(
    variable_name: str,
    band: str,
    dataset_key: str = _ERA5,
    aggregation_method: str = "mean",
    scale: float = 11132.0,
) -> ExtractionRequest:
    return ExtractionRequest(
        parcel_id=uuid4(),
        parcel_geometry={"type": "MultiPolygon", "coordinates": [_polygon()["coordinates"]]},
        temporal_window={"start": "2023-01-01", "end": "2024-01-01"},
        variable_name=variable_name,
        criterion_id="test_criterion",
        crop_id="test_crop",
        phase_id="test_phase",
        dataset_key=dataset_key,
        band=band,
        unit="celsius",
        temporal_resolution="monthly",
        spatial_resolution=None,
        scale=scale,
        reducer="mean",
        aggregation_method=aggregation_method,
        quality_mask=None,
        fallback_allowed=True,
        period_key="2023-annual",
        period_start="2023-01-01",
        period_end="2024-01-01",
    )


# ─── ERA5-Land temperature: Kelvin → °C conversion ────────────────────────────


def test_temperatura_minima_applies_kelvin_offset() -> None:
    """temperature_2m_min raw=278.15 K → 278.15 + (-273.15) = 5.0°C."""
    fake_ee = FakeEeModule(value=278.15)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(_climate_request("temperatura_minima_c", "temperature_2m_min"))

    assert result is not None
    assert abs(result.value - 5.0) < 1e-6


def test_temperatura_maxima_applies_kelvin_offset() -> None:
    """temperature_2m_max raw=298.15 K → 298.15 - 273.15 = 25.0°C."""
    fake_ee = FakeEeModule(value=298.15)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(_climate_request("temperatura_maxima_c", "temperature_2m_max"))

    assert result is not None
    assert abs(result.value - 25.0) < 1e-6


def test_temperatura_media_applies_kelvin_offset() -> None:
    """temperature_2m raw=292.15 K → 292.15 - 273.15 = 19.0°C."""
    fake_ee = FakeEeModule(value=292.15)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(_climate_request("temperatura_media_c", "temperature_2m"))

    assert result is not None
    assert abs(result.value - 19.0) < 1e-6


def test_temperatura_media_routes_to_climate_simple() -> None:
    """temperatura_media_c is now CLIMATE_SIMPLE (direct ERA5 band, not derived)."""
    fake_ee = FakeEeModule(value=292.15)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(_climate_request("temperatura_media_c", "temperature_2m"))

    assert len(fake_ee.collections) == 1
    assert fake_ee.collections[0].dataset_key == _ERA5


def test_temperatura_media_does_not_use_expression() -> None:
    """temperatura_media_c now comes from temperature_2m band directly — no GEE expression."""
    fake_ee = FakeEeModule(value=292.15)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(_climate_request("temperatura_media_c", "temperature_2m"))

    assert not fake_ee.collections[0].image.expression_called


def test_temperatura_minima_uses_mean_temporal_aggregation() -> None:
    fake_ee = FakeEeModule(value=278.15)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(_climate_request("temperatura_minima_c", "temperature_2m_min"))

    assert fake_ee.collections[0].temporal_reducer_used == "mean"


def test_temperatura_maxima_uses_mean_temporal_aggregation() -> None:
    fake_ee = FakeEeModule(value=298.15)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(_climate_request("temperatura_maxima_c", "temperature_2m_max"))

    assert fake_ee.collections[0].temporal_reducer_used == "mean"


def test_temperatura_media_uses_mean_temporal_aggregation() -> None:
    fake_ee = FakeEeModule(value=292.15)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(_climate_request("temperatura_media_c", "temperature_2m"))

    assert fake_ee.collections[0].temporal_reducer_used == "mean"


def test_temperatura_minima_selects_correct_band() -> None:
    fake_ee = FakeEeModule(value=278.15)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(_climate_request("temperatura_minima_c", "temperature_2m_min"))

    assert "temperature_2m_min" in fake_ee.collections[0].selected_bands


def test_temperatura_maxima_selects_correct_band() -> None:
    fake_ee = FakeEeModule(value=298.15)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(_climate_request("temperatura_maxima_c", "temperature_2m_max"))

    assert "temperature_2m_max" in fake_ee.collections[0].selected_bands


# ─── ERA5-Land PET: meters (negative) → mm (positive) ────────────────────────


def test_pet_normalizes_sign_and_converts_to_mm() -> None:
    """potential_evaporation_sum raw=-0.075 m → abs(-0.075)*1000 = 75 mm."""
    fake_ee = FakeEeModule(value=-0.075)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(
        _climate_request("evapotranspiracion_referencia_mm", "potential_evaporation_sum", aggregation_method="sum")
    )

    assert result is not None
    assert abs(result.value - 75.0) < 1e-6


def test_pet_positive_raw_value_still_gives_correct_mm() -> None:
    """abs() handles also positive raw values (some ERA5 variants/regions)."""
    fake_ee = FakeEeModule(value=0.075)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(
        _climate_request("evapotranspiracion_referencia_mm", "potential_evaporation_sum", aggregation_method="sum")
    )

    assert result is not None
    assert abs(result.value - 75.0) < 1e-6


def test_pet_uses_era5_dataset() -> None:
    fake_ee = FakeEeModule(value=-0.075)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(
        _climate_request("evapotranspiracion_referencia_mm", "potential_evaporation_sum", aggregation_method="sum")
    )

    assert fake_ee.collections[0].dataset_key == _ERA5


def test_pet_uses_sum_temporal_aggregation() -> None:
    fake_ee = FakeEeModule(value=-0.075)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(
        _climate_request("evapotranspiracion_referencia_mm", "potential_evaporation_sum", aggregation_method="sum")
    )

    assert fake_ee.collections[0].temporal_reducer_used == "sum"


# ─── CHIRPS precipitation ─────────────────────────────────────────────────────


def test_precipitacion_uses_chirps_dataset() -> None:
    fake_ee = FakeEeModule(value=15.0)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(
        _climate_request("precipitacion_acumulada_mm", "precipitation",
                         dataset_key=_CHIRPS, aggregation_method="sum", scale=5566.0)
    )

    assert fake_ee.collections[0].dataset_key == _CHIRPS


def test_precipitacion_has_no_conversion() -> None:
    """CHIRPS precipitation is already in mm — raw=15.0 → result=15.0."""
    fake_ee = FakeEeModule(value=15.0)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(
        _climate_request("precipitacion_acumulada_mm", "precipitation",
                         dataset_key=_CHIRPS, aggregation_method="sum", scale=5566.0)
    )

    assert result is not None
    assert abs(result.value - 15.0) < 1e-9


def test_precipitacion_uses_sum_temporal_aggregation() -> None:
    fake_ee = FakeEeModule(value=15.0)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(
        _climate_request("precipitacion_acumulada_mm", "precipitation",
                         dataset_key=_CHIRPS, aggregation_method="sum", scale=5566.0)
    )

    assert fake_ee.collections[0].temporal_reducer_used == "sum"


# ─── Deficit hídrico derivado: max(0, PET − P) ────────────────────────────────


def test_deficit_computes_max_zero_pet_minus_precip() -> None:
    """ERA5 PET=-0.075m→75mm, CHIRPS P=15mm → deficit=max(0,75-15)=60mm."""
    fake_ee = FakeEeModule(dataset_values={
        _ERA5:   -0.075,   # raw PET in meters (negative ERA5 convention)
        _CHIRPS: 15.0,     # raw precipitation in mm
    })
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(
        _climate_request("deficit_hidrico_mm", "deficit_hidrico_mm")
    )

    assert result is not None
    assert abs(result.value - 60.0) < 1e-6


def test_deficit_is_zero_when_precip_exceeds_pet() -> None:
    """PET=10mm, P=50mm → deficit=max(0,10-50)=0mm (no deficit when rain covers demand)."""
    fake_ee = FakeEeModule(dataset_values={
        _ERA5:   -0.010,   # → 10mm after conversion
        _CHIRPS: 50.0,
    })
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(
        _climate_request("deficit_hidrico_mm", "deficit_hidrico_mm")
    )

    assert result is not None
    assert abs(result.value - 0.0) < 1e-9


def test_deficit_uses_two_collections() -> None:
    """Deficit extraction makes two ImageCollection calls: ERA5 for PET and CHIRPS for P."""
    fake_ee = FakeEeModule(dataset_values={_ERA5: -0.075, _CHIRPS: 15.0})
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(_climate_request("deficit_hidrico_mm", "deficit_hidrico_mm"))

    assert len(fake_ee.collections) == 2
    datasets = {c.dataset_key for c in fake_ee.collections}
    assert _ERA5 in datasets
    assert _CHIRPS in datasets


def test_deficit_returns_none_when_pet_unavailable() -> None:
    """If ERA5 PET is unavailable (None raw value), deficit returns None."""
    fake_ee = FakeEeModule(dataset_values={_ERA5: None, _CHIRPS: 15.0})
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(
        _climate_request("deficit_hidrico_mm", "deficit_hidrico_mm")
    )

    assert result is None


def test_deficit_returns_none_when_precip_unavailable() -> None:
    """If CHIRPS precipitation is unavailable (None raw value), deficit returns None."""
    fake_ee = FakeEeModule(dataset_values={_ERA5: -0.075, _CHIRPS: None})
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(
        _climate_request("deficit_hidrico_mm", "deficit_hidrico_mm")
    )

    assert result is None


# ─── Temporal window is applied ───────────────────────────────────────────────


@pytest.mark.parametrize("variable_name,band,dataset_key", [
    ("temperatura_minima_c",           "temperature_2m_min",        _ERA5),
    ("temperatura_maxima_c",           "temperature_2m_max",        _ERA5),
    ("temperatura_media_c",            "temperature_2m",            _ERA5),
    ("evapotranspiracion_referencia_mm", "potential_evaporation_sum", _ERA5),
    ("precipitacion_acumulada_mm",     "precipitation",             _CHIRPS),
])
def test_climate_variables_apply_date_filter(variable_name: str, band: str, dataset_key: str) -> None:
    fake_ee = FakeEeModule(value=100.0)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(_climate_request(variable_name, band, dataset_key=dataset_key))

    assert fake_ee.collections[0].date_filter == ("2023-01-01", "2024-01-01")


def test_deficit_date_filter_applied_to_both_source_collections() -> None:
    """Both ERA5 (PET) and CHIRPS (P) collections receive the same date filter."""
    fake_ee = FakeEeModule(dataset_values={_ERA5: -0.075, _CHIRPS: 15.0})
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(_climate_request("deficit_hidrico_mm", "deficit_hidrico_mm"))

    for coll in fake_ee.collections:
        assert coll.date_filter == ("2023-01-01", "2024-01-01"), (
            f"{coll.dataset_key}: date_filter={coll.date_filter}"
        )


# ─── Climate variables do not use static Image or Terrain ─────────────────────


@pytest.mark.parametrize("variable_name,band,dataset_key", [
    ("temperatura_minima_c",           "temperature_2m_min",        _ERA5),
    ("temperatura_maxima_c",           "temperature_2m_max",        _ERA5),
    ("temperatura_media_c",            "temperature_2m",            _ERA5),
    ("evapotranspiracion_referencia_mm", "potential_evaporation_sum", _ERA5),
    ("precipitacion_acumulada_mm",     "precipitation",             _CHIRPS),
])
def test_climate_variables_do_not_use_static_image(variable_name: str, band: str, dataset_key: str) -> None:
    fake_ee = FakeEeModule(value=100.0)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(_climate_request(variable_name, band, dataset_key=dataset_key))

    assert not fake_ee.static_images, f"{variable_name} must not call ee.Image (static)"
    assert fake_ee.terrain_slope_calls == 0


# ─── Source string format ──────────────────────────────────────────────────────


def test_climate_result_has_gee_source_prefix() -> None:
    fake_ee = FakeEeModule(value=292.15)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(_climate_request("temperatura_media_c", "temperature_2m"))

    assert result is not None
    assert result.source.startswith("GEE:")


# ─── None value passthrough ────────────────────────────────────────────────────


def test_climate_simple_returns_none_when_value_is_none() -> None:
    fake_ee = FakeEeModule(value=None)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(_climate_request("temperatura_minima_c", "temperature_2m_min"))

    assert result is None


# ─── Empty collection (data unavailable for date range) ───────────────────────


def test_climate_simple_returns_none_on_empty_collection() -> None:
    """'No bands' GEE error (empty collection) → extract_variable returns None."""
    fake_ee = FakeEeModuleEmpty()
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(_climate_request("temperatura_minima_c", "temperature_2m_min"))

    assert result is None


def test_climate_derived_returns_none_on_empty_collection() -> None:
    """Deficit returns None when an underlying collection is empty."""
    # ERA5 empty, CHIRPS has data — deficit should still be None
    fake_ee = FakeEeModulePartialEmpty(empty_dataset=_ERA5, present_value=15.0)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(_climate_request("deficit_hidrico_mm", "deficit_hidrico_mm"))

    assert result is None


def test_empty_collection_is_not_retried() -> None:
    """'No bands' is deterministic — only one attempt is made even with retries configured."""
    fake_ee = FakeEeModuleEmpty()
    client = GeeExtractionClient(settings=_gee_settings(max_retries=3), ee_module=fake_ee)

    result = client.extract_variable(_climate_request("temperatura_minima_c", "temperature_2m_min"))

    assert result is None
    assert len(fake_ee.collections) == 1  # no retries


# ─── Fake GEE module ──────────────────────────────────────────────────────────


_UNSET = object()  # sentinel to distinguish "no value" from explicit None


class FakeEeModule:
    """Earth Engine fake for climate dispatch tests.

    Pass ``value`` for a uniform return value across all datasets, or
    ``dataset_values`` (dict[dataset_key → value]) for per-dataset control.
    A dataset_values entry of ``None`` simulates a collection with no data.
    """

    def __init__(
        self,
        value: float | None = 1.0,
        dataset_values: dict[str, float | None] | None = None,
    ) -> None:
        self.value = value
        self.dataset_values: dict[str, float | None] = dataset_values or {}
        self.collections: list[FakeImageCollection] = []
        self.static_images: list = []
        self.terrain_slope_calls = 0
        self.Geometry = FakeGeometry(self)
        self.Reducer = FakeReducer(self)
        self.data = FakeData(self)
        self.Terrain = FakeTerrain(self)

    def ServiceAccountCredentials(self, service_account, private_key_file):
        return "credentials"

    def Initialize(self, credentials, project=None) -> None:
        pass

    def ImageCollection(self, dataset_key: str) -> "FakeImageCollection":
        if dataset_key in self.dataset_values:
            # Explicit entry — may be None to signal "no data available"
            collection = FakeImageCollection(self, dataset_key, explicit_value=self.dataset_values[dataset_key])
        else:
            collection = FakeImageCollection(self, dataset_key)
        self.collections.append(collection)
        return collection

    def Image(self, dataset_key: str):
        img = object()
        self.static_images.append(img)
        return img


class FakeTerrain:
    def __init__(self, ee: FakeEeModule) -> None:
        self._ee = ee

    def slope(self, image: object) -> object:
        self._ee.terrain_slope_calls += 1
        return object()


class FakeData:
    def __init__(self, ee: FakeEeModule) -> None:
        self._ee = ee

    def setDeadline(self, ms: int) -> None:
        pass


class FakeGeometry:
    def __init__(self, ee: FakeEeModule) -> None:
        self._ee = ee
        self.point_calls: list = []

    def Polygon(self, coordinates: object) -> tuple:
        return ("Polygon", coordinates)

    def MultiPolygon(self, coordinates: object) -> tuple:
        return ("MultiPolygon", coordinates)

    def Point(self, lon_lat: list) -> tuple:
        self.point_calls.append(lon_lat)
        return ("Point", lon_lat)


class FakeReducer:
    def __init__(self, ee: FakeEeModule) -> None:
        self._ee = ee

    def mean(self) -> str:
        return "mean"

    def median(self) -> str:
        return "median"

    def min(self) -> str:
        return "min"

    def max(self) -> str:
        return "max"


class FakeImageCollection:
    """Fake ImageCollection that tracks temporal aggregation and carries a per-dataset value."""

    def __init__(self, ee: FakeEeModule, dataset_key: str, explicit_value=_UNSET) -> None:
        self._ee = ee
        self.dataset_key = dataset_key
        # _UNSET means "use module-wide default"; explicit None means "no data"
        self._value = ee.value if explicit_value is _UNSET else explicit_value
        self.date_filter: tuple | None = None
        self.selected_bands: list[str] = []
        self.selected_band: str | None = None
        self.temporal_reducer_used: str | None = None
        self.image = FakeComputedImage(ee, explicit_value=self._value)

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

    def map(self, func) -> "FakeImageCollection":
        return self

    def mean(self) -> "FakeComputedImage":
        self.temporal_reducer_used = "mean"
        self.image.reducer_method = "mean"
        return self.image

    def median(self) -> "FakeComputedImage":
        self.temporal_reducer_used = "median"
        self.image.reducer_method = "median"
        return self.image

    def sum(self) -> "FakeComputedImage":
        self.temporal_reducer_used = "sum"
        self.image.reducer_method = "sum"
        return self.image

    def min(self) -> "FakeComputedImage":
        self.temporal_reducer_used = "min"
        self.image.reducer_method = "min"
        return self.image

    def max(self) -> "FakeComputedImage":
        self.temporal_reducer_used = "max"
        self.image.reducer_method = "max"
        return self.image


class FakeComputedImage:
    def __init__(self, ee: FakeEeModule, explicit_value=_UNSET) -> None:
        self._ee = ee
        self._value = ee.value if explicit_value is _UNSET else explicit_value
        self.reducer_method: str | None = None
        self.expression_called = False
        self.last_expression: str | None = None
        self.renamed_band: str | None = None

    def normalizedDifference(self, bands: list[str]) -> "FakeComputedImage":
        return self

    def expression(self, expr: str, band_map: dict | None = None) -> "FakeComputedImage":
        self.expression_called = True
        self.last_expression = expr
        return self

    def rename(self, name: str) -> "FakeComputedImage":
        self.renamed_band = name
        return self

    def select(self, band) -> "FakeComputedImage":
        return self

    def reduceRegion(self, **kwargs) -> "FakeRegion":
        return FakeRegion(self._value)


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


# ─── Fakes for empty-collection (data lag / unavailable date range) ───────────


class FakeValueError:
    """Simulates a GEE value whose getInfo raises 'no bands' (empty collection)."""

    def getInfo(self) -> None:
        raise Exception(
            "Image.select: Band pattern 'temperature_2m_min' was applied to an Image with no bands."
        )


class FakeRegionError:
    def get(self, band: str) -> FakeValueError:
        return FakeValueError()


class FakeComputedImageError(FakeComputedImage):
    """FakeComputedImage whose reduceRegion propagates a 'no bands' error."""

    def reduceRegion(self, **kwargs) -> FakeRegionError:
        return FakeRegionError()


class FakeImageCollectionEmpty(FakeImageCollection):
    """FakeImageCollection simulating an empty collection (no data for date range)."""

    def __init__(self, ee: FakeEeModule, dataset_key: str, explicit_value=_UNSET) -> None:
        super().__init__(ee, dataset_key, explicit_value=explicit_value)
        self.image = FakeComputedImageError(ee)


class FakeEeModuleEmpty(FakeEeModule):
    """Simulates GEE where every ImageCollection is empty (raises 'no bands' on getInfo)."""

    def ImageCollection(self, dataset_key: str) -> "FakeImageCollectionEmpty":
        collection = FakeImageCollectionEmpty(self, dataset_key)
        self.collections.append(collection)
        return collection


class FakeEeModulePartialEmpty(FakeEeModule):
    """Simulates GEE where one dataset is empty and another has data.

    Used to test deficit robustness when one source is unavailable.
    """

    def __init__(self, empty_dataset: str, present_value: float) -> None:
        super().__init__(value=present_value)
        self._empty_dataset = empty_dataset

    def ImageCollection(self, dataset_key: str):
        if dataset_key == self._empty_dataset:
            collection = FakeImageCollectionEmpty(self, dataset_key)
        else:
            collection = FakeImageCollection(self, dataset_key, explicit_value=self.value)
        self.collections.append(collection)
        return collection
