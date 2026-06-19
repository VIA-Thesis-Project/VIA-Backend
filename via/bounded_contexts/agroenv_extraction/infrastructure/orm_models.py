"""Minimal agroenvironmental extraction ORM models for initial migrations."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from via.shared.database.base import Base, TRANSACTIONAL_SCHEMA


class AgroenvVectorModel(Base):
    """Persisted extracted vector header."""

    __tablename__ = "agroenv_vectors"
    __table_args__ = {"schema": TRANSACTIONAL_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    evaluation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    parcel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    temporal_window: Mapped[dict] = mapped_column(JSONB, nullable=False)
    extracted_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AgroenvVariableEntryModel(Base):
    """Persisted extracted variable entry."""

    __tablename__ = "agroenv_variable_entries"
    __table_args__ = {"schema": TRANSACTIONAL_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vector_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{TRANSACTIONAL_SCHEMA}.agroenv_vectors.id"), nullable=False)
    variable_name: Mapped[str] = mapped_column(String(100), nullable=False)
    criterion_id: Mapped[str] = mapped_column(String(100), nullable=False)
    crop_id: Mapped[str] = mapped_column(String(100), nullable=False)
    phase_id: Mapped[str] = mapped_column(String(100), nullable=False)
    dataset_key: Mapped[str] = mapped_column(String(150), nullable=False)
    band: Mapped[str] = mapped_column(String(128), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    temporal_resolution: Mapped[str] = mapped_column(String(50), nullable=False)
    spatial_resolution: Mapped[str | None] = mapped_column(String(50))
    scale: Mapped[Decimal | None] = mapped_column(Numeric)
    reducer: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregation_method: Mapped[str] = mapped_column(String(100), nullable=False)
    quality_mask: Mapped[dict | None] = mapped_column(JSONB)
    fallback_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_date: Mapped[object] = mapped_column(Date, nullable=False)
    period_key: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
