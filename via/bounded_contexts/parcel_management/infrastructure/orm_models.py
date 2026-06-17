"""Minimal parcel ORM models for initial VIA migrations."""

from __future__ import annotations

import uuid

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from via.shared.database.base import Base, TRANSACTIONAL_SCHEMA
from via.shared.database.types import Geometry


class ParcelModel(Base):
    """Persistent parcel with PostGIS MultiPolygon geometry."""

    __tablename__ = "parcels"
    __table_args__ = {"schema": TRANSACTIONAL_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    geometry: Mapped[object] = mapped_column(Geometry("MULTIPOLYGON", 4326), nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ParcelVersionModel(Base):
    """Historical parcel snapshot for future parcel updates."""

    __tablename__ = "parcel_version_history"
    __table_args__ = {"schema": TRANSACTIONAL_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parcel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{TRANSACTIONAL_SCHEMA}.parcels.id"), nullable=False)
    metadata_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    geometry_snapshot: Mapped[object | None] = mapped_column(Geometry("MULTIPOLYGON", 4326))
    recorded_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
