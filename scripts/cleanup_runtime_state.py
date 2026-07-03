"""Clean transient VIA runtime state from PostgreSQL.

Intended for production troubleshooting when evaluation/recommendation sagas or
outbox messages are stuck. It keeps users, parcels, rulebooks and documents.

Usage from Render Shell:
    PYTHONPATH=. python scripts/cleanup_runtime_state.py --confirm
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


def _count_sql() -> str:
    selects = [
        f"SELECT '{table}' AS table_name, COUNT(*)::bigint AS row_count FROM {table}"
        for table in RUNTIME_TABLES
    ]
    return "\nUNION ALL\n".join(selects)


def _print_counts(conn, title: str) -> None:
    print(f"\n{title}")
    for row in conn.execute(text(_count_sql())):
        print(f"  {row.table_name}: {row.row_count}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean VIA evaluation/outbox runtime state.")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required. Actually executes the TRUNCATE.",
    )
    args = parser.parse_args()

    if not args.confirm:
        print("Dry run only. Add --confirm to truncate runtime tables.")
        return 0

    engine = create_engine(_database_url(), future=True)
    with engine.begin() as conn:
        _print_counts(conn, "Before cleanup")
        conn.execute(text("TRUNCATE " + ", ".join(RUNTIME_TABLES) + " CASCADE"))
        _print_counts(conn, "After cleanup")

    print("\nOK: runtime evaluation/outbox state cleaned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
