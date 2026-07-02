"""Google Earth Engine extraction client adapter."""

from __future__ import annotations

from datetime import date
from importlib import import_module
from time import sleep
from typing import Any, Callable

from via.bounded_contexts.agroenv_extraction.application.ports import ExtractionClientResult, ExtractionRequest, IExtractionClient
from via.bounded_contexts.agroenv_extraction.infrastructure.gee_variable_registry import GeeVariableDefinition, GeeVariableType, get_variable_definition
from via.config import Settings, get_settings

SAVI_L: float = 0.5


class GeeExtractionError(RuntimeError):
    """Raised when Google Earth Engine extraction cannot complete."""


class GeeExtractionClient(IExtractionClient):
    """Google Earth Engine adapter for one variable-period extraction.

    Dispatches to the appropriate extraction strategy (simple band, derived
    index, or topographic) based on the variable registry.  Unknown variables
    fall back to the simple-band strategy for backward compatibility.
    """

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
        defn = get_variable_definition(request.variable_name)
        strategy = defn.spatial_sampling_strategy if defn is not None else "polygon_mean"
        scale = _scale(request)

        last_error: Exception | None = None
        attempts = self._settings.gee_max_retries + 1
        for attempt in range(attempts):
            try:
                value = self._extract_once(request, reducer_factory, start_date, end_date)
                if value is None:
                    return None
                return ExtractionClientResult(
                    value=float(value),
                    source=f"GEE:{request.dataset_key}:{request.band}:{strategy}:scale={int(scale)}",
                    extraction_date=date.today(),
                )
            except GeeExtractionError:
                raise
            except Exception as exc:
                # "No bands" means the ImageCollection was empty for the requested period.
                # This is deterministic — retrying won't help. Return None so fallback_allowed handles it.
                if _is_empty_collection_error(exc):
                    return None
                if request.fallback_allowed and _is_missing_asset_error(exc):
                    return None
                last_error = exc
                if attempt < attempts - 1:
                    self._sleep(min(2**attempt, 5))
                    continue
        raise GeeExtractionError(f"GEE extraction failed after {attempts} attempts: {last_error}") from last_error

    def _initialize(self) -> None:
        if self._initialized:
            return
        ee = self._ee or import_module("ee")
        if self._settings.gee_private_key_json:
            credentials = ee.ServiceAccountCredentials(
                self._settings.gee_service_account,
                key_data=self._settings.gee_private_key_json,
            )
        else:
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
        scale = _scale(request)
        defn = get_variable_definition(request.variable_name)

        if defn is None or defn.variable_type == GeeVariableType.SIMPLE_BAND:
            return _extract_simple(ee, request, geometry, reducer, scale, start_date, end_date)
        if defn.variable_type == GeeVariableType.DERIVED_INDEX:
            return _extract_index(ee, request, defn, geometry, reducer, scale, start_date, end_date)
        if defn.variable_type in (GeeVariableType.TOPO_STATIC, GeeVariableType.TOPO_DERIVED):
            return _extract_topo(ee, request, defn, geometry, reducer, scale)
        if defn.variable_type == GeeVariableType.CLIMATE_SIMPLE:
            sampling_geom = _sampling_geometry(ee, geometry, request.parcel_geometry, defn.spatial_sampling_strategy)
            return _extract_climate_simple(ee, defn, sampling_geom, reducer, scale, start_date, end_date)
        if defn.variable_type == GeeVariableType.CLIMATE_DERIVED:
            return _extract_climate_derived_multivar(ee, defn, geometry, request.parcel_geometry, reducer, start_date, end_date)
        if defn.variable_type == GeeVariableType.SOIL_STATIC:
            sampling_geom = _sampling_geometry(ee, geometry, request.parcel_geometry, defn.spatial_sampling_strategy)
            return _extract_soil(ee, defn, sampling_geom, reducer, scale)
        raise GeeExtractionError(f"Unsupported variable type: {defn.variable_type}")


# ─── Private helpers ──────────────────────────────────────────────────────────


