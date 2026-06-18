"""Traceable E2E demo for VIA - runs the full evaluation pipeline with artifacts.

Usage (PowerShell):
    $env:DATABASE_URL="postgresql+psycopg2://via_user:via_password@localhost:5433/via_test"
    $env:VIA_API_BASE_URL="http://127.0.0.1:8000"
    $env:VIA_ADMIN_EMAIL="admin@via.local"
    $env:VIA_ADMIN_PASSWORD="Admin123456"
    $env:GEE_PROJECT="via-tp"
    $env:GEE_SERVICE_ACCOUNT="via-gee-extractor@via-tp.iam.gserviceaccount.com"
    $env:GEE_PRIVATE_KEY_FILE="C:/keys/gee-key.json"

    python scripts/run_traceable_e2e_demo.py \\
        --geojson-file examples/parcels/parcela_humalla.geojson \\
        --start-date 2025-01-01 \\
        --end-date 2025-12-31 \\
        --max-rounds 10 \\
        --pause-seconds 1 \\
        --until-completed

To change the parcel location, edit or replace the GeoJSON file in
examples/parcels/. Do NOT modify this script to change coordinates.

IMPORTANT: Rulebooks must already be seeded before running this script.
   Run: python scripts/seed_diagnostic_rulebooks.py

ADVERTENCIA: Los rulebooks diagnosticos son fixtures sinteticos para
validacion funcional. No son datos INIA ni guia agronomica real.
"""

from __future__ import annotations

import argparse
import base64
import datetime
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from via.config import load_settings

_SCRIPTS_DIR = pathlib.Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from process_outbox_for_evaluation import (  # noqa: E402
    _TERMINAL_STATUSES,
    _build_relay,
    run_rounds,
)
from seed_demo_rulebooks import DEMO_CROPS  # noqa: E402


# ─── Constants ────────────────────────────────────────────────────────────────

DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_CROPS: list[str] = list(DEMO_CROPS.keys())
DEFAULT_GEOJSON_FILE = str(
    pathlib.Path(__file__).parents[1] / "examples" / "parcels" / "parcela_humalla.geojson"
)
ARTIFACTS_BASE = pathlib.Path(__file__).parents[1] / "artifacts" / "demo_runs"

DEMO_DISCLAIMER = (
    "ADVERTENCIA: Los rulebooks diagnosticos son fixtures sinteticos para "
    "validacion funcional. No son datos INIA ni guia agronomica real."
)

ARTIFACT_NAMES = {
    "input": "00_input.geojson",
    "auth": "01_auth_summary.json",
    "parcel_api": "02_parcel_api_response.json",
    "parcel_db": "03_parcel_db_snapshot.json",
    "rulebooks": "04_rulebooks_used.json",
    "rulebook_details": "05_rulebook_criteria_phases_requirements.json",
    "extraction_bindings": "06_extraction_bindings.json",
    "evaluation_api": "07_evaluation_api_response.json",
    "outbox_timeline": "08_outbox_timeline.json",
    "saga_timeline": "09_saga_status_timeline.json",
    "agroenv_vector": "10_agroenv_vector.json",
    "agroenv_entries": "11_agroenv_variable_entries.json",
    "mcda_results": "12_mcda_results.json",
    "criterion_details": "13_mcda_criterion_details.json",
    "final_api": "14_final_api_result.json",
    "report": "trace_report.md",
}


# ─── Argument parsing ─────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_traceable_e2e_demo.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--geojson-file",
        default=DEFAULT_GEOJSON_FILE,
        metavar="PATH",
        help=f"GeoJSON file with parcel geometry (default: {DEFAULT_GEOJSON_FILE})",
    )
    parser.add_argument(
        "--crops",
        nargs="+",
        default=DEFAULT_CROPS,
        metavar="CROP_ID",
        help="Crop IDs to evaluate (default: 5 diagnostic demo crops)",
    )
    parser.add_argument(
        "--start-date",
        default="2025-01-01",
        metavar="YYYY-MM-DD",
        help="Start of the temporal evaluation window (default: 2025-01-01)",
    )
    parser.add_argument(
        "--end-date",
        default="2025-12-31",
        metavar="YYYY-MM-DD",
        help="End of the temporal evaluation window (default: 2025-12-31)",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=10,
        metavar="N",
        help="Maximum outbox processing rounds (default: 10)",
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=2.0,
        metavar="N",
        help="Pause between processing rounds in seconds (default: 2.0)",
    )
    parser.add_argument(
        "--until-completed",
        action="store_true",
        help="Stop processing when evaluation reaches a terminal status",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and config without creating any resources",
    )
    parser.add_argument(
        "--skip-processing",
        action="store_true",
        help="Create parcel/evaluation but skip outbox processing",
    )
    parser.add_argument(
        "--allow-failed",
        action="store_true",
        help="Do not exit with error when the evaluation saga finishes FALLIDA",
    )
    return parser.parse_args(argv)


# ─── Environment validation ───────────────────────────────────────────────────


