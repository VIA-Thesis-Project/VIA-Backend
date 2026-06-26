#!/usr/bin/env python3
"""Sube documentos de un cultivo a un vector store de OpenAI para VIA File Search.

Uso:
    python scripts/openai_upload_crop_documents.py \\
        --crop maiz_amarillo_duro \\
        --vector-store-id vs_xxxxxxxx \\
        --manifest artifacts/openai_file_search/manifests/maiz_amarillo_duro_manifest.json

Estructura del manifest JSON:
    {
      "crop": "maiz_amarillo_duro",
      "variety": "maiz_amarillo_duro",
      "vector_store_name": "via_maiz_amarillo_duro",
      "documents": [
        {
          "path": "Fuente Documental/maiz_amarillo_duro/principal/documento.pdf",
          "role": "principal",
          "title": "Titulo del documento",
          "source_name": "INIA",
          "publication_year": 2020,
          "topics": ["riego", "deficit_hidrico", "suelo"]
        }
      ]
    }

Campos de role: "principal", "complementario" o "curated".
El script guarda un artifact en artifacts/openai_file_search/<crop>_upload_result.json.

Requiere:
    OPENAI_API_KEY configurada en el entorno.
    pip install openai
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import sys
import time
from typing import Any


VALID_ROLES = {"principal", "complementario", "curated"}
CURATED_FILENAMES = (
    "clima_fenologia.md",
    "suelo.md",
    "riego.md",
    "agua_riego.md",
    "fertilizacion.md",
    "fertilizacion_nutricion.md",
    "siembra_manejo.md",
    "instalacion_material_vegetal.md",
    "polinizacion_floracion.md",
    "polinizacion_floracion_cuajado.md",
    "floracion_cuajado_raleo_calibre.md",
    "induccion_floracion_cuajado.md",
    "propagacion_vivero_material.md",
    "instalacion_conduccion_podas.md",
    "instalacion_conduccion_canopia_podas.md",
    "malezas_sanidad.md",
    "sanidad.md",
    "sanidad_mip.md",
    "sanidad_mip_bpa.md",
    "cosecha_postcosecha.md",
    "cosecha_postcosecha_calidad.md",
    "mercado_cadena_productiva.md",
    "mercado_varietal_exportacion.md",
    "hybridos_variedades.md",
    "variedades_portainjertos.md",
    "material_varietal_portainjerto.md",
    "fitosanitario_exportacion_trazabilidad.md",
    "certificacion_exportacion.md",
    "metadata_manifest.json",
)
ARTIFACT_BASE = pathlib.Path(__file__).parents[1] / "artifacts" / "openai_file_search"
POLL_INTERVAL_SECONDS = 5
MAX_WAIT_SECONDS = 180


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="openai_upload_crop_documents.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--crop", required=True, metavar="CROP_ID", help="ID del cultivo")
    parser.add_argument(
        "--vector-store-id",
        required=True,
        metavar="VS_ID",
        help="Vector store ID de OpenAI (vs_...)",
    )
    parser.add_argument(
        "--manifest",
        required=True,
        metavar="PATH",
        help="Ruta al archivo JSON de manifest",
    )
    return parser.parse_args(argv)


def load_and_validate_manifest(manifest_path: str, crop_id: str) -> dict:
    """Load manifest JSON and validate structure. Raises SystemExit on error."""

    path = pathlib.Path(manifest_path)
    if not path.exists():
        print(f"ERROR: Manifest no encontrado: {manifest_path}", file=sys.stderr)
        sys.exit(1)

    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: Manifest JSON inválido: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(manifest, dict):
        print("ERROR: Manifest debe ser un objeto JSON.", file=sys.stderr)
        sys.exit(1)

    if "documents" not in manifest:
        print("ERROR: Manifest debe tener el campo 'documents'.", file=sys.stderr)
        sys.exit(1)

    if not isinstance(manifest["documents"], list):
        print("ERROR: Manifest.documents debe ser una lista.", file=sys.stderr)
        sys.exit(1)

    if not manifest["documents"]:
        print("ERROR: Manifest.documents no puede estar vacío.", file=sys.stderr)
        sys.exit(1)

    manifest_crop = manifest.get("crop", "")
    if manifest_crop != crop_id:
        print(
            f"ERROR: Manifest.crop='{manifest_crop}' no coincide con --crop='{crop_id}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    manifest["documents"] = _with_curated_documents(manifest["documents"], crop_id)
    manifest["documents"] = _sort_documents_for_upload(manifest["documents"])

    for i, doc in enumerate(manifest["documents"]):
        if not isinstance(doc, dict):
            print(f"ERROR: documents[{i}] debe ser un objeto.", file=sys.stderr)
            sys.exit(1)
        if "path" not in doc:
            print(f"ERROR: documents[{i}] debe tener el campo 'path'.", file=sys.stderr)
            sys.exit(1)
        role = doc.get("role", "principal")
        if role not in VALID_ROLES:
            print(
                f"ERROR: documents[{i}].role='{role}' inválido. "
                f"Valores válidos: {', '.join(sorted(VALID_ROLES))}",
                file=sys.stderr,
            )
            sys.exit(1)

    return manifest


def validate_document_paths(documents: list[dict]) -> None:
    """Verify all document paths exist. Raises SystemExit listing missing files."""

    missing: list[str] = []
    for doc in documents:
        p = pathlib.Path(doc["path"])
        if not p.exists():
            missing.append(doc["path"])

    if missing:
        print("ERROR: Los siguientes archivos no existen:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        sys.exit(1)


def _with_curated_documents(documents: list[dict], crop_id: str) -> list[dict]:
    """Append crop curated files when Fuente Documental/<crop>/curated exists."""

    curated_dir = _discover_curated_dir(documents, crop_id)
    if curated_dir is None:
        return documents

    existing_paths = {str(pathlib.Path(doc["path"]).resolve()).lower() for doc in documents}
    enriched = list(documents)
    for filename in CURATED_FILENAMES:
        path = curated_dir / filename
        if not path.exists():
            continue
        resolved = str(path.resolve()).lower()
        if resolved in existing_paths:
            continue
        enriched.append(
            {
                "path": str(path),
                "role": "curated",
                "title": f"Ficha curada {filename}",
                "source_name": "VIA curated",
                "publication_year": None,
                "topics": _topics_for_curated_filename(filename),
            }
        )
    return enriched


def _discover_curated_dir(documents: list[dict], crop_id: str) -> pathlib.Path | None:
    """Find the curated directory from manifest document paths."""

    for doc in documents:
        path = pathlib.Path(doc.get("path", ""))
        parts = path.parts
        if crop_id not in parts:
            continue
        crop_index = parts.index(crop_id)
        crop_dir = pathlib.Path(*parts[: crop_index + 1])
        curated_dir = crop_dir / "curated"
        if curated_dir.exists() and curated_dir.is_dir():
            return curated_dir
    return None


def _topics_for_curated_filename(filename: str) -> list[str]:
    """Return topic tags for a curated recommendation document."""

    return {
        "clima_fenologia.md": ["curated", "clima", "fenologia", "temperatura", "aptitud_termica"],
        "suelo.md": ["curated", "suelo", "textura", "arcilla", "materia_organica", "drenaje"],
        "riego.md": ["curated", "riego", "agua", "deficit_hidrico", "exceso_hidrico"],
        "agua_riego.md": ["curated", "riego", "agua", "deficit_hidrico", "humedad"],
        "fertilizacion.md": ["curated", "fertilizacion", "nutrientes", "nitrogeno", "fosforo", "potasio"],
        "fertilizacion_nutricion.md": ["curated", "fertilizacion", "nutricion", "nitrogeno", "fosforo", "potasio"],
        "siembra_manejo.md": ["curated", "siembra", "densidad", "semilla", "manejo"],
        "instalacion_material_vegetal.md": ["curated", "instalacion", "material_vegetal", "vivero", "planton"],
        "polinizacion_floracion.md": ["curated", "floracion", "polinizacion", "cuajado", "abejas"],
        "polinizacion_floracion_cuajado.md": ["curated", "floracion", "polinizacion", "cuajado", "fecundacion"],
        "floracion_cuajado_raleo_calibre.md": ["curated", "floracion", "cuajado", "raleo", "calibre"],
        "induccion_floracion_cuajado.md": ["curated", "induccion_floral", "floracion", "cuajado", "estres_hidrico"],
        "propagacion_vivero_material.md": ["curated", "propagacion", "vivero", "material_vegetal", "semilla"],
        "instalacion_conduccion_podas.md": ["curated", "instalacion", "conduccion", "poda", "tutorado"],
        "instalacion_conduccion_canopia_podas.md": ["curated", "instalacion", "conduccion", "canopia", "poda"],
        "malezas_sanidad.md": ["curated", "malezas", "sanidad", "plagas", "enfermedades"],
        "sanidad.md": ["curated", "sanidad", "plagas", "enfermedades", "mip"],
        "sanidad_mip.md": ["curated", "sanidad", "plagas", "enfermedades", "mip"],
        "sanidad_mip_bpa.md": ["curated", "sanidad", "plagas", "enfermedades", "mip", "bpa"],
        "cosecha_postcosecha.md": ["curated", "cosecha", "postcosecha", "calidad_grano"],
        "cosecha_postcosecha_calidad.md": ["curated", "cosecha", "postcosecha", "calidad", "exportacion"],
        "mercado_cadena_productiva.md": ["curated", "mercado", "cadena_productiva", "comercializacion", "exportacion"],
        "mercado_varietal_exportacion.md": ["curated", "mercado", "varietal", "exportacion", "sweet_globe"],
        "hybridos_variedades.md": ["curated", "hibrido", "variedad"],
        "variedades_portainjertos.md": ["curated", "variedad", "portainjerto", "hass"],
        "material_varietal_portainjerto.md": ["curated", "variedad", "portainjerto", "sweet_globe", "material_vegetal"],
        "fitosanitario_exportacion_trazabilidad.md": ["curated", "fitosanitario", "exportacion", "trazabilidad", "senasa"],
        "certificacion_exportacion.md": ["curated", "certificacion", "exportacion", "fitosanitaria", "calidad"],
        "metadata_manifest.json": ["curated", "metadata", "manifest"],
    }.get(filename, ["curated"])


def _sort_documents_for_upload(documents: list[dict]) -> list[dict]:
    """Upload curated files first, then principal and complementary PDFs."""

    role_order = {"curated": 0, "principal": 1, "complementario": 2}
    return sorted(documents, key=lambda doc: (role_order.get(doc.get("role", "principal"), 9), doc["path"]))


def upload_documents(
    crop_id: str,
    vector_store_id: str,
    manifest: dict,
    client_factory: Any = None,
) -> dict:
    """Upload documents and return the artifact dict."""

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("ERROR: OPENAI_API_KEY no está configurada en el entorno.", file=sys.stderr)
        sys.exit(1)

    if client_factory is not None:
        client = client_factory(api_key)
    else:
        try:
            from openai import OpenAI
        except ImportError:
            print(
                "ERROR: paquete 'openai' no instalado. Ejecuta: pip install openai",
                file=sys.stderr,
            )
            sys.exit(1)
        client = OpenAI(api_key=api_key)

    documents = _sort_documents_for_upload(manifest["documents"])
    uploaded_file_ids: list[str] = []
    source_filenames: list[str] = []
    artifact_documents: list[dict] = []

    for doc in documents:
        file_path = pathlib.Path(doc["path"])
        print(f"Subiendo: {file_path.name} ...")
        try:
            with open(file_path, "rb") as f:
                uploaded = client.files.create(file=f, purpose="assistants")
        except Exception as exc:
            print(f"  ERROR al subir {file_path.name}: {exc}", file=sys.stderr)
            sys.exit(1)

        print(f"  Archivo subido → {uploaded.id}")

        try:
            client.vector_stores.files.create(
                vector_store_id=vector_store_id,
                file_id=uploaded.id,
            )
        except Exception as exc:
            print(f"  ERROR al agregar al vector store: {exc}", file=sys.stderr)
            sys.exit(1)

        print(f"  Agregado al vector store.")

        uploaded_file_ids.append(uploaded.id)
        source_filenames.append(file_path.name)
        artifact_documents.append(
            {
                "path": doc["path"],
                "filename": file_path.name,
                "role": doc.get("role", "principal"),
                "title": doc.get("title", ""),
                "source_name": doc.get("source_name", ""),
                "publication_year": doc.get("publication_year"),
                "topics": doc.get("topics", []),
                "file_id": uploaded.id,
            }
        )

    print("\nEsperando procesamiento en el vector store ...")
    status = _wait_for_processing(client, vector_store_id)
    print(f"  Estado final: {status}")

    artifact = {
        "crop": crop_id,
        "vector_store_id": vector_store_id,
        "uploaded_file_ids": uploaded_file_ids,
        "source_filenames": source_filenames,
        "documents": artifact_documents,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "completed",
        "vector_store_processing_status": status,
        "role_note": (
            "MVP: un vector store por cultivo. role=principal/complementario "
            "registrado en artifact local; metadata de role no disponible en "
            "OpenAI File Search en esta implementación."
        ),
    }

    return artifact


def _wait_for_processing(client: Any, vector_store_id: str) -> str:
    """Poll until the vector store finishes processing or timeout."""
    start = time.time()
    while time.time() - start < MAX_WAIT_SECONDS:
        try:
            vs = client.vector_stores.retrieve(vector_store_id)
            fc = vs.file_counts
            in_progress = getattr(fc, "in_progress", 0)
            completed = getattr(fc, "completed", 0)
            failed = getattr(fc, "failed", 0)
            if in_progress == 0:
                return f"completed={completed}, failed={failed}"
            print(f"  En proceso: {in_progress} archivo(s) ...")
        except Exception as exc:
            return f"error_polling: {exc}"
        time.sleep(POLL_INTERVAL_SECONDS)
    return "timeout"


def _save_artifact(crop_id: str, artifact: dict) -> pathlib.Path:
    ARTIFACT_BASE.mkdir(parents=True, exist_ok=True)
    artifact_path = ARTIFACT_BASE / f"{crop_id}_upload_result.json"
    artifact_path.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return artifact_path


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    manifest = load_and_validate_manifest(args.manifest, args.crop)
    validate_document_paths(manifest["documents"])

    artifact = upload_documents(args.crop, args.vector_store_id, manifest)

    artifact_path = _save_artifact(args.crop, artifact)
    print(f"\nArtifact guardado en: {artifact_path}")
    print(f"  uploaded_file_ids : {artifact['uploaded_file_ids']}")
    print(f"  source_filenames  : {artifact['source_filenames']}")
    print(
        "\nPróximo paso: configura LLM_DRAFTING_PROVIDER=openai_file_search "
        f"y VIA_VECTOR_STORE_{args.crop.upper()}_ID={args.vector_store_id} en tu .env"
    )


if __name__ == "__main__":
    main()