def _is_empty_collection_error(exc: Exception) -> bool:
    """True when a GEE server error indicates an empty ImageCollection for the period.

    GEE raises this when .mean()/.sum() is called on a collection with no images:
      "Image.select: Band pattern '...' was applied to an Image with no bands."
    TerraClimate has a ~1-2 year data lag, so future date ranges trigger this.
    """
    msg = str(exc)
    return "no bands" in msg.lower() or "Band pattern" in msg


def _is_missing_asset_error(exc: Exception) -> bool:
    """Return True for deterministic missing/inaccessible GEE assets."""

    msg = str(exc).lower()
    return (
        (
            ("not found" in msg or "does not exist" in msg)
            and ("asset" in msg or "imagecollection" in msg or "image collection" in msg)
        )
        or "caller does not have access" in msg
    )


# ─── Extraction strategies ────────────────────────────────────────────────────


def _extract_simple(
    ee: object,
    request: ExtractionRequest,
    geometry: object,
    reducer: object,
    scale: float,
    start_date: str,
    end_date: str,
) -> float | int | None:
    """Extract a single raw band from an ImageCollection."""
    image = (
        ee.ImageCollection(request.dataset_key)
        .filterDate(start_date, end_date)
        .select(request.band)
    )
    image = _apply_quality_mask(image, request.quality_mask)
    image = _image_for_reducer(image, request.reducer)
    region = image.reduceRegion(reducer=reducer, geometry=geometry, scale=scale, maxPixels=1e13, bestEffort=True)
    value_ref = region.get(request.band)
    return value_ref.getInfo() if hasattr(value_ref, "getInfo") else value_ref


def _extract_index(
    ee: object,
    request: ExtractionRequest,
    defn: GeeVariableDefinition,
    geometry: object,
    reducer: object,
    scale: float,
    start_date: str,
    end_date: str,
) -> float | int | None:
    """Extract a spectral index by computing it from reduced multi-band imagery."""
    collection = (
        ee.ImageCollection(defn.dataset_key)
        .filterDate(start_date, end_date)
        .select(list(defn.source_bands))
    )
    collection = _apply_quality_mask(collection, request.quality_mask)
    reduced = _image_for_reducer(collection, request.reducer)
    computed = _compute_index(ee, reduced, defn)
    region = computed.reduceRegion(reducer=reducer, geometry=geometry, scale=scale, maxPixels=1e13, bestEffort=True)
    value_ref = region.get(defn.result_band)
    return value_ref.getInfo() if hasattr(value_ref, "getInfo") else value_ref


def _extract_topo(
    ee: object,
    request: ExtractionRequest,
    defn: GeeVariableDefinition,
    geometry: object,
    reducer: object,
    scale: float,
) -> float | int | None:
    """Extract a topographic variable from a static DEM image (no temporal filter)."""
    if defn.variable_type == GeeVariableType.TOPO_STATIC:
        image = ee.Image(defn.dataset_key).select(defn.result_band)
    else:
        dem = ee.Image(defn.dataset_key)
        image = ee.Terrain.slope(dem)
    region = image.reduceRegion(reducer=reducer, geometry=geometry, scale=scale, maxPixels=1e13, bestEffort=True)
    value_ref = region.get(defn.result_band)
    return value_ref.getInfo() if hasattr(value_ref, "getInfo") else value_ref


def _extract_climate_simple(
    ee: object,
    defn: GeeVariableDefinition,
    geometry: object,
    reducer: object,
    scale: float,
    start_date: str,
    end_date: str,
) -> float | int | None:
    """Extract a single climate band (ERA5-Land or CHIRPS), applying temporal aggregation and unit conversions."""
    collection = (
        ee.ImageCollection(defn.dataset_key)
        .filterDate(start_date, end_date)
        .select(list(defn.source_bands))
    )
    image = _image_for_reducer(collection, defn.temporal_aggregation)
    region = image.reduceRegion(reducer=reducer, geometry=geometry, scale=scale, maxPixels=1e13, bestEffort=True)
    value_ref = region.get(defn.result_band)
    raw = value_ref.getInfo() if hasattr(value_ref, "getInfo") else value_ref
    return _apply_conversion(raw, defn.scale_factor, defn.offset, defn.normalize_sign)


