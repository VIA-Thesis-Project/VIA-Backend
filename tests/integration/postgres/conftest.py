"""Session-scoped fixtures for PostgreSQL integration tests (lote 22A).

All tests in this package require a live PostgreSQL instance.
Set the DATABASE_URL environment variable before running:

    DATABASE_URL=postgresql+psycopg2://username:password@localhost:5432/via_test pytest tests/integration/

Tests skip automatically when DATABASE_URL is absent.
Credentials are never printed or hardcoded here.
"""

from __future__ import annotations

import os
import pathlib

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine, text

_SKIP_REASON = (
    "DATABASE_URL is not set — PostgreSQL integration tests require a live database. "
    "Export DATABASE_URL=postgresql+psycopg2://username:password@localhost:5432/via_test and retry."
)

_REPO_ROOT = pathlib.Path(__file__).parents[3]


@pytest.fixture(scope="session")
def pg_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip(_SKIP_REASON)
    if "psycopg2" not in url:
        scheme = url.split("://")[0] if "://" in url else url[:30]
        pytest.fail(
            f"DATABASE_URL must use the psycopg2 driver (postgresql+psycopg2://...). "
            f"Detected scheme: {scheme!r}"
        )
    return url


@pytest.fixture(scope="session")
def pg_engine(pg_database_url: str):
    engine = create_engine(pg_database_url, echo=False)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.fail(f"Cannot connect to PostgreSQL: {type(exc).__name__}: {exc}")
    yield engine
    engine.dispose()


_REQUIRED_EXTENSIONS = ("pgcrypto", "postgis", "vector")


@pytest.fixture(scope="session")
def pg_migrated(pg_database_url: str, pg_engine):
    """Run alembic downgrade base → upgrade head once per test session.

    Safety guards:
    - Database name must contain 'test' to prevent accidental use against production.
    - Required extensions must be available on the server before migrations run.
      If an extension is missing, this fixture fails with a clear installation message
      rather than a cryptic SQLAlchemy error from inside the migration.
    """
    db_name = pg_database_url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    if "test" not in db_name.lower():
        pytest.fail(
            f"Safety guard: DATABASE_URL must point to a test database "
            f"(name must contain 'test'). Got database name: '{db_name}'."
        )

    with pg_engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT name FROM pg_available_extensions "
                "WHERE name IN ('pgcrypto', 'postgis', 'vector')"
            )
        )
        available = {row[0] for row in result}

    missing = set(_REQUIRED_EXTENSIONS) - available
    if missing:
        pytest.fail(
            f"Required PostgreSQL extensions are not installed on this server: {sorted(missing)}. "
            f"Install the missing packages (e.g. 'postgresql-15-postgis-3', 'postgresql-15-pgvector') "
            f"and restart PostgreSQL before running lote 22A integration tests. "
            f"Extensions found on server: {sorted(available) or 'none of the required ones'}."
        )

    alembic_cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(_REPO_ROOT / "migrations"))

    alembic_command.downgrade(alembic_cfg, "base")
    alembic_command.upgrade(alembic_cfg, "head")

    return pg_engine