def _check_env() -> None:
    required = [
        "DATABASE_URL",
        "VIA_ADMIN_EMAIL",
        "VIA_ADMIN_PASSWORD",
        "GEE_PROJECT",
        "GEE_SERVICE_ACCOUNT",
        "GEE_PRIVATE_KEY_FILE",
    ]
    missing = [v for v in required if not os.environ.get(v, "").strip()]
    if missing:
        print(
            f"ERROR: Variables de entorno requeridas no configuradas: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url.startswith("postgresql+psycopg2://"):
        print("ERROR: DATABASE_URL debe usar el esquema postgresql+psycopg2://", file=sys.stderr)
        sys.exit(1)


# ─── GeoJSON helpers ──────────────────────────────────────────────────────────


def load_geometry_from_file(path: str) -> dict[str, Any]:
    """Load and validate a Polygon or MultiPolygon from a GeoJSON file."""
    p = pathlib.Path(path)
    if not p.exists():
        print(f"ERROR: Archivo GeoJSON no encontrado: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        with open(p, encoding="utf-8") as fh:
            raw = json.load(fh)
    except json.JSONDecodeError as exc:
        print(f"ERROR: Archivo GeoJSON invalido: {exc}", file=sys.stderr)
        sys.exit(1)
    try:
        geometry = extract_polygon_or_multipolygon(raw)
        validate_geometry(geometry)
    except ValueError as exc:
        print(f"ERROR: Geometria invalida en {path}: {exc}", file=sys.stderr)
        sys.exit(1)
    return geometry


def extract_polygon_or_multipolygon(geojson: dict[str, Any]) -> dict[str, Any]:
    """Return a Polygon or MultiPolygon geometry dict from any GeoJSON object."""
    gtype = geojson.get("type", "")
    if gtype in ("Polygon", "MultiPolygon"):
        return geojson
    if gtype == "Feature":
        return extract_polygon_or_multipolygon(geojson.get("geometry") or {})
    if gtype == "FeatureCollection":
        for feature in geojson.get("features", []):
            fg = (feature.get("geometry") or {}).get("type", "")
            if fg in ("Polygon", "MultiPolygon"):
                return feature["geometry"]
        raise ValueError(
            "FeatureCollection no contiene ninguna feature con Polygon o MultiPolygon."
        )
    raise ValueError(
        f"Tipo GeoJSON no soportado: '{gtype}'. "
        "Se requiere Polygon, MultiPolygon o FeatureCollection."
    )


def validate_geometry(geometry: dict[str, Any]) -> None:
    """Validate that a geometry dict has proper structure for the VIA API."""
    gtype = geometry.get("type", "")
    if gtype not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"Tipo invalido para validacion: '{gtype}'.")
    coords = geometry.get("coordinates")
    if not coords:
        raise ValueError("Geometria sin coordenadas.")
    rings = coords if gtype == "MultiPolygon" else [coords]
    for polygon in rings:
        if polygon:
            _validate_ring(polygon[0])


def _validate_ring(ring: list) -> None:
    if len(ring) < 4:
        raise ValueError(f"Anillo con menos de 4 puntos ({len(ring)}).")
    for coord in ring:
        if len(coord) < 2:
            raise ValueError(f"Coordenada con menos de 2 valores: {coord}.")
        if not isinstance(coord[0], (int, float)) or not isinstance(coord[1], (int, float)):
            raise ValueError(f"Coordenadas no numericas: {coord}.")
    if list(ring[0]) != list(ring[-1]):
        raise ValueError(
            f"Anillo no cerrado: primer punto {ring[0]} != ultimo punto {ring[-1]}."
        )


# ─── HTTP helpers ─────────────────────────────────────────────────────────────


def _http_post_json(
    url: str,
    payload: dict,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            body = {"detail": exc.reason}
        return exc.code, body


def _http_get_json(
    url: str,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    req_headers: dict[str, str] = {}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers, method="GET")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            body = {"detail": exc.reason}
        return exc.code, body


# ─── JWT / auth helpers ───────────────────────────────────────────────────────


def _decode_jwt_user_id(token: str) -> str | None:
    """Extract user_id (sub claim) from a JWT without verifying the signature."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        segment = parts[1]
        padding = 4 - len(segment) % 4
        if padding != 4:
            segment += "=" * padding
        segment = segment.replace("-", "+").replace("_", "/")
        payload = json.loads(base64.b64decode(segment).decode("utf-8"))
        return str(payload.get("sub", ""))
    except Exception:
        return None


def authenticate(base_url: str, email: str, password: str) -> tuple[str, str]:
    """Login and return (access_token, user_id). Exits on failure."""
    url = f"{base_url}/auth/login"
    status, body = _http_post_json(url, {"email": email, "password": password})
    if status != 200:
        print(
            f"ERROR: Login fallido (HTTP {status}): {body.get('detail', body)}",
            file=sys.stderr,
        )
        sys.exit(1)
    token = body.get("access_token", "")
    if not token:
        print("ERROR: Login exitoso pero sin access_token en la respuesta.", file=sys.stderr)
        sys.exit(1)
    user_id = _decode_jwt_user_id(token) or ""
    print(f"[OK] Autenticado como {email}")
    return token, user_id


# ─── API call functions ───────────────────────────────────────────────────────


def create_parcel(
    base_url: str,
    token: str,
    geometry: dict,
    name: str = "Demo E2E VIA",
) -> dict:
    """POST /parcelas and return the response body. Exits on failure."""
    url = f"{base_url}/parcelas"
    payload = {
        "geometry": geometry,
        "metadata": {
            "name": name,
            "description": "Parcela de evaluacion E2E - Demo VIA (fixture diagnostico)",
            "crs": "EPSG:4326",
        },
    }
    status, body = _http_post_json(url, payload, {"Authorization": f"Bearer {token}"})
    if status != 201:
        print(
            f"ERROR: POST /parcelas fallido (HTTP {status}): {body.get('detail', body)}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"[OK] Parcela creada: {body.get('id', '?')}")
    return body


def start_evaluation(
    base_url: str,
    token: str,
    parcel_id: str,
    user_id: str,
    crop_ids: list[str],
    start_date: str,
    end_date: str,
) -> dict:
    """POST /evaluaciones and return the response body. Exits on failure."""
    url = f"{base_url}/evaluaciones"
    payload = {
        "parcel_id": parcel_id,
        "requested_by": user_id,
        "crop_candidates": crop_ids,
        "temporal_window": {"start_date": start_date, "end_date": end_date},
    }
    status, body = _http_post_json(url, payload, {"Authorization": f"Bearer {token}"})
    if status != 202:
        print(
            f"ERROR: POST /evaluaciones fallido (HTTP {status}): {body.get('detail', body)}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"[OK] Evaluacion iniciada: {body.get('evaluation_id', '?')}")
    return body


def get_mcda_result(base_url: str, token: str, evaluation_id: str) -> dict:
    """GET /evaluaciones/{id}/resultado-mcda and return the body."""
    url = f"{base_url}/evaluaciones/{evaluation_id}/resultado-mcda"
    status, body = _http_get_json(url, {"Authorization": f"Bearer {token}"})
    if status != 200:
        print(f"AVISO: GET resultado-mcda retorno HTTP {status}")
    return body


# ─── DB query helpers ─────────────────────────────────────────────────────────


class _SafeEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def _row_to_dict(row: Any) -> dict:
    if row is None:
        return {}
    result: dict = {}
    for key, val in row.items():
        if isinstance(val, (datetime.datetime, datetime.date)):
            result[key] = val.isoformat()
        elif isinstance(val, UUID):
            result[key] = str(val)
        elif isinstance(val, Decimal):
            result[key] = float(val)
        else:
            result[key] = val
    return result


def verify_active_rulebooks(session_factory: Any, crop_ids: list[str]) -> list[dict]:
    """Return active rulebooks for crop_ids, or exit with a clear error."""
    with session_factory() as session:
        rows = session.execute(
            text(
                "SELECT id, crop_id, version, status, created_at "
                "FROM transactional.rulebooks "
                "WHERE crop_id IN :crop_ids AND status = 'ACTIVE'"
            ).bindparams(bindparam("crop_ids", expanding=True)),
            {"crop_ids": crop_ids},
        ).mappings().all()
    found = {row["crop_id"] for row in rows}
    missing = set(crop_ids) - found
    if missing:
        print(
            f"ERROR: No se encontraron rulebooks ACTIVE para: {', '.join(sorted(missing))}",
            file=sys.stderr,
        )
        print(
            "       Ejecuta primero: python scripts/seed_diagnostic_rulebooks.py",
            file=sys.stderr,
        )
        sys.exit(1)
    return [_row_to_dict(row) for row in rows]


def query_rulebook_details(session_factory: Any, crop_ids: list[str]) -> dict:
    """Query criteria, phases, and requirements for the active rulebooks."""
    try:
        with session_factory() as session:
            rb_rows = session.execute(
                text(
                    "SELECT id, crop_id, version "
                    "FROM transactional.rulebooks "
                    "WHERE crop_id IN :crop_ids AND status = 'ACTIVE'"
                ).bindparams(bindparam("crop_ids", expanding=True)),
                {"crop_ids": crop_ids},
            ).mappings().all()
            rb_id_to_crop = {str(row["id"]): row["crop_id"] for row in rb_rows}
            rb_ids = list(rb_id_to_crop.keys())
            if not rb_ids:
                return {}

            crit_rows = session.execute(
                text(
                    "SELECT id, rulebook_id, name, is_critical, critical_policy, "
                    "penalty_factor, ahp_weight, doc_source, technical_notes "
                    "FROM transactional.rulebook_criteria "
                    "WHERE rulebook_id IN :rb_ids"
                ).bindparams(bindparam("rb_ids", expanding=True)),
                {"rb_ids": rb_ids},
            ).mappings().all()

            phase_rows = session.execute(
                text(
                    "SELECT id, rulebook_id, name, duration_days, sequence_order "
                    "FROM transactional.rulebook_phases "
                    "WHERE rulebook_id IN :rb_ids"
                ).bindparams(bindparam("rb_ids", expanding=True)),
                {"rb_ids": rb_ids},
            ).mappings().all()

            crit_ids = [str(row["id"]) for row in crit_rows]
            req_rows = (
                session.execute(
                    text(
                        "SELECT id, criterion_id, phase_id, membership_fn, "
                        "phase_weight, temporal_periods, extraction_binding "
                        "FROM transactional.rulebook_phase_requirements "
                        "WHERE criterion_id IN :crit_ids"
                    ).bindparams(bindparam("crit_ids", expanding=True)),
                    {"crit_ids": crit_ids},
                ).mappings().all()
                if crit_ids
                else []
            )

        crit_id_to_name = {str(r["id"]): r["name"] for r in crit_rows}
        phase_id_to_name = {str(r["id"]): r["name"] for r in phase_rows}

        criteria_by_crop: dict = {}
        phases_by_crop: dict = {}
        requirements_by_crop: dict = {}

        for rb_id, crop_id in rb_id_to_crop.items():
            criteria_by_crop[crop_id] = [
                _row_to_dict(r) for r in crit_rows if str(r["rulebook_id"]) == rb_id
            ]
            phases_by_crop[crop_id] = sorted(
                [_row_to_dict(r) for r in phase_rows if str(r["rulebook_id"]) == rb_id],
                key=lambda p: p.get("sequence_order", 0),
            )
            crop_crit_ids = {str(r["id"]) for r in crit_rows if str(r["rulebook_id"]) == rb_id}
            reqs = []
            for r in req_rows:
                if str(r["criterion_id"]) in crop_crit_ids:
                    d = _row_to_dict(r)
                    d["criterion_name"] = crit_id_to_name.get(str(r["criterion_id"]), "?")
                    d["phase_name"] = phase_id_to_name.get(str(r["phase_id"]), "?")
                    reqs.append(d)
            requirements_by_crop[crop_id] = reqs

        seen: set = set()
        unique_bindings: list = []
        for r in req_rows:
            eb = r.get("extraction_binding") or {}
            key = json.dumps(eb, sort_keys=True)
            if key not in seen:
                seen.add(key)
                unique_bindings.append(eb)

        return {
            "criteria_by_crop": criteria_by_crop,
            "phases_by_crop": phases_by_crop,
            "requirements_by_crop": requirements_by_crop,
            "extraction_bindings": unique_bindings,
        }
    except Exception as exc:
        print(f"AVISO: Error consultando detalles de rulebooks: {exc}")
        return {}


def query_parcel_snapshot(session_factory: Any, parcel_id: str) -> dict:
    try:
        with session_factory() as session:
            row = session.execute(
                text(
                    "SELECT id, owner_id, metadata, "
                    "ST_Area(geometry::geography) AS area_m2, "
                    "ST_AsGeoJSON(geometry) AS geom_json, "
                    "created_at "
                    "FROM transactional.parcels WHERE id = :pid"
                ),
                {"pid": parcel_id},
            ).mappings().first()
        return _row_to_dict(row) if row else {}
    except Exception as exc:
        print(f"AVISO: No se pudo consultar parcela en DB: {exc}")
        return {}


def snapshot_outbox(session_factory: Any, evaluation_id: UUID) -> list[dict]:
    try:
        with session_factory() as session:
            rows = session.execute(
                text(
                    "SELECT id, message_type, message_kind, status, retry_count, "
                    "last_error, correlation_id, created_at, dispatched_at "
                    "FROM transactional.outbox_messages "
                    "WHERE correlation_id = :eid "
                    "ORDER BY created_at"
                ),
                {"eid": str(evaluation_id)},
            ).mappings().all()
        return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        print(f"AVISO: Error consultando outbox: {exc}")
        return []


def snapshot_saga(session_factory: Any, evaluation_id: UUID) -> dict:
    try:
        with session_factory() as session:
            row = session.execute(
                text(
                    "SELECT id, parcel_id, requested_by, crop_candidates, "
                    "temporal_window, status, created_at, updated_at "
                    "FROM transactional.evaluation_sagas WHERE id = :eid"
                ),
                {"eid": str(evaluation_id)},
            ).mappings().first()
        return _row_to_dict(row) if row else {}
    except Exception as exc:
        print(f"AVISO: Error consultando saga: {exc}")
        return {}


def query_saga_transitions(session_factory: Any, evaluation_id: UUID) -> list[dict]:
    try:
        with session_factory() as session:
            rows = session.execute(
                text(
                    "SELECT from_status, to_status, triggered_by, occurred_at, failure_cause "
                    "FROM transactional.saga_transitions "
                    "WHERE saga_id = :eid ORDER BY occurred_at"
                ),
                {"eid": str(evaluation_id)},
            ).mappings().all()
        return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        print(f"AVISO: Error consultando transiciones de saga: {exc}")
        return []


def query_agroenv_vector(session_factory: Any, evaluation_id: UUID) -> dict:
    try:
        with session_factory() as session:
            row = session.execute(
                text(
                    "SELECT id, evaluation_id, parcel_id, temporal_window, extracted_at "
                    "FROM transactional.agroenv_vectors WHERE evaluation_id = :eid"
                ),
                {"eid": str(evaluation_id)},
            ).mappings().first()
        return _row_to_dict(row) if row else {}
    except Exception as exc:
        print(f"AVISO: Error consultando vector agroambiental: {exc}")
        return {}


def query_agroenv_variable_entries(session_factory: Any, vector_id: str) -> list[dict]:
    try:
        with session_factory() as session:
            rows = session.execute(
                text(
                    "SELECT id, variable_name, criterion_id, crop_id, phase_id, "
                    "dataset_key, band, unit, temporal_resolution, scale, reducer, "
                    "aggregation_method, fallback_allowed, value, source, "
                    "extraction_date, period_key, status "
                    "FROM transactional.agroenv_variable_entries "
                    "WHERE vector_id = :vid ORDER BY crop_id, criterion_id, period_key"
                ),
                {"vid": vector_id},
            ).mappings().all()
        return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        print(f"AVISO: Error consultando variable entries: {exc}")
        return []


def query_evaluation_results(session_factory: Any, evaluation_id: UUID) -> list[dict]:
    try:
        with session_factory() as session:
            rows = session.execute(
                text(
                    "SELECT id, evaluation_id, crop_id, score, calc_condition, "
                    "viability_category, rank_position, rulebook_version, "
                    "entropy_used, computed_at "
                    "FROM transactional.evaluation_results "
                    "WHERE evaluation_id = :eid ORDER BY rank_position NULLS LAST"
                ),
                {"eid": str(evaluation_id)},
            ).mappings().all()
        return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        print(f"AVISO: Error consultando evaluation results: {exc}")
        return []


def query_criterion_details(session_factory: Any, result_ids: list[str]) -> list[dict]:
    if not result_ids:
        return []
    try:
        with session_factory() as session:
            rows = session.execute(
                text(
                    "SELECT id, result_id, criterion_id, memberships_by_period, "
                    "aggregated_by_phase, aggregated_membership, w_ahp, w_entropy, "
                    "w_hybrid, entropy_series_used, entropy_fallback_reason "
                    "FROM transactional.evaluation_criterion_details "
                    "WHERE result_id IN :result_ids"
                ).bindparams(bindparam("result_ids", expanding=True)),
                {"result_ids": result_ids},
            ).mappings().all()
        return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        print(f"AVISO: Error consultando criterion details: {exc}")
        return []


# ─── Artifact management ──────────────────────────────────────────────────────


def setup_artifacts_dir(evaluation_id: str) -> pathlib.Path:
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    artifacts_dir = ARTIFACTS_BASE / f"{timestamp}_{evaluation_id}"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    return artifacts_dir


def safe_json_dump(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=True, cls=_SafeEncoder)


def write_artifact(artifacts_dir: pathlib.Path, filename: str, data: Any) -> None:
    path = artifacts_dir / filename
    if filename.endswith(".geojson") or filename.endswith(".json"):
        path.write_text(safe_json_dump(data), encoding="utf-8")
    else:
        path.write_text(str(data), encoding="utf-8")


# ─── Trace report generation ──────────────────────────────────────────────────


def generate_trace_report(artifacts_dir: pathlib.Path, ctx: dict) -> None:
    lines: list[str] = []
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines += [
        "# VIA - Trazabilidad E2E Demo",
        f"_Generado: {now}_",
        "",
        f"> {DEMO_DISCLAIMER}",
        "",
        "---",
        "",
        "## 1. Datos de Entrada",
        f"- Archivo GeoJSON: `{ctx['geojson_file']}`",
        f"- Cultivos candidatos: {', '.join(ctx['crops'])}",
        f"- Ventana temporal: {ctx['start_date']} a {ctx['end_date']}",
        f"- evaluation_id: `{ctx['evaluation_id']}`",
        f"- parcel_id: `{ctx['parcel_id']}`",
        "",
    ]

    lines += ["## 2. Parcela Creada"]
    snap = ctx.get("parcel_snapshot", {})
    lines.append(f"- parcel_id: `{ctx['parcel_id']}`")
    lines.append(f"- Propietario (user_id): `{ctx.get('user_id', '?')}`")
    area = snap.get("area_m2")
    if area is not None:
        try:
            area_f = float(area)
            lines.append(f"- Area aproximada: {area_f:,.0f} m2 ({area_f / 10000:.4f} ha)")
        except (TypeError, ValueError):
            lines.append(f"- Area aproximada: {area}")
    lines.append(f"- created_at: `{snap.get('created_at', '?')}`")
    lines.append("")

    lines += ["## 3. Rulebooks Activos Usados"]
    rulebooks = ctx.get("rulebooks", [])
    if rulebooks:
        lines += [
            "| crop_id | rulebook_id | version | status |",
            "|---------|-------------|---------|--------|",
        ]
        for rb in rulebooks:
            lines.append(
                f"| {rb.get('crop_id','?')} | {rb.get('id','?')} "
                f"| {rb.get('version','?')} | {rb.get('status','?')} |"
            )
    lines.append("")

    lines += ["## 4. Criterios por Cultivo - Pesos AHP y Politica Critica"]
    rb_details = ctx.get("rulebook_details", {})
    for crop_id, criteria in rb_details.get("criteria_by_crop", {}).items():
        lines.append(f"### {crop_id}")
        lines += [
            "| criterio | ahp_weight | is_critical | critical_policy | penalty_factor |",
            "|----------|------------|-------------|-----------------|----------------|",
        ]
        for c in criteria:
            lines.append(
                f"| {c.get('name','?')} | {c.get('ahp_weight','?')} "
                f"| {c.get('is_critical',False)} | {c.get('critical_policy','') or '-'} "
                f"| {c.get('penalty_factor','') or '-'} |"
            )
        lines.append("")

    lines += ["## 5. Fases Fenologicas por Cultivo"]
    for crop_id, phases in rb_details.get("phases_by_crop", {}).items():
        lines.append(f"### {crop_id}")
        lines += [
            "| fase | duracion_dias | sequence_order |",
            "|------|---------------|----------------|",
        ]
        for ph in phases:
            lines.append(
                f"| {ph.get('name','?')} | {ph.get('duration_days','?')} | {ph.get('sequence_order','?')} |"
            )
        lines.append("")

    lines += ["## 6. Funciones de Membresia (Trapeciales)"]
    for crop_id, reqs in rb_details.get("requirements_by_crop", {}).items():
        lines.append(f"### {crop_id}")
        lines += [
            "| criterio | fase | a | b | c | d | peso_fase |",
            "|----------|------|---|---|---|---|-----------|",
        ]
        for r in reqs:
            mfn = r.get("membership_fn") or {}
            lines.append(
                f"| {r.get('criterion_name','?')} | {r.get('phase_name','?')} "
                f"| {mfn.get('a','?')} | {mfn.get('b','?')} "
                f"| {mfn.get('c','?')} | {mfn.get('d','?')} "
                f"| {r.get('phase_weight','?')} |"
            )
        lines.append("")

    lines += ["## 7. Extraction Bindings (GEE)"]
    for binding in rb_details.get("extraction_bindings", []):
        lines += [
            f"- variable: `{binding.get('variable_name','?')}`",
            f"  dataset:  `{binding.get('dataset_key','?')}`",
            f"  band:     `{binding.get('band','?')}`",
            f"  reducer:  `{binding.get('reducer','?')}`",
            f"  scale:    `{binding.get('scale','?')}`",
        ]
    lines.append("")

    lines += ["## 8. Timeline del Outbox"]
    outbox = ctx.get("outbox_timeline", {})
    before_msgs = outbox.get("before", [])
    after_msgs = outbox.get("after", [])
    lines += [
        f"- Mensajes PENDING antes de procesar: {len(before_msgs)}",
        f"- Mensajes total despues de procesar: {len(after_msgs)}",
    ]
    if after_msgs:
        lines += [
            "",
            "| message_type | status | retry_count | dispatched_at |",
            "|--------------|--------|-------------|---------------|",
        ]
        for msg in after_msgs:
            lines.append(
                f"| {msg.get('message_type','?')} | {msg.get('status','?')} "
                f"| {msg.get('retry_count',0)} | {msg.get('dispatched_at','?')} |"
            )
    lines.append("")

    lines += ["## 9. Timeline de la Saga"]
    saga_t = ctx.get("saga_timeline", {})
    lines.append(f"- Estado final: `{saga_t.get('final_status','?')}`")
    transitions = saga_t.get("transitions", [])
    if transitions:
        lines += [
            "",
            "| from_status | to_status | occurred_at | failure_cause |",
            "|-------------|-----------|-------------|---------------|",
        ]
        for t in transitions:
            lines.append(
                f"| {t.get('from_status','?') or '-'} | {t.get('to_status','?')} "
                f"| {t.get('occurred_at','?')} | {t.get('failure_cause','') or '-'} |"
            )
    lines.append("")

    lines += ["## 10. Vector Agroambiental Generado"]
    vec = ctx.get("agroenv_vector") or {}
    if vec:
        lines += [
            f"- vector_id:    `{vec.get('id','?')}`",
            f"- evaluation_id:`{vec.get('evaluation_id','?')}`",
            f"- parcel_id:    `{vec.get('parcel_id','?')}`",
            f"- extracted_at: `{vec.get('extracted_at','?')}`",
            f"- temporal_window: `{vec.get('temporal_window','?')}`",
        ]
    else:
        lines.append("_Vector no disponible (evaluacion no completada o fallo)._")
    lines.append("")

    lines += ["## 11. Variables Extraidas desde GEE"]
    entries = ctx.get("agroenv_entries", [])
    if entries:
        lines += [
            "| variable | criterio | cultivo | fase | periodo | valor | status |",
            "|----------|----------|---------|------|---------|-------|--------|",
        ]
        for e in entries:
            lines.append(
                f"| {e.get('variable_name','?')} | {e.get('criterion_id','?')} "
                f"| {e.get('crop_id','?')} | {e.get('phase_id','?')} "
                f"| {e.get('period_key','?')} | {e.get('value','?')} "
                f"| {e.get('status','?')} |"
            )
    else:
        lines.append("_Sin variables extraidas._")
    lines.append("")

    eval_results = ctx.get("eval_results", [])
    sorted_results = sorted(eval_results, key=lambda r: (r.get("rank_position") or 999))

    lines += ["## 12. Resultado MCDA por Cultivo"]
    if sorted_results:
        lines += [
            "| rank | crop_id | score | categoria | calc_condition | entropy_used |",
            "|------|---------|-------|-----------|----------------|--------------|",
        ]
        for r in sorted_results:
            score = r.get("score")
            score_str = f"{float(score):.4f}" if score is not None else "N/A"
            lines.append(
                f"| {r.get('rank_position','-')} | {r.get('crop_id','?')} "
                f"| {score_str} | {r.get('viability_category','?')} "
                f"| {r.get('calc_condition','?')} | {r.get('entropy_used','?')} |"
            )
    lines.append("")

    lines += ["## 13. Detalle por Criterio (Trazabilidad MCDA)"]
    crit_details = ctx.get("criterion_details", [])
    result_to_crop = {str(r.get("id","")): r.get("crop_id","?") for r in eval_results}
    details_by_result: dict[str, list] = {}
    for d in crit_details:
        rid = str(d.get("result_id",""))
        details_by_result.setdefault(rid, []).append(d)
    for result_id, details in details_by_result.items():
        crop = result_to_crop.get(result_id, result_id)
        lines.append(f"### {crop}")
        for d in details:
            lines += [
                f"#### {d.get('criterion_id','?')}",
                f"- aggregated_membership: `{d.get('aggregated_membership','?')}`",
                f"- w_ahp: `{d.get('w_ahp','?')}`",
                f"- w_entropy: `{d.get('w_entropy','?')}`",
                f"- w_hybrid: `{d.get('w_hybrid','?')}`",
                f"- entropy_series_used: `{d.get('entropy_series_used','?')}`",
                f"- entropy_fallback_reason: `{d.get('entropy_fallback_reason') or 'N/A'}`",
            ]
            mbp = d.get("memberships_by_period")
            if mbp:
                lines.append(f"- memberships_by_period: `{json.dumps(mbp, ensure_ascii=True)}`")
            abp = d.get("aggregated_by_phase")
            if abp:
                lines.append(f"- aggregated_by_phase: `{json.dumps(abp, ensure_ascii=True)}`")
    lines.append("")

    final = ctx.get("final_api_result") or {}
    api_results = final.get("results") or []

    lines += ["## 14. Brechas (Gaps)"]
    has_gaps = any(r.get("gaps") for r in api_results)
    for r in api_results:
        gaps = r.get("gaps") or []
        if not gaps:
            continue
        lines.append(f"### {r.get('crop_id','?')}")
        lines += [
            "| criterio | fase | periodo_limitante | obs | optimo | brecha |",
            "|----------|------|-------------------|-----|--------|--------|",
        ]
        for g in gaps:
            lines.append(
                f"| {g.get('criterion_id','?')} | {g.get('phase_id','?')} "
                f"| {g.get('most_limiting_period','?')} | {g.get('observed_value','?')} "
                f"| {g.get('optimal_limit','?')} | {g.get('gap_value','?')} |"
            )
        lines.append("")
    if not has_gaps:
        lines += ["_Sin brechas detectadas._", ""]

    lines += ["## 15. Factores Limitantes (Criterios Criticos)"]
    has_factors = any(r.get("limiting_factors") for r in api_results)
    for r in api_results:
        factors = r.get("limiting_factors") or []
        if not factors:
            continue
        lines.append(f"### {r.get('crop_id','?')}")
        for f in factors:
            lines.append(
                f"- criterio: `{f.get('criterion_id','?')}` | "
                f"fase: `{f.get('phase_id','?')}` | "
                f"politica: `{f.get('policy','?')}` | "
                f"membership: `{f.get('membership','?')}`"
            )
        lines.append("")
    if not has_factors:
        lines += ["_Sin factores limitantes activados._", ""]

    lines += ["## 16. Ranking Final"]
    sorted_api = sorted(api_results, key=lambda r: (r.get("rank_position") or 999))
    for r in sorted_api:
        rank = r.get("rank_position", "-")
        score = r.get("score")
        score_str = f"{score:.4f}" if score is not None else "N/A"
        cat = r.get("viability_category", "?")
        lines.append(f"{rank}. {r.get('crop_id','?')} - score={score_str} - {cat}")
    lines.append("")

    lines += ["## 17. Respuesta Final de la API", "```json", safe_json_dump(final), "```", ""]

    lines += ["---", DEMO_DISCLAIMER, ""]

    report_path = artifacts_dir / ARTIFACT_NAMES["report"]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] Reporte generado: {report_path}")


# ─── Dry-run display ──────────────────────────────────────────────────────────


def _dry_run_report(args: argparse.Namespace, geometry: dict) -> None:
    print("\n[DRY-RUN] Configuracion validada. El script haria lo siguiente:")
    print(f"  GeoJSON          : {args.geojson_file}")
    print(f"  Tipo geometria   : {geometry.get('type','?')}")
    coords_preview = geometry.get("coordinates", [[]])[0][:2]
    print(f"  Primeros coords  : {coords_preview} (longitud, latitud)")
    print(f"  Cultivos         : {', '.join(args.crops)}")
    print(f"  Ventana temporal : {args.start_date} a {args.end_date}")
    print(f"  API base URL     : {os.environ.get('VIA_API_BASE_URL', DEFAULT_API_BASE_URL)}")
    print(f"  Admin email      : {os.environ.get('VIA_ADMIN_EMAIL', '?')}")
    print(f"  DATABASE_URL     : [configurada]")
    print(f"  GEE_PROJECT      : {os.environ.get('GEE_PROJECT', '?')}")
    print(f"  Artifacts dir    : {ARTIFACTS_BASE}/<timestamp>_<evaluation_id>/")
    print(f"  Max rounds       : {args.max_rounds}")
    print(f"  Pause seconds    : {args.pause_seconds}")
    print(f"  Until completed  : {args.until_completed}")
    print()
    print("[DRY-RUN] No se creo ninguna parcela ni evaluacion.")


# ─── Summary printer ─────────────────────────────────────────────────────────


def _failure_cause_from_timeline(saga_timeline: dict) -> str | None:
    """Extract the failure_cause from the FALLIDA saga transition, if present."""
    for t in saga_timeline.get("transitions", []):
        if t.get("to_status") == "FALLIDA":
            return t.get("failure_cause") or None
    return None


def _print_summary(
    parcel_id: str,
    evaluation_id: str,
    artifacts_dir: pathlib.Path,
    final_api_result: dict,
    saga_timeline: dict,
    allow_failed: bool = False,
) -> None:
    final_status = saga_timeline.get("final_status")
    print()
    print("=" * 60)

    if final_status == "FALLIDA":
        print("[ERROR] Evaluacion fallida.")
        print(f"  evaluation_id : {evaluation_id}")
        print(f"  parcel_id     : {parcel_id}")
        print(f"  final_status  : {final_status}")
        failure_cause = _failure_cause_from_timeline(saga_timeline)
        if failure_cause:
            print(f"  failure_cause : {failure_cause}")
        print()
        print("Trace generado en:")
        print(f"  {artifacts_dir / ARTIFACT_NAMES['report']}")
        print(f"  {artifacts_dir}")
        print("=" * 60)
        if not allow_failed:
            sys.exit(1)
        return

    if final_status in _TERMINAL_STATUSES:
        print("[OK] Evaluacion completada.")
    else:
        print(f"[AVISO] Estado final de la saga: {final_status}")
    print(f"  parcel_id     : {parcel_id}")
    print(f"  evaluation_id : {evaluation_id}")
    print()
    results = final_api_result.get("results") or []
    if results:
        print("Ranking:")
        sorted_r = sorted(results, key=lambda r: (r.get("rank_position") or 999))
        for r in sorted_r:
            rank = r.get("rank_position", "-")
            score = r.get("score")
            score_str = f"{score:.4f}" if score is not None else "N/A"
            cat = r.get("viability_category", "?")
            print(f"  {rank}. {r.get('crop_id','?'):<20} score={score_str}  {cat}")
    else:
        print("  (Sin resultados MCDA disponibles)")
    print()
    print("Trace generado en:")
    print(f"  {artifacts_dir / ARTIFACT_NAMES['report']}")
    print(f"  {artifacts_dir}")
    print("=" * 60)


# ─── Main orchestration ───────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    _check_env()

    geometry = load_geometry_from_file(args.geojson_file)

    if args.dry_run:
        _dry_run_report(args, geometry)
        return

    database_url = os.environ["DATABASE_URL"]
    api_base = os.environ.get("VIA_API_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/")

    engine = create_engine(database_url, echo=False, future=True)
    session_factory = sessionmaker(bind=engine, class_=Session, autoflush=False, expire_on_commit=False)

    try:
        rulebooks = verify_active_rulebooks(session_factory, args.crops)
        rb_details = query_rulebook_details(session_factory, args.crops)

        token, user_id = authenticate(api_base, os.environ["VIA_ADMIN_EMAIL"], os.environ["VIA_ADMIN_PASSWORD"])

        parcel_name = f"Demo E2E VIA {datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
        parcel_resp = create_parcel(api_base, token, geometry, parcel_name)
        parcel_id = str(parcel_resp.get("id", ""))

        parcel_snap = query_parcel_snapshot(session_factory, parcel_id)

        eval_resp = start_evaluation(
            api_base, token, parcel_id, user_id,
            args.crops, args.start_date, args.end_date,
        )
        evaluation_id = str(eval_resp.get("evaluation_id", ""))
        eval_uuid = UUID(evaluation_id)

        artifacts_dir = setup_artifacts_dir(evaluation_id)

        write_artifact(artifacts_dir, ARTIFACT_NAMES["input"], geometry)
        write_artifact(artifacts_dir, ARTIFACT_NAMES["auth"], {"email": os.environ["VIA_ADMIN_EMAIL"], "user_id": user_id})
        write_artifact(artifacts_dir, ARTIFACT_NAMES["parcel_api"], parcel_resp)
        write_artifact(artifacts_dir, ARTIFACT_NAMES["parcel_db"], parcel_snap)
        write_artifact(artifacts_dir, ARTIFACT_NAMES["rulebooks"], rulebooks)
        write_artifact(artifacts_dir, ARTIFACT_NAMES["rulebook_details"], rb_details)
        write_artifact(artifacts_dir, ARTIFACT_NAMES["extraction_bindings"], rb_details.get("extraction_bindings", []))
        write_artifact(artifacts_dir, ARTIFACT_NAMES["evaluation_api"], eval_resp)

        if args.skip_processing:
            print(f"[SKIP] --skip-processing: Outbox no procesado.")
            print(f"       evaluation_id : {evaluation_id}")
            print(f"       Artifacts dir : {artifacts_dir}")
            return

        outbox_before = snapshot_outbox(session_factory, eval_uuid)
        saga_before = snapshot_saga(session_factory, eval_uuid)

        print(f"\n[INFO] Procesando Outbox (max-rounds={args.max_rounds}, pause={args.pause_seconds}s)...")
        settings = load_settings({**os.environ, "GEE_ENABLED": "true"})
        relay = _build_relay(session_factory, settings)
        final_status = run_rounds(
            relay=relay,
            session_factory=session_factory,
            evaluation_id=eval_uuid,
            max_rounds=args.max_rounds,
            pause_seconds=args.pause_seconds,
            until_completed=args.until_completed,
        )

        outbox_after = snapshot_outbox(session_factory, eval_uuid)
        saga_after = snapshot_saga(session_factory, eval_uuid)
        saga_transitions = query_saga_transitions(session_factory, eval_uuid)

        agroenv_vec = query_agroenv_vector(session_factory, eval_uuid)
        agroenv_entries: list[dict] = []
        if agroenv_vec and agroenv_vec.get("id"):
            agroenv_entries = query_agroenv_variable_entries(session_factory, str(agroenv_vec["id"]))

        eval_results = query_evaluation_results(session_factory, eval_uuid)
        result_ids = [str(r["id"]) for r in eval_results if r.get("id")]
        crit_details = query_criterion_details(session_factory, result_ids)

        final_api = get_mcda_result(api_base, token, evaluation_id)

        outbox_timeline = {"before": outbox_before, "after": outbox_after}
        saga_timeline = {
            "before": saga_before,
            "after": saga_after,
            "transitions": saga_transitions,
            "final_status": final_status,
        }

        write_artifact(artifacts_dir, ARTIFACT_NAMES["outbox_timeline"], outbox_timeline)
        write_artifact(artifacts_dir, ARTIFACT_NAMES["saga_timeline"], saga_timeline)
        write_artifact(artifacts_dir, ARTIFACT_NAMES["agroenv_vector"], agroenv_vec or {})
        write_artifact(artifacts_dir, ARTIFACT_NAMES["agroenv_entries"], agroenv_entries)
        write_artifact(artifacts_dir, ARTIFACT_NAMES["mcda_results"], eval_results)
        write_artifact(artifacts_dir, ARTIFACT_NAMES["criterion_details"], crit_details)
        write_artifact(artifacts_dir, ARTIFACT_NAMES["final_api"], final_api)

        context = {
            "geojson_file": args.geojson_file,
            "crops": args.crops,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "parcel_id": parcel_id,
            "evaluation_id": evaluation_id,
            "user_id": user_id,
            "parcel_snapshot": parcel_snap,
            "rulebooks": rulebooks,
            "rulebook_details": rb_details,
            "outbox_timeline": outbox_timeline,
            "saga_timeline": saga_timeline,
            "agroenv_vector": agroenv_vec,
            "agroenv_entries": agroenv_entries,
            "eval_results": eval_results,
            "criterion_details": crit_details,
            "final_api_result": final_api,
            "final_status": final_status,
        }
        generate_trace_report(artifacts_dir, context)
        _print_summary(parcel_id, evaluation_id, artifacts_dir, final_api, saga_timeline, allow_failed=args.allow_failed)

    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