def _extract_climate_derived_multivar(
    ee: object,
    defn: GeeVariableDefinition,
    geometry: object,
    parcel_geometry_dict: dict,
    reducer: object,
    start_date: str,
    end_date: str,
) -> float | None:
    """Derive a climate variable by extracting multiple registered source variables and combining them.

    Each source variable is extracted at its own native scale and spatial_sampling_strategy.
    Returns None if any source variable is unavailable for the requested period.
    """
    if not defn.derived_from:
        raise GeeExtractionError(f"CLIMATE_DERIVED variable {defn.variable_name!r} has no derived_from")
    source_values: dict[str, float] = {}
    for src_name in defn.derived_from:
        src_defn = get_variable_definition(src_name)
        if src_defn is None:
            raise GeeExtractionError(
                f"{defn.variable_name!r}: source variable {src_name!r} not found in registry"
            )
        sampling_geom = _sampling_geometry(ee, geometry, parcel_geometry_dict, src_defn.spatial_sampling_strategy)
        value = _extract_climate_simple(
            ee, src_defn, sampling_geom, reducer, src_defn.default_scale, start_date, end_date
        )
        if value is None:
            return None
        source_values[src_name] = float(value)
    return _apply_deficit_formula(defn, source_values)


def _extract_soil(
    ee: object,
    defn: GeeVariableDefinition,
    geometry: object,
    reducer: object,
    scale: float,
) -> float | int | None:
    """Extract a static soil variable from OpenLandMap using the declared depth strategy.

    depth_strategy controls which bands from the multi-depth image are used:
        "surface_0cm"        — selects only band b0 (0 cm layer).
        "topsoil_0_30cm_mean" — arithmetic mean of b0, b10, b30 (0, 10, 30 cm layers).

    The image is renamed to defn.result_band before reduceRegion so the key is predictable.
    scale_factor is applied afterward via _apply_conversion.
    """
    if not defn.source_bands:
        raise GeeExtractionError(f"SOIL_STATIC variable {defn.variable_name!r} has no source_bands")
    if defn.depth_strategy not in ("surface_0cm", "topsoil_0_30cm_mean"):
        raise GeeExtractionError(
            f"SOIL_STATIC variable {defn.variable_name!r} has unsupported depth_strategy: {defn.depth_strategy!r}"
        )

    image = ee.Image(defn.dataset_key)

    if defn.depth_strategy == "surface_0cm":
        result_image = image.select(defn.source_bands[0]).rename(defn.result_band)
    else:  # topsoil_0_30cm_mean
        if len(defn.source_bands) < 3:
            raise GeeExtractionError(
                f"topsoil_0_30cm_mean requires at least 3 source_bands, "
                f"got {len(defn.source_bands)} for {defn.variable_name!r}"
            )
        bands = list(defn.source_bands)
        result_image = (
            image.select(bands[0])
            .add(image.select(bands[1]))
            .add(image.select(bands[2]))
            .divide(len(bands))
            .rename(defn.result_band)
        )

    region = result_image.reduceRegion(
        reducer=reducer, geometry=geometry, scale=scale, maxPixels=1e13, bestEffort=True
    )
    value_ref = region.get(defn.result_band)
    raw = value_ref.getInfo() if hasattr(value_ref, "getInfo") else value_ref
    return _apply_conversion(raw, defn.scale_factor, defn.offset, defn.normalize_sign)


def _apply_deficit_formula(defn: GeeVariableDefinition, source_values: dict[str, float]) -> float:
    """Apply the deficit formula for CLIMATE_DERIVED variables."""
    if defn.variable_name == "deficit_hidrico_mm":
        pet = source_values["evapotranspiracion_referencia_mm"]
        p = source_values["precipitacion_acumulada_mm"]
        return max(0.0, pet - p)
    raise GeeExtractionError(f"No formula defined for CLIMATE_DERIVED: {defn.variable_name!r}")


