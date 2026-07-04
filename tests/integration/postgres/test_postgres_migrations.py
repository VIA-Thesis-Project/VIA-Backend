"""22A: Validate that Alembic migrations apply cleanly and record the correct head revision."""

from __future__ import annotations

import pathlib

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

_REPO_ROOT = pathlib.Path(__file__).parents[3]
# Derived from the migrations directory so this test can never go stale when
# a new revision is added (it previously hardcoded the initial head).
_EXPECTED_HEAD = ScriptDirectory(str(_REPO_ROOT / "migrations")).get_current_head()


def _make_alembic_config(database_url: str) -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "migrations"))
    return cfg


@pytest.mark.slow
def test_alembic_version_table_exists(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        result = conn.execute(
            text("SELECT tablename FROM pg_tables WHERE tablename = 'alembic_version'")
        )
        row = result.fetchone()
    assert row is not None, (
        "Table 'alembic_version' not found after upgrade head. "
        "Verify Alembic ran correctly."
    )


@pytest.mark.slow
def test_head_revision_is_applied(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        result = conn.execute(text("SELECT version_num FROM alembic_version"))
        applied = [row[0] for row in result]
    assert _EXPECTED_HEAD in applied, (
        f"Expected head revision '{_EXPECTED_HEAD}' in alembic_version, found: {applied}"
    )


@pytest.mark.slow
def test_alembic_api_reports_correct_current_revision(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        ctx = MigrationContext.configure(conn)
        current_rev = ctx.get_current_revision()
    assert current_rev == _EXPECTED_HEAD, (
        f"Alembic MigrationContext reports revision '{current_rev}', "
        f"expected '{_EXPECTED_HEAD}'"
    )


@pytest.mark.slow
def test_upgrade_head_is_idempotent(pg_migrated, pg_database_url: str) -> None:
    """Running upgrade head when already at head must succeed without errors."""
    cfg = _make_alembic_config(pg_database_url)
    alembic_command.upgrade(cfg, "head")

    with pg_migrated.connect() as conn:
        ctx = MigrationContext.configure(conn)
        current_rev = ctx.get_current_revision()
    assert current_rev == _EXPECTED_HEAD


@pytest.mark.slow
def test_migration_creates_both_schemas(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        result = conn.execute(
            text(
                "SELECT nspname FROM pg_namespace "
                "WHERE nspname IN ('transactional', 'documental') "
                "ORDER BY nspname"
            )
        )
        schemas = [row[0] for row in result]
    assert "documental" in schemas, "Migration did not create 'documental' schema"
    assert "transactional" in schemas, "Migration did not create 'transactional' schema"


@pytest.mark.slow
def test_migration_creates_all_three_extensions(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        result = conn.execute(
            text(
                "SELECT extname FROM pg_extension "
                "WHERE extname IN ('pgcrypto', 'postgis', 'vector') "
                "ORDER BY extname"
            )
        )
        extensions = [row[0] for row in result]
    missing = {"pgcrypto", "postgis", "vector"} - set(extensions)
    assert not missing, (
        f"Migration 20260614_0001 did not create extensions: {sorted(missing)}. "
        "Install the missing PostgreSQL extensions and re-run."
    )
