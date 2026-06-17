"""Minimal viability evaluation ORM models for initial migrations."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from via.shared.database.base import Base, TRANSACTIONAL_SCHEMA


class EvaluationResultModel(Base):
    """Persisted crop evaluation result."""

    __tablename__ = "evaluation_results"
    __table_args__ = {"schema": TRANSACTIONAL_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    evaluation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{TRANSACTIONAL_SCHEMA}.evaluation_sagas.id"), nullable=False)
    crop_id: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    calc_condition: Mapped[str] = mapped_column(String(20), nullable=False)
    viability_category: Mapped[str] = mapped_column(String(15), nullable=False)
    rank_position: Mapped[int | None] = mapped_column(Integer)
    rulebook_version: Mapped[int] = mapped_column(Integer, nullable=False)
    entropy_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    computed_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EvaluationCriterionDetailModel(Base):
    """Persisted criterion traceability for an evaluation result."""

    __tablename__ = "evaluation_criterion_details"
    __table_args__ = {"schema": TRANSACTIONAL_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    result_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{TRANSACTIONAL_SCHEMA}.evaluation_results.id"), nullable=False)
    criterion_id: Mapped[str] = mapped_column(String(100), nullable=False)
    memberships_by_period: Mapped[dict] = mapped_column(JSONB, nullable=False)
    aggregated_by_phase: Mapped[dict] = mapped_column(JSONB, nullable=False)
    aggregated_membership: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    w_ahp: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    w_entropy: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    w_hybrid: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    entropy_series_used: Mapped[bool] = mapped_column(Boolean, nullable=False)
    entropy_fallback_reason: Mapped[str | None] = mapped_column(Text)


class AgronomyGapModel(Base):
    """Persisted agronomic gap for a crop result."""

    __tablename__ = "agronomy_gaps"
    __table_args__ = {"schema": TRANSACTIONAL_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    result_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{TRANSACTIONAL_SCHEMA}.evaluation_results.id"), nullable=False)
    criterion_id: Mapped[str] = mapped_column(String(100), nullable=False)
    phase_id: Mapped[str] = mapped_column(String(100), nullable=False)
    most_limiting_period: Mapped[str] = mapped_column(String(50), nullable=False)
    observed_value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    optimal_limit: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    gap_value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)


class LimitingFactorModel(Base):
    """Persisted limiting factor traceability."""

    __tablename__ = "limiting_factors"
    __table_args__ = {"schema": TRANSACTIONAL_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    result_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{TRANSACTIONAL_SCHEMA}.evaluation_results.id"), nullable=False)
    criterion_id: Mapped[str] = mapped_column(String(100), nullable=False)
    phase_id: Mapped[str] = mapped_column(String(100), nullable=False)
    policy: Mapped[str] = mapped_column(String(20), nullable=False)
    penalty_factor: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    observed_value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    optimal_limit: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    membership: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    doc_source: Mapped[str | None] = mapped_column(Text)
