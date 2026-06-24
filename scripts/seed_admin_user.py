"""Seed or update an admin user in the VIA PostgreSQL database.

Usage (PowerShell):
    $env:DATABASE_URL="postgresql+psycopg2://via_user:via_password@localhost:5433/via_test"
    $env:SEED_ADMIN_EMAIL="admin@via.local"
    $env:SEED_ADMIN_PASSWORD="Admin123456"
    $env:SEED_ADMIN_NAME="Administrador VIA"   # optional, not persisted (no full_name column)
    python scripts/seed_admin_user.py
"""

from __future__ import annotations

import os
import sys
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from via.bounded_contexts.iam.domain.role import Role
from via.bounded_contexts.iam.infrastructure.orm_models import UserModel
from via.bounded_contexts.iam.infrastructure.password_hasher import BcryptPasswordHasher


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"ERROR: {name} is required but not set.", file=sys.stderr)
        sys.exit(1)
    return value


def main() -> None:
    database_url = _require_env("DATABASE_URL")
    email = _require_env("SEED_ADMIN_EMAIL")
    password = _require_env("SEED_ADMIN_PASSWORD")

    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if not database_url.startswith("postgresql+psycopg2://"):
        print("ERROR: DATABASE_URL must be a PostgreSQL connection string.", file=sys.stderr)
        sys.exit(1)

    name_hint = os.environ.get("SEED_ADMIN_NAME", "").strip()
    if name_hint:
        # Informational only — the users table has no full_name column.
        print(f"Note: SEED_ADMIN_NAME='{name_hint}' accepted but not persisted (no full_name column in schema).")

    hasher = BcryptPasswordHasher()
    hashed = hasher.hash(password)

    engine = create_engine(database_url, future=True)
    try:
        with Session(engine) as session:
            stmt = select(UserModel).where(UserModel.email == email.strip().lower())
            existing = session.execute(stmt).scalar_one_or_none()

            if existing is None:
                session.add(UserModel(
                    id=uuid.uuid4(),
                    email=email.strip().lower(),
                    hashed_password=hashed,
                    role=Role.ADMINISTRADOR,
                ))
                action = "created"
            else:
                existing.hashed_password = hashed
                existing.role = Role.ADMINISTRADOR
                action = "updated"

            session.commit()
    finally:
        engine.dispose()

    print(f"Admin user '{email}' {action} with role {Role.ADMINISTRADOR}.")


if __name__ == "__main__":
    main()
