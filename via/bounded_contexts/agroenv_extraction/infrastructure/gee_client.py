"""Google Earth Engine extraction client adapter."""

from __future__ import annotations

from datetime import date
from importlib import import_module
from time import sleep
from typing import Any, Callable

from via.bounded_contexts.agroenv_extraction.application.ports import ExtractionClientResult, ExtractionRequest, IExtractionClient
from via.config import Settings, get_settings


class GeeExtractionError(RuntimeError):
    """Raised when Google Earth Engine extraction cannot complete."""


class GeeExtractionClient(IExtractionClient):
    """Google Earth Engine adapter for one variable-period extraction."""

    def __init__(
        self,
        settings: Settings | None = None,
        ee_module: object | None = None,
        sleep_func: Callable[[float], None] = sleep,
    ) -> None:
        """Create a GEE client and initialize Earth Engine when enabled."""

        self._settings = settings or get_settings()
        self._ee = ee_module
        self._sleep = sleep_func
        self._initialized = False
        if self._settings.gee_enabled:
            self._initialize()

    def extract_variable(self, request: ExtractionRequest) -> ExtractionClientResult | None:
        """Extract one variable value from Google Earth Engine."""

        if not self._settings.gee_enabled:
            raise GeeExtractionError("GEE is disabled")
        reducer_factory = _reducer_factory(request.reducer)
        start_date, end_date = _date_range(request)

        last_error: Exception | None = None
        attempts = self._settings.gee_max_retries + 1
        for attempt in range(attempts):
            try:
                value = self._extract_once(request, reducer_factory, start_date, end_date)
                if value is None:
                    return None
                return ExtractionClientResult(
                    value=float(value),
                    source=f"GEE:{request.dataset_key}:{request.band}",
                    extraction_date=date.today(),
                )
            except GeeExtractionError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < attempts - 1:
                    self._sleep(min(2**attempt, 5))
                    continue
        raise GeeExtractionError(f"GEE extraction failed after {attempts} attempts: {last_error}") from last_error

    def _initialize(self) -> None:
        if self._initialized:
            return
        ee = self._ee or import_module("ee")
        credentials = ee.ServiceAccountCredentials(
            self._settings.gee_service_account,
            self._settings.gee_private_key_file,
        )
        ee.Initialize(credentials, project=self._settings.gee_project)
        if hasattr(ee, "data") and hasattr(ee.data, "setDeadline"):
            ee.data.setDeadline(self._settings.gee_timeout_seconds * 1000)
        self._ee = ee
        self._initialized = True

    def _extract_once(
        self,
        request: ExtractionRequest,
        reducer_factory: Callable[[object], object],
        start_date: str,
        end_date: str,
    ) -> float | int | None:
        ee = self._ee
        if ee is None:
            raise GeeExtractionError("GEE module is not initialized")

        geometry = _gee_geometry(ee, request.parcel_geometry)
        reducer = reducer_factory(ee)
        image = (
            ee.ImageCollection(request.dataset_key)
            .filterDate(start_date, end_date)
            .select(request.band)
        )
        image = _apply_quality_mask(image, request.quality_mask)
        image = _image_for_reducer(image, request.reducer)
        region = image.reduceRegion(
            reducer=reducer,
            geometry=geometry,
            scale=_scale(request),
            maxPixels=1e13,
            bestEffort=True,
        )
        value_ref = region.get(request.band)
        return value_ref.getInfo() if hasattr(value_ref, "getInfo") else value_ref


def _reducer_factory(name: str) -> Callable[[object], object]:
    reducers: dict[str, Callable[[object], object]] = {
        "mean": lambda ee: ee.Reducer.mean(),
        "median": lambda ee: ee.Reducer.median(),
        "min": lambda ee: ee.Reducer.min(),
        "max": lambda ee: ee.Reducer.max(),
    }
    key = name.lower()
    if key not in reducers:
        raise GeeExtractionError(f"Unsupported GEE reducer: {name}")
    return reducers[key]


def _date_range(request: ExtractionRequest) -> tuple[str, str]:
    start_date = request.period_start or request.temporal_window.get("start") or request.temporal_window.get("start_date")
    end_date = request.period_end or request.temporal_window.get("end") or request.temporal_window.get("end_date")
    if not start_date or not end_date:
        raise GeeExtractionError("ExtractionRequest requires temporal start and end dates")
    return str(start_date), str(end_date)


def _gee_geometry(ee: object, geometry: dict[str, Any]) -> object:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Polygon":
        return ee.Geometry.Polygon(coordinates)
    if geometry_type == "MultiPolygon":
        return ee.Geometry.MultiPolygon(coordinates)
    raise GeeExtractionError("parcel_geometry type must be Polygon or MultiPolygon")


def _apply_quality_mask(image_collection: object, quality_mask: dict[str, Any] | None) -> object:
    if not quality_mask:
        return image_collection
    band = quality_mask.get("band") or quality_mask.get("mask_band")
    if not band:
        return image_collection
    equals = quality_mask.get("equals")
    allowed_values = quality_mask.get("allowed_values") or quality_mask.get("values")

    def mask_image(image: object) -> object:
        selected = image.select(band)
        if equals is not None:
            mask = selected.eq(equals)
        elif allowed_values:
            mask = selected.eq(allowed_values[0])
            for value in allowed_values[1:]:
                mask = mask.Or(selected.eq(value))
        else:
            return image
        return image.updateMask(mask)

    return image_collection.map(mask_image)


def _image_for_reducer(image_collection: object, reducer: str) -> object:
    method_name = reducer.lower()
    method = getattr(image_collection, method_name)
    return method()


def _scale(request: ExtractionRequest) -> float:
    if request.scale is not None:
        return float(request.scale)
    if request.spatial_resolution:
        text = str(request.spatial_resolution).strip().lower().removesuffix("m")
        try:
            return float(text)
        except ValueError as exc:
            raise GeeExtractionError(f"Invalid spatial resolution for GEE scale: {request.spatial_resolution}") from exc
    return 30.0
