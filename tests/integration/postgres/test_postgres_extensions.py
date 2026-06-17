"""22A: Validate that required PostgreSQL extensions are installed.

Extensions are created by migration 20260614_0001.
All tests in this module depend on pg_migrated (downgrade base + upgrade head).
If an extension is missing, the test fails with a clear installation message.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text


def _extension_installed(conn, extname: str) -> bool:
    result = conn.execute(
        text("SELECT 1 FROM pg_extension WHERE extname = :name"),
        {"name": extname},
    )
    return result.fetchone() is not None


@pytest.mark.slow
def test_pgcrypto_is_installed(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        installed = _extension_installed(conn, "pgcrypto")
    assert installed, (
        "Extension 'pgcrypto' is not installed. "
        "Run: CREATE EXTENSION IF NOT EXISTS pgcrypto; "
        "or ensure migration 20260614_0001 ran successfully."
    )


@pytest.mark.slow
def test_postgis_is_installed(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        installed = _extension_installed(conn, "postgis")
    assert installed, (
        "Extension 'postgis' is not installed. "
        "Install PostGIS for your PostgreSQL version and retry. "
        "Migration 20260614_0001 runs: CREATE EXTENSION IF NOT EXISTS postgis"
    )


@pytest.mark.slow
def test_vector_pgvector_is_installed(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        installed = _extension_installed(conn, "vector")
    assert installed, (
        "Extension 'vector' (pgvector) is not installed. "
        "Install pgvector for your PostgreSQL version and retry. "
        "Migration 20260614_0001 runs: CREATE EXTENSION IF NOT EXISTS vector"
    )


@pytest.mark.slow
def test_pgcrypto_gen_random_uuid_works(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        result = conn.execute(text("SELECT gen_random_uuid()"))
        uuid_value = str(result.scalar_one())
    assert len(uuid_value) == 36, (
        f"gen_random_uuid() returned unexpected value: {uuid_value!r}"
    )
    parts = uuid_value.split("-")
    assert len(parts) == 5, f"UUID format invalid: {uuid_value!r}"


@pytest.mark.slow
def test_postgis_st_astext_works(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        result = conn.execute(
            text("SELECT ST_AsText(ST_GeomFromText('POINT(0 0)', 4326))")
        )
        wkt = result.scalar_one()
    assert wkt == "POINT(0 0)", f"PostGIS ST_AsText returned unexpected value: {wkt!r}"


@pytest.mark.slow
def test_vector_cast_works(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        result = conn.execute(text("SELECT '[1,2,3]'::vector"))
        value = result.scalar_one()
    assert value is not None, "vector cast returned None"


@pytest.mark.slow
def test_vector_dimensions_are_queryable(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        result = conn.execute(text("SELECT vector_dims('[1,2,3]'::vector)"))
        dims = result.scalar_one()
    assert dims == 3, f"Expected 3 dimensions, got {dims}"
