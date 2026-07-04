"""End-to-end smoke test for the cross-crop entropy weighting.

Drives a full evaluation through the real HTTP API and then reads the persisted
per-criterion weights straight from the database to show the entropy
redistribution (w_ahp vs w_entropy vs w_hybrid), grouped into site-static
(soil/topography) vs dynamic (climate) criteria.

    login -> create parcel -> POST /evaluaciones (5 crops) -> poll estado
          -> GET resultado-mcda -> read w_entropy per criterion from DB

Run against a server started with scripts/start_dev.ps1. Everything is read from
the environment (same variables start_dev.ps1 exports), so it works with either
GEE_ENABLED=true (real extraction, slow) or GEE_ENABLED=false.

Usage (PowerShell, with the server already running):
    PYTHONPATH=. python scripts/smoke_entropy_eval.py
    # optional overrides:
    $env:VIA_BASE_URL="http://127.0.0.1:8000"
    $env:SMOKE_CROPS="maiz_amarillo_duro,mandarina_murcott,palta_hass"
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from sqlalchemy import create_engine, text

# ── Configuration from environment (defaults match scripts/start_dev.ps1) ───────

BASE_URL = os.environ.get("VIA_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg2://via_user:via_password@localhost:5433/via_test"
)
ADMIN_EMAIL = os.environ.get("SEED_ADMIN_EMAIL") or os.environ.get("VIA_ADMIN_EMAIL") or "admin@via.local"
ADMIN_PASSWORD = os.environ.get("SEED_ADMIN_PASSWORD") or os.environ.get("VIA_ADMIN_PASSWORD") or "Admin123456"
GEE_ENABLED = os.environ.get("GEE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}

DEFAULT_CROPS = [
    "maiz_amarillo_duro",
    "mandarina_murcott",
    "maracuya_criolla_amarilla",
    "palta_hass",
    "uva_de_mesa_sweet_globe",
]
CROPS = [c.strip() for c in os.environ.get("SMOKE_CROPS", ",".join(DEFAULT_CROPS)).split(",") if c.strip()]

TEMPORAL_WINDOW = {
    "start_date": os.environ.get("SMOKE_START_DATE", "2024-06-01"),
    "end_date": os.environ.get("SMOKE_END_DATE", "2024-08-31"),
}
GEOJSON_FILE = os.environ.get(
    "SMOKE_GEOJSON",
    str(pathlib.Path(__file__).parents[1] / "examples" / "parcels" / "parcela_humalla.geojson"),
)

# Real GEE extraction is hundreds of serial round-trips; give it room.
POLL_TIMEOUT_SECONDS = int(os.environ.get("SMOKE_POLL_TIMEOUT", "900" if GEE_ENABLED else "120"))
POLL_INTERVAL_SECONDS = int(os.environ.get("SMOKE_POLL_INTERVAL", "3"))

# Site-static criteria (soil + topography): the ones the temporal-entropy bug zeroed.
STATIC_CRITERIA = {
    "aptitud_altitudinal",
    "aptitud_topografica",
    "reaccion_suelo_ph",
    "contenido_arcilla",
    "contenido_arena",
    "carbono_organico_suelo",
    "profundidad_suelo",
    "salinidad_suelo",
    "cobertura_actual_auxiliar",
}


# ── Tiny HTTP helpers (stdlib only) ─────────────────────────────────────────────


def _request(method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, Any]:
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            payload = response.read().decode("utf-8")
            return response.status, (json.loads(payload) if payload else {})
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(payload)
        except json.JSONDecodeError:
            return exc.code, {"detail": payload}
    except urllib.error.URLError as exc:
        _fail(f"No se pudo conectar a {url}: {exc.reason}. ¿El servidor está arriba (start_dev.ps1)?")


def _fail(message: str) -> "None":
    print(f"\nERROR: {message}", file=sys.stderr)
    sys.exit(1)


def _load_polygon(path: str) -> dict:
    raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if raw.get("type") == "FeatureCollection":
        raw = raw["features"][0].get("geometry", {})
    elif raw.get("type") == "Feature":
        raw = raw.get("geometry", {})
    if raw.get("type") not in {"Polygon", "MultiPolygon"}:
        _fail(f"Geometría inválida en {path}: se esperaba Polygon/MultiPolygon")
    return raw


# ── Pipeline steps ──────────────────────────────────────────────────────────────


def login() -> str:
    status, body = _request("POST", "/auth/login", {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if status != 200 or "access_token" not in body:
        _fail(f"Login falló (HTTP {status}): {body}. Verificá SEED_ADMIN_EMAIL/PASSWORD y el seed de admin.")
    print(f"[1/5] Autenticado como {ADMIN_EMAIL}")
    return body["access_token"]


def create_parcel(token: str) -> str:
    geometry = _load_polygon(GEOJSON_FILE)
    body = {
        "geometry": geometry,
        "metadata": {"name": "Smoke Entropía", "description": "parcela smoke test", "crs": "EPSG:4326"},
    }
    status, resp = _request("POST", "/parcelas", body, token)
    if status != 201 or "id" not in resp:
        _fail(f"Crear parcela falló (HTTP {status}): {resp}")
    print(f"[2/5] Parcela creada: {resp['id']}  (geometría: {pathlib.Path(GEOJSON_FILE).name})")
    return resp["id"]


def start_evaluation(token: str, parcel_id: str) -> str:
    body = {"parcel_id": parcel_id, "crop_candidates": CROPS, "temporal_window": TEMPORAL_WINDOW}
    status, resp = _request("POST", "/evaluaciones", body, token)
    if status != 202 or "evaluation_id" not in resp:
        _fail(f"POST /evaluaciones falló (HTTP {status}): {resp}")
    print(f"[3/5] Evaluación iniciada: {resp['evaluation_id']}  ({len(CROPS)} cultivos, GEE={'ON' if GEE_ENABLED else 'OFF'})")
    return resp["evaluation_id"]


def poll_until_terminal(token: str, evaluation_id: str) -> str:
    terminal = {"EVALUACION_COMPLETADA", "RECOMENDACION_COMPLETADA", "FALLIDA"}
    deadline = time.time() + POLL_TIMEOUT_SECONDS
    last_status = ""
    while time.time() < deadline:
        status, resp = _request("GET", f"/evaluaciones/{evaluation_id}/estado", token=token)
        if status != 200:
            _fail(f"GET estado falló (HTTP {status}): {resp}")
        current = resp.get("status", "")
        if current != last_status:
            print(f"      estado: {current}")
            last_status = current
        if current in terminal:
            if current == "FALLIDA":
                _fail(f"La evaluación falló: {resp.get('failure_reason')}")
            print(f"[4/5] Evaluación terminó en {current}")
            return current
        time.sleep(POLL_INTERVAL_SECONDS)
    _fail(f"Timeout tras {POLL_TIMEOUT_SECONDS}s esperando el estado terminal (último: {last_status}).")


def print_mcda_ranking(token: str, evaluation_id: str) -> None:
    status, resp = _request("GET", f"/evaluaciones/{evaluation_id}/resultado-mcda", token=token)
    if status != 200:
        _fail(f"GET resultado-mcda falló (HTTP {status}): {resp}")
    print("\n[5/5] Ranking MCDA:")
    results = sorted(resp.get("results", []), key=lambda r: (r.get("rank_position") or 999))
    for r in results:
        rank = r.get("rank_position")
        rank_str = f"#{rank}" if rank else "—"
        score = r.get("score")
        score_str = f"{score:.4f}" if isinstance(score, (int, float)) else "N/A"
        print(f"   {rank_str:>3s}  {r['crop_id']:28s} score={score_str}  {r.get('viability_category')}")


def print_entropy_weights(evaluation_id: str) -> None:
    """Read persisted per-criterion weights from the DB and show the redistribution.

    w_entropy is persisted but not exposed by the MCDA endpoint, so we query the
    evaluation_criterion_details table directly.
    """
    engine = create_engine(DATABASE_URL)
    query = text(
        """
        SELECT r.crop_id, r.entropy_used, d.criterion_id, d.w_ahp, d.w_entropy, d.w_hybrid
        FROM transactional.evaluation_results r
        JOIN transactional.evaluation_criterion_details d ON d.result_id = r.id
        WHERE r.evaluation_id = :eid
        ORDER BY r.rank_position NULLS LAST, r.crop_id, d.criterion_id
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(query, {"eid": evaluation_id}).mappings().all()

    if not rows:
        _fail("No hay criterion_details persistidos para esta evaluación.")

    by_crop: dict[str, list[dict]] = {}
    entropy_used_by_crop: dict[str, bool] = {}
    for row in rows:
        by_crop.setdefault(row["crop_id"], []).append(row)
        entropy_used_by_crop[row["crop_id"]] = bool(row["entropy_used"])

    print("\n" + "=" * 78)
    print("PESOS POR CRITERIO — w_ahp vs w_entropy vs w_hybrid  (S=estático, D=dinámico)")
    print("=" * 78)
    print("Verificación: los criterios ESTÁTICOS (suelo/topografía) deben mostrar")
    print("w_entropy > 0 cuando discriminan entre cultivos — antes del fix eran ~0.\n")

    for crop_id, details in by_crop.items():
        used = entropy_used_by_crop[crop_id]
        print(f"── {crop_id}  (entropy_used={used}) " + "─" * max(0, 40 - len(crop_id)))
        print(f"   {'criterio':26s}{'tipo':>5s}{'w_ahp':>9s}{'w_entropy':>11s}{'w_hybrid':>10s}{'Δ vs AHP':>10s}")
        static_entropy_mass = 0.0
        for d in sorted(details, key=lambda x: (x["criterion_id"] not in STATIC_CRITERIA, x["criterion_id"])):
            crit = d["criterion_id"]
            kind = "S" if crit in STATIC_CRITERIA else "D"
            w_ahp = float(d["w_ahp"])
            w_ent = None if d["w_entropy"] is None else float(d["w_entropy"])
            w_hyb = float(d["w_hybrid"])
            ent_str = "—" if w_ent is None else f"{w_ent:.4f}"
            delta = (w_hyb - w_ahp) / w_ahp * 100 if w_ahp > 0 else 0.0
            if kind == "S" and w_ent is not None:
                static_entropy_mass += w_ent
            print(f"   {crit:26s}{kind:>5s}{w_ahp:9.4f}{ent_str:>11s}{w_hyb:10.4f}{delta:>+9.1f}%")
        print(f"   → masa de entropía capturada por criterios ESTÁTICOS: {static_entropy_mass:.3f}\n")

    if len(CROPS) < 3:
        print("NOTA: con <3 cultivos la entropía cae a AHP puro por diseño (umbral "
              "MCDA_MIN_ALTERNATIVES_FOR_ENTROPY=3); w_entropy aparecerá vacío.")


def main() -> None:
    print(f"VIA smoke — base={BASE_URL}  GEE={'ON' if GEE_ENABLED else 'OFF'}  "
          f"cultivos={len(CROPS)}  poll_timeout={POLL_TIMEOUT_SECONDS}s")
    token = login()
    parcel_id = create_parcel(token)
    evaluation_id = start_evaluation(token, parcel_id)
    poll_until_terminal(token, evaluation_id)
    print_mcda_ranking(token, evaluation_id)
    print_entropy_weights(evaluation_id)
    print("\n[OK] Smoke completo.")


if __name__ == "__main__":
    main()
