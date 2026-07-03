"""Clean VIA runtime or application state from PostgreSQL.

Intended for production troubleshooting when evaluation/recommendation sagas or
outbox messages are stuck.

Usage:
    PYTHONPATH=. python scripts/cleanup_runtime_state.py --confirm
    PYTHONPATH=. python scripts/cleanup_runtime_state.py --scope all --confirm
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine, text


RUNTIME_TABLES = (
    "transactional.recommendations",
    "transactional.agronomy_gaps",
    "transactional.limiting_factors",
    "transactional.evaluation_criterion_details",
    "transactional.evaluation_results",
    "transactional.agroenv_variable_entries",
    "transactional.agroenv_vectors",
    "transactional.processed_message_ids",
    "transactional.outbox_messages",
    "transactional.saga_transitions",
    "transactional.evaluation_sagas",
)

ALL_TABLES = (
    "documental.document_fragments",
    "documental.documents",
    "transactional.recommendations",
    "transactional.agronomy_gaps",
    "transactional.limiting_factors",
    "transactional.evaluation_criterion_details",
    "transactional.evaluation_results",
    "transactional.agroenv_variable_entries",
    "transactional.agroenv_vectors",
    "transactional.processed_message_ids",
    "transactional.outbox_messages",
    "transactional.saga_transitions",
    "transactional.evaluation_sagas",
    "transactional.parcel_version_history",
    "transactional.parcels",
    "transactional.rulebook_phase_requirements",
    "transactional.rulebook_phases",
    "transactional.rulebook_criteria",
    "transactional.rulebooks",
    "transactional.auth_audit_log",
    "transactional.users",
)


def _database_url() -> str:
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        print("ERROR: DATABASE_URL is required.", file=sys.stderr)
        raise SystemExit(2)
    if raw.startswith("postgresql://"):
        raw = raw.replace("postgresql://", "postgresql+psycopg2://", 1)
    if not raw.startswith("postgresql+psycopg2://"):
        print("ERROR: DATABASE_URL must use PostgreSQL/psycopg2.", file=sys.stderr)
        raise SystemExit(2)
    return raw


def _count_sql(tables: tuple[str, ...]) -> str:
    selects = [
        f"SELECT '{table}' AS table_name, COUNT(*)::bigint AS row_count FROM {table}"
        for table in tables
    ]
    return "\nUNION ALL\n".join(selects)


def _print_counts(conn, title: str, tables: tuple[str, ...]) -> None:
    print(f"\n{title}")
    for row in conn.execute(text(_count_sql(tables))):
        print(f"  {row.table_name}: {row.row_count}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean VIA PostgreSQL state.")
    parser.add_argument(
        "--scope",
        choices=("runtime", "all"),
        default="runtime",
        help=(
            "runtime keeps users, parcels, documents and rulebooks. "
            "all truncates application data too; migrations/schemas remain."
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required. Actually executes the TRUNCATE.",
    )
    args = parser.parse_args()
    tables = ALL_TABLES if args.scope == "all" else RUNTIME_TABLES

    if not args.confirm:
        print(f"Dry run only. Add --confirm to truncate {args.scope} tables.")
        for table in tables:
            print(f"  {table}")
        return 0

    engine = create_engine(_database_url(), future=True)
    with engine.begin() as conn:
        _print_counts(conn, f"Before cleanup ({args.scope})", tables)
        conn.execute(text("TRUNCATE " + ", ".join(tables) + " CASCADE"))
        _print_counts(conn, f"After cleanup ({args.scope})", tables)

    print(f"\nOK: {args.scope} state cleaned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
