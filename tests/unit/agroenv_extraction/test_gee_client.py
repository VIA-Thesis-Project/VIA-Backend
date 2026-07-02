"""Unit tests for the Google Earth Engine extraction client adapter."""

from __future__ import annotations

import ast
from pathlib import Path
from uuid import uuid4

import pytest

from via.bounded_contexts.agroenv_extraction.application.ports import ExtractionRequest
from via.bounded_contexts.agroenv_extraction.domain.value_objects import AgroenvExtractionError
from via.bounded_contexts.agroenv_extraction.infrastructure.extraction_acl import ExtractionAcl
from via.bounded_contexts.agroenv_extraction.infrastructure.gee_client import GeeExtractionClient, GeeExtractionError
from via.config import load_settings


ROOT = Path(__file__).resolve().parents[3]
DOMAIN = ROOT / "via" / "bounded_contexts" / "agroenv_extraction" / "domain"


def test_initialization_does_not_run_when_gee_is_disabled() -> None:
    fake_ee = FakeEeModule()

    GeeExtractionClient(settings=load_settings({"GEE_ENABLED": "false"}), ee_module=fake_ee)

    assert fake_ee.initialize_calls == []


def test_initialization_runs_when_gee_is_enabled() -> None:
    fake_ee = FakeEeModule()

    GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    assert fake_ee.credentials_calls == [("svc@example.com", "C:/keys/gee.json")]
    assert fake_ee.initialize_calls == [("credentials", "via-project")]
    assert fake_ee.deadline_calls == [60000]


def test_query_uses_dataset_band_polygon_temporal_period_and_reducer() -> None:
    fake_ee = FakeEeModule(value=0.72)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    result = client.extract_variable(_request(reducer="median", parcel_geometry=_polygon(), period_start="2026-02-01", period_end="2026-02-28"))

    assert result is not None
    assert result.value == 0.72
    assert result.source == "GEE:sentinel-2:B08:polygon_mean:scale=10"
    assert fake_ee.collections[0].dataset_key == "sentinel-2"
    assert fake_ee.collections[0].selected_band == "B08"
    assert fake_ee.collections[0].date_filter == ("2026-02-01", "2026-02-28")
    assert fake_ee.geometry_calls == [("Polygon", _polygon()["coordinates"])]
    assert fake_ee.reducer_calls[-1] == "median"
    assert fake_ee.collections[0].image.reducer_method == "median"
    assert fake_ee.collections[0].image.reduce_region_kwargs["scale"] == 10.0


def test_query_converts_multipolygon_to_gee_geometry() -> None:
    fake_ee = FakeEeModule(value=0.5)
    geometry = {"type": "MultiPolygon", "coordinates": [_polygon()["coordinates"]]}
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(_request(parcel_geometry=geometry))

    assert fake_ee.geometry_calls == [("MultiPolygon", geometry["coordinates"])]


@pytest.mark.parametrize("reducer", ["mean", "median", "min", "max"])
def test_supported_reducers_are_applied(reducer: str) -> None:
    fake_ee = FakeEeModule(value=0.4)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(_request(reducer=reducer))

    assert fake_ee.reducer_calls[-1] == reducer
    assert fake_ee.collections[0].image.reducer_method == reducer


def test_unknown_reducer_fails_clearly() -> None:
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=FakeEeModule())

    with pytest.raises(GeeExtractionError, match="Unsupported GEE reducer"):
        client.extract_variable(_request(reducer="mode"))


def test_quality_mask_is_applied_when_configured() -> None:
    fake_ee = FakeEeModule(value=0.6)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    client.extract_variable(_request(quality_mask={"band": "QA", "equals": 0}))

    assert fake_ee.collections[0].map_called is True


def test_null_value_with_fallback_returns_none_for_acl_missing_entry() -> None:
    fake_ee = FakeEeModule(value=None)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    vector = ExtractionAcl().build_vector(_command_payload(fallback_allowed=True), client)

    assert vector.variables[0].value is None
    assert vector.variables[0].status.value == "CRITERIO_FALTANTE"


def test_null_value_without_fallback_fails_controlled() -> None:
    fake_ee = FakeEeModule(value=None)
    client = GeeExtractionClient(settings=_gee_settings(), ee_module=fake_ee)

    with pytest.raises(AgroenvExtractionError, match="Variable unavailable without fallback"):
        ExtractionAcl().build_vector(_command_payload(fallback_allowed=False), client)


def test_retry_is_used_for_transient_errors() -> None:
    fake_ee = FakeEeModule(value=0.9, transient_failures=1)
    sleeps: list[float] = []
    client = GeeExtractionClient(settings=_gee_settings(max_retries=2), ee_module=fake_ee, sleep_func=sleeps.append)

    result = client.extract_variable(_request())

    assert result is not None
    assert result.value == 0.9
    assert fake_ee.reduce_region_attempts == 2
    assert sleeps == [1]


