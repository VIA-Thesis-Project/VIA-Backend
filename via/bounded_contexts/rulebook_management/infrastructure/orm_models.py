"""Minimal rulebook ORM models for initial VIA migrations."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from via.shared.database.base import Base, TRANSACTIONAL_SCHEMA


class RulebookModel(Base):
    """Versioned crop rulebook record."""

    __tablename__ = "rulebooks"
    __table_args__ = (UniqueConstraint("crop_id", "version"), {"schema": TRANSACTIONAL_SCHEMA})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    crop_id: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CriterionModel(Base):
    """Rulebook criterion without phase-specific membership function."""

    __tablename__ = "rulebook_criteria"
    __table_args__ = {"schema": TRANSACTIONAL_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    rulebook_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{TRANSACTIONAL_SCHEMA}.rulebooks.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    is_critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    critical_policy: Mapped[str | None] = mapped_column(String(20))
    penalty_factor: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    ahp_weight: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    doc_source: Mapped[str | None] = mapped_column(Text)
    technical_notes: Mapped[str | None] = mapped_column(Text)


class RulebookPhaseModel(Base):
    """Phenological phase for one rulebook."""

    __tablename__ = "rulebook_phases"
    __table_args__ = {"schema": TRANSACTIONAL_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    rulebook_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{TRANSACTIONAL_SCHEMA}.rulebooks.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False)


class PhaseRequirementModel(Base):
    """Criterion by phase requirement with the phase-specific membership function."""

    __tablename__ = "rulebook_phase_requirements"
    __table_args__ = (UniqueConstraint("criterion_id", "phase_id"), {"schema": TRANSACTIONAL_SCHEMA})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    criterion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{TRANSACTIONAL_SCHEMA}.rulebook_criteria.id"), nullable=False)
    phase_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{TRANSACTIONAL_SCHEMA}.rulebook_phases.id"), nullable=False)
    membership_fn: Mapped[dict] = mapped_column(JSONB, nullable=False)
    phase_weight: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    temporal_periods: Mapped[list] = mapped_column(JSONB, nullable=False)
    extraction_binding: Mapped[dict] = mapped_column(JSONB, nullable=False)
