"""Manual Google Earth Engine smoke test for VIA extraction."""

from __future__ import annotations

import argparse
import json
from uuid import UUID

from via.bounded_contexts.agroenv_extraction.application.ports import ExtractionRequest, normalize_parcel_geometry
from via.bounded_contexts.agroenv_extraction.infrastructure.gee_client import GeeExtractionClient, GeeExtractionError
from via.config import ConfigurationError, load_settings


DEFAULT_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[-76.01, -12.01], [-76.01, -12.011], [-76.009, -12.011], [-76.009, -12.01], [-76.01, -12.01]]],
}


def main() -> int:
    """Run one real GEE extraction using local environment credentials."""

    parser = _parser()
    args = parser.parse_args()
    try:
        settings = load_settings()
        request = _request_from_args(args)
        result = GeeExtractionClient(settings=settings).extract_variable(request)
    except ConfigurationError as exc:
        print(f"GEE smoke test configuration error: {exc}")
        return 2
    except GeeExtractionError as exc:
        print(f"GEE smoke test extraction error: {exc}")
        return 3
    except Exception as exc:
        print(f"GEE smoke test unexpected error: {exc}")
        return 4

    if result is None:
        print("GEE smoke test completed: no data returned for the requested parcel/period.")
        return 0
    print(
        json.dumps(
            {
                "status": "ok",
                "dataset_key": args.dataset_key,
                "band": args.band,
                "reducer": args.reducer,
                "period": {"start": args.start, "end": args.end},
                "value": result.value,
                "source": result.source,
                "extraction_date": result.extraction_date.isoformat(),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a manual VIA Google Earth Engine smoke extraction. Requires GEE_ENABLED=True credentials in env.",
    )
    parser.add_argument("--dataset-key", required=True, help="Earth Engine ImageCollection id, e.g. COPERNICUS/S2_SR_HARMONIZED.")
    parser.add_argument("--band", required=True, help="Band to reduce, e.g. B8.")
    parser.add_argument("--start", required=True, help="Inclusive period start date YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="Exclusive period end date YYYY-MM-DD.")
    parser.add_argument("--reducer", default="mean", choices=["mean", "median", "min", "max"], help="Spatial and temporal reducer.")
    parser.add_argument("--scale", type=float, default=30.0, help="GEE scale in meters.")
    parser.add_argument("--geometry-json", help="Small GeoJSON Polygon/MultiPolygon string. Defaults to a tiny Lima-area polygon.")
    parser.add_argument("--quality-mask-json", help="Optional quality mask JSON, e.g. {\"band\":\"QA60\",\"equals\":0}.")
    parser.add_argument("--fallback-allowed", action="store_true", help="Allow no-data result to return None.")
    return parser


def _request_from_args(args: argparse.Namespace) -> ExtractionRequest:
    geometry = normalize_parcel_geometry(json.loads(args.geometry_json) if args.geometry_json else DEFAULT_GEOMETRY)
    quality_mask = json.loads(args.quality_mask_json) if args.quality_mask_json else None
    return ExtractionRequest(
        parcel_id=UUID("00000000-0000-0000-0000-000000000001"),
        parcel_geometry=geometry,
        temporal_window={"start": args.start, "end": args.end},
        variable_name="gee_smoke_value",
        criterion_id="gee_smoke",
        crop_id="gee_smoke",
        phase_id="gee_smoke",
        dataset_key=args.dataset_key,
        band=args.band,
        unit="raw",
        temporal_resolution="manual",
        spatial_resolution=None,
        scale=args.scale,
        reducer=args.reducer,
        aggregation_method=args.reducer,
        quality_mask=quality_mask,
        fallback_allowed=args.fallback_allowed,
        period_key=f"{args.start}:{args.end}",
        period_start=args.start,
        period_end=args.end,
    )


if __name__ == "__main__":
    raise SystemExit(main())