def test_missing_imagecollection_asset_with_fallback_returns_none_without_retry() -> None:
    fake_ee = FakeEeModule(
        error=RuntimeError(
            "ImageCollection.load: ImageCollection asset 'projects/soilgrids-isric/ece' "
            "not found (does not exist or caller does not have access)."
        )
    )
    sleeps: list[float] = []
    client = GeeExtractionClient(settings=_gee_settings(max_retries=3), ee_module=fake_ee, sleep_func=sleeps.append)

    result = client.extract_variable(_request())

    assert result is None
    assert fake_ee.reduce_region_attempts == 1
    assert sleeps == []


def test_domain_does_not_import_earth_engine() -> None:
    offenders: list[str] = []
    for path in DOMAIN.rglob("*.py"):
        for imported_name in _imports_from(path):
            if imported_name in {"ee", "earthengine"} or imported_name.startswith("ee."):
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {imported_name}")

    assert offenders == []


class FakeEeModule:
    """Small Earth Engine module fake that records API calls."""

    def __init__(
        self,
        value: float | None = 1.0,
        transient_failures: int = 0,
        error: Exception | None = None,
    ) -> None:
        """Create fake EE state."""

        self.value = value
        self.transient_failures = transient_failures
        self.error = error
        self.reduce_region_attempts = 0
        self.credentials_calls: list[tuple[str | None, str | None]] = []
        self.initialize_calls: list[tuple[str, str | None]] = []
        self.deadline_calls: list[int] = []
        self.geometry_calls: list[tuple[str, object]] = []
        self.reducer_calls: list[str] = []
        self.collections: list[FakeImageCollection] = []
        self.Geometry = FakeGeometry(self)
        self.Reducer = FakeReducer(self)
        self.data = FakeData(self)

    def ServiceAccountCredentials(self, service_account: str | None, private_key_file: str | None) -> str:
        """Record fake service-account credential creation."""

        self.credentials_calls.append((service_account, private_key_file))
        return "credentials"

    def Initialize(self, credentials: str, project: str | None = None) -> None:
        """Record fake initialization."""

        self.initialize_calls.append((credentials, project))

    def ImageCollection(self, dataset_key: str) -> "FakeImageCollection":
        """Return a fake image collection."""

        collection = FakeImageCollection(self, dataset_key)
        self.collections.append(collection)
        return collection


class FakeData:
    """Fake ee.data namespace."""

    def __init__(self, ee: FakeEeModule) -> None:
        """Keep fake module state."""

        self._ee = ee

    def setDeadline(self, milliseconds: int) -> None:
        """Record fake request deadline."""

        self._ee.deadline_calls.append(milliseconds)


class FakeGeometry:
    """Fake ee.Geometry namespace."""

    def __init__(self, ee: FakeEeModule) -> None:
        """Keep fake module state."""

        self._ee = ee

    def Polygon(self, coordinates: object) -> tuple[str, object]:
        """Record polygon conversion."""

        self._ee.geometry_calls.append(("Polygon", coordinates))
        return ("Polygon", coordinates)

    def MultiPolygon(self, coordinates: object) -> tuple[str, object]:
        """Record multipolygon conversion."""

        self._ee.geometry_calls.append(("MultiPolygon", coordinates))
        return ("MultiPolygon", coordinates)


class FakeReducer:
    """Fake ee.Reducer namespace."""

    def __init__(self, ee: FakeEeModule) -> None:
        """Keep fake module state."""

        self._ee = ee

    def mean(self) -> str:
        """Return fake mean reducer."""

        self._ee.reducer_calls.append("mean")
        return "mean"

    def median(self) -> str:
        """Return fake median reducer."""

        self._ee.reducer_calls.append("median")
        return "median"

    def min(self) -> str:
        """Return fake min reducer."""

        self._ee.reducer_calls.append("min")
        return "min"

    def max(self) -> str:
        """Return fake max reducer."""

        self._ee.reducer_calls.append("max")
        return "max"


class FakeImageCollection:
    """Fake image collection with fluent GEE-like methods."""

    def __init__(self, ee: FakeEeModule, dataset_key: str) -> None:
        """Create fake collection."""

        self._ee = ee
        self.dataset_key = dataset_key
        self.date_filter: tuple[str, str] | None = None
        self.selected_band: str | None = None
        self.map_called = False
        self.image = FakeImage(ee)

    def filterDate(self, start_date: str, end_date: str) -> "FakeImageCollection":
        """Record date filter."""

        self.date_filter = (start_date, end_date)
        return self

    def select(self, band: str) -> "FakeImageCollection":
        """Record selected band."""

        self.selected_band = band
        return self

    def map(self, func):
        """Record quality mask mapping."""

        self.map_called = True
        func(FakeMaskableImage())
        return self

    def mean(self) -> "FakeImage":
        """Return fake mean image."""

        self.image.reducer_method = "mean"
        return self.image

    def median(self) -> "FakeImage":
        """Return fake median image."""

        self.image.reducer_method = "median"
        return self.image

    def min(self) -> "FakeImage":
        """Return fake min image."""

        self.image.reducer_method = "min"
        return self.image

    def max(self) -> "FakeImage":
        """Return fake max image."""

        self.image.reducer_method = "max"
        return self.image


