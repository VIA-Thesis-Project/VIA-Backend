"""Minimal IAM ORM models for initial VIA migrations."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from via.shared.database.base import Base, TRANSACTIONAL_SCHEMA


class UserModel(Base):
    """Persistent user record for future IAM functionality."""

    __tablename__ = "users"
    __table_args__ = {"schema": TRANSACTIONAL_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AuthAuditLogModel(Base):
    """Audit row for future authentication attempts."""

    __tablename__ = "auth_audit_log"
    __table_args__ = {"schema": TRANSACTIONAL_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attempted_user: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    occurred_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
