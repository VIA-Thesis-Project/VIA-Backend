"""Unit tests for scripts/run_traceable_e2e_demo.py."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

_SCRIPT_PATH = pathlib.Path(__file__).parents[2] / "scripts" / "run_traceable_e2e_demo.py"
_EXAMPLE_GEOJSON = (
    pathlib.Path(__file__).parents[2] / "examples" / "parcels" / "parcela_humalla.geojson"
)


def _load_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("run_traceable_e2e_demo", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_mod = _load_module()


# ─── GeoJSON loading ──────────────────────────────────────────────────────────


def test_load_geometry_from_file_returns_polygon_from_feature_collection(tmp_path: pathlib.Path) -> None:
    gj = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[-71.0, -13.0], [-70.0, -13.0], [-70.0, -12.0], [-71.0, -12.0], [-71.0, -13.0]]
                    ],
                },
            }
        ],
    }
    f = tmp_path / "test.geojson"
    f.write_text(json.dumps(gj), encoding="utf-8")
    geom = _mod.load_geometry_from_file(str(f))
    assert geom["type"] == "Polygon"


def test_load_geometry_from_file_accepts_plain_polygon(tmp_path: pathlib.Path) -> None:
    gj = {
        "type": "Polygon",
        "coordinates": [
            [[-71.0, -13.0], [-70.0, -13.0], [-70.0, -12.0], [-71.0, -12.0], [-71.0, -13.0]]
        ],
    }
    f = tmp_path / "poly.geojson"
    f.write_text(json.dumps(gj), encoding="utf-8")
    geom = _mod.load_geometry_from_file(str(f))
    assert geom["type"] == "Polygon"


def test_load_geometry_from_file_accepts_multipolygon(tmp_path: pathlib.Path) -> None:
    gj = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[-71.0, -13.0], [-70.0, -13.0], [-70.0, -12.0], [-71.0, -12.0], [-71.0, -13.0]]]
        ],
    }
    f = tmp_path / "multi.geojson"
    f.write_text(json.dumps(gj), encoding="utf-8")
    geom = _mod.load_geometry_from_file(str(f))
    assert geom["type"] == "MultiPolygon"


def test_load_geometry_exits_when_file_not_found() -> None:
    with pytest.raises(SystemExit):
        _mod.load_geometry_from_file("/nonexistent/path/does_not_exist.geojson")


def test_load_geometry_exits_on_invalid_json(tmp_path: pathlib.Path) -> None:
    f = tmp_path / "bad.geojson"
    f.write_text("not valid json {{{{", encoding="utf-8")
    with pytest.raises(SystemExit):
        _mod.load_geometry_from_file(str(f))


def test_load_geometry_exits_on_unsupported_type(tmp_path: pathlib.Path) -> None:
    gj = {"type": "Point", "coordinates": [-71.0, -13.0]}
    f = tmp_path / "pt.geojson"
    f.write_text(json.dumps(gj), encoding="utf-8")
    with pytest.raises(SystemExit):
        _mod.load_geometry_from_file(str(f))


# ─── extract_polygon_or_multipolygon ─────────────────────────────────────────


def test_extract_passes_polygon_through() -> None:
    gj = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    result = _mod.extract_polygon_or_multipolygon(gj)
    assert result is gj


def test_extract_passes_multipolygon_through() -> None:
    gj = {"type": "MultiPolygon", "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]]}
    result = _mod.extract_polygon_or_multipolygon(gj)
    assert result is gj


def test_extract_unwraps_feature() -> None:
    polygon = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    feature = {"type": "Feature", "properties": {}, "geometry": polygon}
    result = _mod.extract_polygon_or_multipolygon(feature)
    assert result is polygon


def test_extract_unwraps_feature_collection() -> None:
    polygon = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": polygon}]}
    result = _mod.extract_polygon_or_multipolygon(fc)
    assert result is polygon


def test_extract_raises_for_empty_feature_collection() -> None:
    fc = {"type": "FeatureCollection", "features": []}
    with pytest.raises(ValueError, match="FeatureCollection"):
        _mod.extract_polygon_or_multipolygon(fc)


def test_extract_raises_for_unknown_type() -> None:
    with pytest.raises(ValueError, match="Tipo GeoJSON no soportado"):
        _mod.extract_polygon_or_multipolygon({"type": "GeometryCollection", "geometries": []})


# ─── validate_geometry ────────────────────────────────────────────────────────


def test_validate_accepts_closed_ring() -> None:
    geom = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
    }
    _mod.validate_geometry(geom)  # should not raise


def test_validate_rejects_open_ring() -> None:
    geom = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]],
    }
    with pytest.raises(ValueError, match="Anillo no cerrado"):
        _mod.validate_geometry(geom)


def test_validate_rejects_ring_with_fewer_than_four_points() -> None:
    geom = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [1.0, 0.0], [0.0, 0.0]]],
    }
    with pytest.raises(ValueError, match="menos de 4 puntos"):
        _mod.validate_geometry(geom)


def test_validate_rejects_non_numeric_coords() -> None:
    geom = {
        "type": "Polygon",
        "coordinates": [[["lon", "lat"], [1.0, 0.0], [1.0, 1.0], ["lon", "lat"]]],
    }
    with pytest.raises(ValueError, match="no numericas"):
        _mod.validate_geometry(geom)


def test_validate_accepts_multipolygon_with_valid_ring() -> None:
    geom = {
        "type": "MultiPolygon",
        "coordinates": [[[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]]],
    }
    _mod.validate_geometry(geom)  # should not raise


# ─── Example GeoJSON file ─────────────────────────────────────────────────────


def test_example_parcela_humalla_file_exists() -> None:
    assert _EXAMPLE_GEOJSON.exists(), f"Missing example file: {_EXAMPLE_GEOJSON}"


def test_example_parcela_humalla_loads_cleanly() -> None:
    geom = _mod.load_geometry_from_file(str(_EXAMPLE_GEOJSON))
    assert geom["type"] in ("Polygon", "MultiPolygon")
    _mod.validate_geometry(geom)


def test_example_parcela_humalla_is_ascii_safe() -> None:
    raw = _EXAMPLE_GEOJSON.read_text(encoding="utf-8")
    raw.encode("ascii")  # raises UnicodeEncodeError if non-ASCII chars present


# ─── _decode_jwt_user_id ──────────────────────────────────────────────────────


def test_decode_jwt_extracts_sub_claim() -> None:
    import base64
    payload = json.dumps({"sub": "user-uuid-1234", "exp": 9999999999})
    encoded = base64.urlsafe_b64encode(payload.encode()).rstrip(b"=").decode()
    token = f"header.{encoded}.signature"
    result = _mod._decode_jwt_user_id(token)
    assert result == "user-uuid-1234"


def test_decode_jwt_returns_none_for_malformed_token() -> None:
    assert _mod._decode_jwt_user_id("not.a.valid.jwt.payload") is None


def test_decode_jwt_returns_none_for_empty_string() -> None:
    result = _mod._decode_jwt_user_id("")
    assert result is None


# ─── safe_json_dump ────────────────────────────────────────────────────────────


def test_safe_json_dump_is_ascii_only() -> None:
    data = {"name": "Evaluacion", "desc": "Prueba diagnostico"}
    result = _mod.safe_json_dump(data)
    result.encode("ascii")


def test_safe_json_dump_serialises_datetime() -> None:
    import datetime
    data = {"ts": datetime.datetime(2025, 1, 15, 10, 30, 0)}
    result = _mod.safe_json_dump(data)
    assert "2025-01-15" in result


def test_safe_json_dump_serialises_uuid() -> None:
    from uuid import UUID
    data = {"id": UUID("12345678-1234-5678-1234-567812345678")}
    result = _mod.safe_json_dump(data)
    assert "12345678-1234-5678-1234-567812345678" in result


# ─── Argument parsing ─────────────────────────────────────────────────────────


def test_parse_args_defaults() -> None:
    args = _mod._parse_args(["--geojson-file", "examples/parcels/parcela_humalla.geojson"])
    assert args.max_rounds == 10
    assert args.pause_seconds == 2.0
    assert not args.dry_run
    assert not args.skip_processing
    assert not args.until_completed
    assert not args.allow_failed
    assert set(args.crops) == set(_mod.DEFAULT_CROPS)


def test_parse_args_allow_failed_flag() -> None:
    args = _mod._parse_args([
        "--geojson-file", "examples/parcels/parcela_humalla.geojson",
        "--allow-failed",
    ])
    assert args.allow_failed is True


def test_parse_args_dry_run_flag() -> None:
    args = _mod._parse_args([
        "--geojson-file", "examples/parcels/parcela_humalla.geojson",
        "--dry-run",
    ])
    assert args.dry_run is True


def test_parse_args_skip_processing_flag() -> None:
    args = _mod._parse_args([
        "--geojson-file", "examples/parcels/parcela_humalla.geojson",
        "--skip-processing",
    ])
    assert args.skip_processing is True


def test_parse_args_custom_crops() -> None:
    args = _mod._parse_args([
        "--geojson-file", "examples/parcels/parcela_humalla.geojson",
        "--crops", "demo_papa", "demo_maiz",
    ])
    assert args.crops == ["demo_papa", "demo_maiz"]


def test_parse_args_custom_dates() -> None:
    args = _mod._parse_args([
        "--geojson-file", "examples/parcels/parcela_humalla.geojson",
        "--start-date", "2024-03-01",
        "--end-date", "2024-08-31",
    ])
    assert args.start_date == "2024-03-01"
    assert args.end_date == "2024-08-31"


# ─── ARTIFACT_NAMES completeness ─────────────────────────────────────────────


def test_artifact_names_has_all_expected_keys() -> None:
    expected_keys = {
        "input", "auth", "parcel_api", "parcel_db", "rulebooks",
        "rulebook_details", "extraction_bindings", "evaluation_api",
        "outbox_timeline", "saga_timeline", "agroenv_vector", "agroenv_entries",
        "mcda_results", "criterion_details", "final_api", "report",
    }
    assert set(_mod.ARTIFACT_NAMES.keys()) == expected_keys


def test_artifact_names_values_are_unique() -> None:
    values = list(_mod.ARTIFACT_NAMES.values())
    assert len(values) == len(set(values))


def test_artifact_names_have_correct_extensions() -> None:
    json_keys = {
        "input", "auth", "parcel_api", "parcel_db", "rulebooks",
        "rulebook_details", "extraction_bindings", "evaluation_api",
        "outbox_timeline", "saga_timeline", "agroenv_vector", "agroenv_entries",
        "mcda_results", "criterion_details", "final_api",
    }
    for key in json_keys:
        assert _mod.ARTIFACT_NAMES[key].endswith(".json") or _mod.ARTIFACT_NAMES[key].endswith(".geojson"), (
            f"Key '{key}' should point to a JSON/GeoJSON file"
        )
    assert _mod.ARTIFACT_NAMES["report"].endswith(".md")


# ─── DEFAULT_CROPS ─────────────────────────────────────────────────────────────


def test_default_crops_contains_five_demo_crops() -> None:
    assert len(_mod.DEFAULT_CROPS) == 5
    assert "demo_papa" in _mod.DEFAULT_CROPS
    assert "demo_maiz" in _mod.DEFAULT_CROPS
    assert "demo_quinua" in _mod.DEFAULT_CROPS
    assert "demo_palta" in _mod.DEFAULT_CROPS
    assert "demo_arandano" in _mod.DEFAULT_CROPS


# ─── No hardcoded credentials / coordinates in script ─────────────────────────


def test_no_hardcoded_db_credentials_in_script() -> None:
    source = _SCRIPT_PATH.read_text(encoding="utf-8")
    # Check for actual secret material only — NOT placeholder examples in
    # docstrings (e.g. "$env:VIA_ADMIN_PASSWORD=...") which are legitimate usage docs.
    forbidden = ["BEGIN RSA", "BEGIN EC"]
    for pattern in forbidden:
        assert pattern.lower() not in source.lower(), (
            f"Script contains hardcoded sensitive string: {pattern!r}"
        )


def test_no_hardcoded_parcel_coordinates_in_demo_script() -> None:
    source = _SCRIPT_PATH.read_text(encoding="utf-8")
    forbidden_coords = [
        "-71.6750",
        "-71.6650",
        "-13.6180",
        "-13.6090",
    ]
    for coord in forbidden_coords:
        assert coord not in source, (
            f"Script contains hardcoded parcel coordinate: {coord!r}. "
            "Parcel coordinates must be ONLY in the GeoJSON example files."
        )


# ─── write_artifact ────────────────────────────────────────────────────────────


def test_write_artifact_creates_json_file(tmp_path: pathlib.Path) -> None:
    data = {"foo": "bar", "num": 42}
    _mod.write_artifact(tmp_path, "test.json", data)
    out = (tmp_path / "test.json").read_text(encoding="utf-8")
    parsed = json.loads(out)
    assert parsed["foo"] == "bar"


def test_write_artifact_creates_geojson_file(tmp_path: pathlib.Path) -> None:
    geom = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    _mod.write_artifact(tmp_path, "00_input.geojson", geom)
    out = json.loads((tmp_path / "00_input.geojson").read_text(encoding="utf-8"))
    assert out["type"] == "Polygon"


def test_write_artifact_json_is_ascii_safe(tmp_path: pathlib.Path) -> None:
    data = {"name": "Evaluacion diagnostico"}
    _mod.write_artifact(tmp_path, "out.json", data)
    raw = (tmp_path / "out.json").read_bytes()
    raw.decode("ascii")


# ─── generate_trace_report ────────────────────────────────────────────────────


def test_generate_trace_report_creates_markdown_file(tmp_path: pathlib.Path) -> None:
    ctx = {
        "geojson_file": "examples/parcels/parcela_humalla.geojson",
        "crops": ["demo_papa", "demo_maiz"],
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "parcel_id": "parcel-uuid-test",
        "evaluation_id": "eval-uuid-test",
        "user_id": "user-uuid-test",
        "parcel_snapshot": {"area_m2": 1000000.0, "created_at": "2025-01-01T10:00:00"},
        "rulebooks": [{"id": "rb-1", "crop_id": "demo_papa", "version": 1, "status": "ACTIVE"}],
        "rulebook_details": {
            "criteria_by_crop": {},
            "phases_by_crop": {},
            "requirements_by_crop": {},
            "extraction_bindings": [],
        },
        "outbox_timeline": {"before": [], "after": []},
        "saga_timeline": {
            "before": {},
            "after": {},
            "transitions": [],
            "final_status": "RECOMENDACION_COMPLETADA",
        },
        "agroenv_vector": None,
        "agroenv_entries": [],
        "eval_results": [],
        "criterion_details": [],
        "final_api_result": {"status": "COMPLETED", "results": []},
        "final_status": "RECOMENDACION_COMPLETADA",
    }
    _mod.generate_trace_report(tmp_path, ctx)
    report = (tmp_path / _mod.ARTIFACT_NAMES["report"]).read_text(encoding="utf-8")
    assert "VIA" in report
    assert "parcel-uuid-test" in report
    assert "eval-uuid-test" in report
    assert "ADVERTENCIA" in report or "diagnostico" in report.lower()


def test_generate_trace_report_is_ascii_safe(tmp_path: pathlib.Path) -> None:
    ctx = {
        "geojson_file": "file.geojson",
        "crops": ["demo_maiz"],
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "parcel_id": "p-1",
        "evaluation_id": "e-1",
        "user_id": "u-1",
        "parcel_snapshot": {},
        "rulebooks": [],
        "rulebook_details": {"criteria_by_crop": {}, "phases_by_crop": {}, "requirements_by_crop": {}, "extraction_bindings": []},
        "outbox_timeline": {"before": [], "after": []},
        "saga_timeline": {"before": {}, "after": {}, "transitions": [], "final_status": "FALLIDA"},
        "agroenv_vector": None,
        "agroenv_entries": [],
        "eval_results": [],
        "criterion_details": [],
        "final_api_result": {},
        "final_status": "FALLIDA",
    }
    _mod.generate_trace_report(tmp_path, ctx)
    raw = (tmp_path / _mod.ARTIFACT_NAMES["report"]).read_bytes()
    raw.decode("ascii")


def test_generate_trace_report_contains_disclaimer(tmp_path: pathlib.Path) -> None:
    ctx = {
        "geojson_file": "file.geojson",
        "crops": [],
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "parcel_id": "p-1",
        "evaluation_id": "e-1",
        "user_id": "u-1",
        "parcel_snapshot": {},
        "rulebooks": [],
        "rulebook_details": {"criteria_by_crop": {}, "phases_by_crop": {}, "requirements_by_crop": {}, "extraction_bindings": []},
        "outbox_timeline": {"before": [], "after": []},
        "saga_timeline": {"before": {}, "after": {}, "transitions": [], "final_status": None},
        "agroenv_vector": None,
        "agroenv_entries": [],
        "eval_results": [],
        "criterion_details": [],
        "final_api_result": {},
        "final_status": None,
    }
    _mod.generate_trace_report(tmp_path, ctx)
    report = (tmp_path / _mod.ARTIFACT_NAMES["report"]).read_text(encoding="utf-8")
    disclaimer_lower = _mod.DEMO_DISCLAIMER.lower()
    assert "diagnostico" in disclaimer_lower or "fixture" in disclaimer_lower
    assert "diagnostico" in report.lower() or "fixture" in report.lower()


# ─── _failure_cause_from_timeline ────────────────────────────────────────────


def test_failure_cause_extracted_from_fallida_transition() -> None:
    timeline = {
        "transitions": [
            {"from_status": "EXTRACCION_COMPLETADA", "to_status": "FALLIDA", "failure_cause": "penalty_factor is required for PENALIZE policy"},
        ],
        "final_status": "FALLIDA",
    }
    cause = _mod._failure_cause_from_timeline(timeline)
    assert cause == "penalty_factor is required for PENALIZE policy"


def test_failure_cause_returns_none_when_no_fallida_transition() -> None:
    timeline = {
        "transitions": [
            {"from_status": "INICIADA", "to_status": "EXTRACCION_COMPLETADA", "failure_cause": None},
        ],
        "final_status": "EXTRACCION_COMPLETADA",
    }
    cause = _mod._failure_cause_from_timeline(timeline)
    assert cause is None


def test_failure_cause_returns_none_for_empty_transitions() -> None:
    assert _mod._failure_cause_from_timeline({"transitions": [], "final_status": "FALLIDA"}) is None


# ─── _print_summary FALLIDA handling ─────────────────────────────────────────


def test_print_summary_exits_with_code_1_when_saga_is_fallida(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
) -> None:
    """When saga=FALLIDA, _print_summary must exit(1) by default."""
    saga_timeline = {
        "transitions": [
            {"to_status": "FALLIDA", "failure_cause": "penalty_factor is required for PENALIZE policy"},
        ],
        "final_status": "FALLIDA",
    }
    with pytest.raises(SystemExit) as exc_info:
        _mod._print_summary(
            parcel_id="p-1",
            evaluation_id="e-1",
            artifacts_dir=tmp_path,
            final_api_result={},
            saga_timeline=saga_timeline,
            allow_failed=False,
        )
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "[ERROR]" in captured.out
    assert "FALLIDA" in captured.out


def test_print_summary_shows_failure_cause(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
) -> None:
    saga_timeline = {
        "transitions": [
            {"to_status": "FALLIDA", "failure_cause": "penalty_factor is required for PENALIZE policy"},
        ],
        "final_status": "FALLIDA",
    }
    with pytest.raises(SystemExit):
        _mod._print_summary("p-1", "e-1", tmp_path, {}, saga_timeline, allow_failed=False)
    captured = capsys.readouterr()
    assert "penalty_factor is required for PENALIZE policy" in captured.out


def test_print_summary_does_not_exit_when_allow_failed_is_true(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
) -> None:
    saga_timeline = {
        "transitions": [{"to_status": "FALLIDA", "failure_cause": "some error"}],
        "final_status": "FALLIDA",
    }
    # Should not raise SystemExit
    _mod._print_summary("p-1", "e-1", tmp_path, {}, saga_timeline, allow_failed=True)
    captured = capsys.readouterr()
    assert "[ERROR]" in captured.out


def test_print_summary_prints_ok_when_recomendacion_completada(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
) -> None:
    saga_timeline = {"transitions": [], "final_status": "RECOMENDACION_COMPLETADA"}
    _mod._print_summary("p-1", "e-1", tmp_path, {"results": []}, saga_timeline)
    captured = capsys.readouterr()
    assert "[OK]" in captured.out
    assert "[ERROR]" not in captured.out


def test_print_summary_prints_ok_when_evaluacion_completada(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
) -> None:
    saga_timeline = {"transitions": [], "final_status": "EVALUACION_COMPLETADA"}
    _mod._print_summary("p-1", "e-1", tmp_path, {"results": []}, saga_timeline)
    captured = capsys.readouterr()
    assert "[OK]" in captured.out


def test_print_summary_never_says_ok_when_fallida(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
) -> None:
    """Regression: the old code printed [OK] when status was in _TERMINAL_STATUSES,
    which includes FALLIDA."""
    saga_timeline = {"transitions": [], "final_status": "FALLIDA"}
    with pytest.raises(SystemExit):
        _mod._print_summary("p-1", "e-1", tmp_path, {}, saga_timeline, allow_failed=False)
    captured = capsys.readouterr()
    assert "[OK]" not in captured.out
    assert "[ERROR]" in captured.out


def test_print_summary_shows_artifact_path_on_failure(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
) -> None:
    saga_timeline = {"transitions": [], "final_status": "FALLIDA"}
    with pytest.raises(SystemExit):
        _mod._print_summary("p-1", "e-1", tmp_path, {}, saga_timeline, allow_failed=False)
    captured = capsys.readouterr()
    assert str(tmp_path) in captured.out