class FakeImage:
    """Fake image used for reduceRegion."""

    def __init__(self, ee: FakeEeModule) -> None:
        """Create fake image."""

        self._ee = ee
        self.reducer_method: str | None = None
        self.reduce_region_kwargs: dict = {}

    def reduceRegion(self, **kwargs) -> "FakeRegion":
        """Record reduceRegion and optionally fail transiently."""

        self._ee.reduce_region_attempts += 1
        self.reduce_region_kwargs = kwargs
        if self._ee.error is not None:
            raise self._ee.error
        if self._ee.reduce_region_attempts <= self._ee.transient_failures:
            raise RuntimeError("temporary gee failure")
        return FakeRegion(self._ee.value)


class FakeRegion:
    """Fake region dictionary returned by reduceRegion."""

    def __init__(self, value: float | None) -> None:
        """Create fake region."""

        self._value = value

    def get(self, band: str) -> "FakeValue":
        """Return fake value reference."""

        return FakeValue(self._value)


class FakeValue:
    """Fake value reference with getInfo."""

    def __init__(self, value: float | None) -> None:
        """Create fake value reference."""

        self._value = value

    def getInfo(self) -> float | None:
        """Return fake scalar."""

        return self._value


class FakeMaskableImage:
    """Fake image for quality-mask callbacks."""

    def select(self, band: str) -> "FakeMaskBand":
        """Return fake mask band."""

        return FakeMaskBand()

    def updateMask(self, mask: object) -> "FakeMaskableImage":
        """Return self after fake mask."""

        return self


class FakeMaskBand:
    """Fake selected band for mask comparisons."""

    def eq(self, value: object) -> "FakeMask":
        """Return fake mask."""

        return FakeMask()


class FakeMask:
    """Fake mask object."""

    def Or(self, other: object) -> "FakeMask":
        """Return fake OR mask."""

        return self


def _gee_settings(max_retries: int = 3):
    return load_settings(
        {
            "GEE_ENABLED": "true",
            "GEE_PROJECT": "via-project",
            "GEE_SERVICE_ACCOUNT": "svc@example.com",
            "GEE_PRIVATE_KEY_FILE": "C:/keys/gee.json",
            "GEE_MAX_RETRIES": str(max_retries),
        }
    )


def _request(
    reducer: str = "mean",
    parcel_geometry: dict | None = None,
    quality_mask: dict | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
) -> ExtractionRequest:
    return ExtractionRequest(
        parcel_id=uuid4(),
        parcel_geometry=parcel_geometry or {"type": "MultiPolygon", "coordinates": [_polygon()["coordinates"]]},
        temporal_window={"start": "2026-01-01", "end": "2026-01-31"},
        variable_name="nir_reflectancia",
        criterion_id="vigor",
        crop_id="cacao",
        phase_id="floracion",
        dataset_key="sentinel-2",
        band="B08",
        unit="index",
        temporal_resolution="monthly",
        spatial_resolution="10m",
        scale=10,
        reducer=reducer,
        aggregation_method="mean",
        quality_mask=quality_mask,
        fallback_allowed=True,
        period_key="2026-01",
        period_start=period_start,
        period_end=period_end,
    )


def _command_payload(fallback_allowed: bool):
    from via.bounded_contexts.agroenv_extraction.application.ports import StartExtractionCommand

    return StartExtractionCommand.from_payload(
        {
            "evaluation_id": str(uuid4()),
            "parcel_id": str(uuid4()),
            "parcel_geometry": _polygon(),
            "crop_candidates": ["cacao"],
            "temporal_window": {"start": "2026-01-01", "end": "2026-01-31"},
            "required_extraction_spec": {
                "variables": [
                    {
                        "variable_name": "nir_reflectancia",
                        "criterion_id": "vigor",
                        "crop_id": "cacao",
                        "phase_id": "floracion",
                        "dataset_key": "sentinel-2",
                        "band": "B08",
                        "unit": "index",
                        "temporal_resolution": "monthly",
                        "spatial_resolution": "10m",
                        "scale": 10,
                        "reducer": "mean",
                        "aggregation_method": "mean",
                        "quality_mask": None,
                        "fallback_allowed": fallback_allowed,
                        "temporal_periods": [
                            {
                                "period_key": "2026-01",
                                "start": "2026-01-01",
                                "end": "2026-01-31",
                                "temporal_weight": 1.0,
                            }
                        ],
                    }
                ]
            },
        }
    )


def _polygon() -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [[-76.0, -12.0], [-76.0, -12.01], [-75.99, -12.01], [-75.99, -12.0], [-76.0, -12.0]]
        ],
    }


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
