#!/usr/bin/env python3
"""Crea vector stores en OpenAI por cultivo para VIA File Search.

Uso:
    python scripts/openai_create_vector_stores.py
    python scripts/openai_create_vector_stores.py --only maiz_amarillo_duro

Requiere:
    OPENAI_API_KEY configurada en el entorno.
    pip install openai

No sube documentos. Usa openai_upload_crop_documents.py para eso.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

CROP_STORE_NAMES: dict[str, str] = {
    "maiz_amarillo_duro": "via_maiz_amarillo_duro",
    "palta_hass": "via_palta_hass",
    "mandarina_murcott": "via_mandarina_murcott",
    "maracuya_amarillo": "via_maracuya_amarillo",
    "cana_de_azucar": "via_cana_de_azucar",
    "uva_de_mesa_sweet_globe": "via_uva_de_mesa_sweet_globe",
}

ENV_VAR_NAMES: dict[str, str] = {
    "maiz_amarillo_duro": "VIA_VECTOR_STORE_MAIZ_AMARILLO_DURO_ID",
    "palta_hass": "VIA_VECTOR_STORE_PALTA_HASS_ID",
    "mandarina_murcott": "VIA_VECTOR_STORE_MANDARINA_MURCOTT_ID",
    "maracuya_amarillo": "VIA_VECTOR_STORE_MARACUYA_AMARILLO_ID",
    "cana_de_azucar": "VIA_VECTOR_STORE_CANA_DE_AZUCAR_ID",
    "uva_de_mesa_sweet_globe": "VIA_VECTOR_STORE_UVA_DE_MESA_SWEET_GLOBE_ID",
}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="openai_create_vector_stores.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--only",
        metavar="CROP_ID",
        help=(
            f"Crear solo el vector store de este cultivo. "
            f"Valores válidos: {', '.join(CROP_STORE_NAMES)}"
        ),
    )
    return parser.parse_args(argv)


def create_vector_stores(
    crops: dict[str, str],
    client_factory: Any = None,
) -> dict[str, dict[str, str]]:
    """Create one vector store per crop. Returns {crop_id: {store_name, vector_store_id}}.

    client_factory: callable that returns an OpenAI client-like object.
    When None the real openai.OpenAI is used.
    """
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

    results: dict[str, dict[str, str]] = {}
    for crop_id, store_name in crops.items():
        print(f"Creando vector store: {store_name} ...")
        try:
            vs = client.vector_stores.create(name=store_name)
            results[crop_id] = {"store_name": store_name, "vector_store_id": vs.id}
            print(f"  OK  → {vs.id}")
        except Exception as exc:
            print(f"  ERROR al crear {store_name}: {exc}", file=sys.stderr)
            sys.exit(1)

    return results


def _print_results(results: dict[str, dict[str, str]]) -> None:
    print("\n=== Vector Stores Creados ===")
    for crop_id, info in results.items():
        print(f"  {crop_id}: {info['vector_store_id']}")

    print("\n=== Variables de entorno sugeridas (.env) ===")
    for crop_id, info in results.items():
        env_var = ENV_VAR_NAMES[crop_id]
        print(f"  {env_var}={info['vector_store_id']}")

    print(
        "\nIMPORTANTE: Agrega estas variables a tu .env y reinicia el servidor antes de "
        "configurar LLM_DRAFTING_PROVIDER=openai_file_search."
    )


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    if args.only is not None:
        if args.only not in CROP_STORE_NAMES:
            print(
                f"ERROR: Cultivo desconocido: '{args.only}'. "
                f"Valores válidos: {', '.join(CROP_STORE_NAMES)}",
                file=sys.stderr,
            )
            sys.exit(1)
        crops_to_create = {args.only: CROP_STORE_NAMES[args.only]}
    else:
        crops_to_create = dict(CROP_STORE_NAMES)

    results = create_vector_stores(crops_to_create)
    _print_results(results)


if __name__ == "__main__":
    main()