def _apply_conversion(
    raw: float | int | None,
    scale_factor: float | None = None,
    offset: float | None = None,
    normalize_sign: bool = False,
) -> float | int | None:
    """Convert a raw GEE value to physical units.

    Conversion order: multiply by scale_factor → abs() if normalize_sign → add offset.
    ERA5 temperature: raw Kelvin + offset=-273.15 → °C.
    ERA5 PET: raw meters × 1000, abs() → positive mm demand.
    """
    if raw is None:
        return None
    value = float(raw)
    if scale_factor is not None:
        value *= scale_factor
    if normalize_sign:
        value = abs(value)
    if offset is not None:
        value += offset
    return value


def _compute_index(ee: object, image: object, defn: GeeVariableDefinition) -> object:
    """Compute a named spectral index from a temporally reduced image."""
    name = defn.variable_name
    if name == "ndvi":
        return image.normalizedDifference(["B8", "B4"]).rename("ndvi")
    if name == "savi":
        expr = f"((B8 - B4) / (B8 + B4 + {SAVI_L})) * {1.0 + SAVI_L}"
        return image.expression(expr, {"B8": image.select("B8"), "B4": image.select("B4")}).rename("savi")
    if name == "ndmi":
        return image.normalizedDifference(["B8", "B11"]).rename("ndmi")
    raise GeeExtractionError(f"Unsupported derived index: {name!r}")


# ─── Shared helpers ───────────────────────────────────────────────────────────


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


def _sampling_geometry(ee: object, geometry: object, geometry_dict: dict[str, Any], strategy: str) -> object:
    """Return the GEE geometry to use for spatial reduction, based on the variable's sampling strategy.

    "polygon_mean"   — use the full parcel geometry (default, fine-resolution datasets).
    "centroid_sample" — use a Point at the parcel centroid (coarse-resolution ERA5/CHIRPS).
    """
    if strategy == "centroid_sample":
        return _centroid_geometry(ee, geometry_dict)
    return geometry


def _centroid_geometry(ee: object, geometry_dict: dict[str, Any]) -> object:
    """Return a GEE Point at the parcel centroid for coarse-resolution climate sampling.

    ERA5 (~11 km) and CHIRPS (~5.5 km) pixels are often larger than a parcela polygon.
    A point query always intersects exactly one pixel and never returns null.
    Coordinates follow GeoJSON convention: [longitude, latitude].
    """
    geom_type = geometry_dict.get("type", "")
    coords = geometry_dict.get("coordinates", [])

    if geom_type == "Polygon":
        exterior_ring = coords[0] if coords else []
        lon, lat = _ring_centroid(exterior_ring)
    elif geom_type == "MultiPolygon":
        # Use the exterior ring of the largest polygon (by vertex count as proxy for area).
        candidate_rings = [polygon[0] for polygon in coords if polygon]
        if not candidate_rings:
            raise GeeExtractionError("MultiPolygon has no rings: cannot compute centroid")
        exterior_ring = max(candidate_rings, key=len)
        lon, lat = _ring_centroid(exterior_ring)
    else:
        raise GeeExtractionError(f"Cannot compute centroid for geometry type: {geom_type!r}")

    return ee.Geometry.Point([lon, lat])


def _ring_centroid(ring: list) -> tuple[float, float]:
    """Compute the mean of exterior ring vertices as an approximation of the centroid.

    GeoJSON rings close by repeating the first vertex at the end; skip the duplicate.
    """
    if not ring:
        raise GeeExtractionError("Empty ring: cannot compute centroid")
    points = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    if not points:
        raise GeeExtractionError("Ring has only one unique vertex: cannot compute centroid")
    lons = [pt[0] for pt in points]
    lats = [pt[1] for pt in points]
    return sum(lons) / len(lons), sum(lats) / len(lats)


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
