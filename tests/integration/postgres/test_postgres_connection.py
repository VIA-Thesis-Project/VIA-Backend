"""22A: Validate that VIA can connect to PostgreSQL using the psycopg2 driver."""

from __future__ import annotations

import pytest
from sqlalchemy import text


@pytest.mark.slow
def test_can_execute_select_one(pg_engine) -> None:
    with pg_engine.connect() as conn:
        result = conn.execute(text("SELECT 1 AS value"))
        row = result.fetchone()
    assert row is not None
    assert row[0] == 1


@pytest.mark.slow
def test_url_uses_psycopg2_driver(pg_database_url: str) -> None:
    assert "psycopg2" in pg_database_url, (
        "DATABASE_URL must use the psycopg2 driver (postgresql+psycopg2://...). "
        f"Current scheme: {pg_database_url.split('://')[0]!r}"
    )


@pytest.mark.slow
def test_url_scheme_is_postgresql_psycopg2(pg_database_url: str) -> None:
    assert pg_database_url.startswith("postgresql+psycopg2://"), (
        "DATABASE_URL must start with 'postgresql+psycopg2://'"
    )


@pytest.mark.slow
def test_url_does_not_use_asyncpg(pg_database_url: str) -> None:
    assert "asyncpg" not in pg_database_url, (
        "DATABASE_URL must not use asyncpg. VIA uses synchronous psycopg2."
    )


@pytest.mark.slow
def test_database_name_contains_test(pg_database_url: str) -> None:
    db_name = pg_database_url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    assert "test" in db_name.lower(), (
        f"DATABASE_URL should point to a test database (name must contain 'test'). "
        f"Got: '{db_name}'"
    )


@pytest.mark.slow
def test_connection_returns_postgresql_version(pg_engine) -> None:
    with pg_engine.connect() as conn:
        result = conn.execute(text("SELECT version()"))
        version_string: str = result.scalar_one()
    assert "PostgreSQL" in version_string, (
        f"Expected PostgreSQL server, got: {version_string[:80]}"
    )


@pytest.mark.slow
def test_connection_result_is_synchronous(pg_engine) -> None:
    import inspect

    with pg_engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
    assert not inspect.isawaitable(result), (
        "Connection result must be synchronous (not a coroutine). "
        "VIA does not use async SQLAlchemy."
    )
