"""Minimal recommendation ORM models for initial migrations."""

from __future__ import annotations

import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from via.shared.database.base import Base, TRANSACTIONAL_SCHEMA


class RecommendationModel(Base):
    """Persisted supported recommendation text."""

    __tablename__ = "recommendations"
    __table_args__ = {"schema": TRANSACTIONAL_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    evaluation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{TRANSACTIONAL_SCHEMA}.evaluation_sagas.id"), nullable=False)
    crop_id: Mapped[str] = mapped_column(String(100), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    fragment_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, server_default="template")
    generated_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
