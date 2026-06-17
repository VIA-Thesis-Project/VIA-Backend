"""Minimal document ORM models for initial VIA migrations."""

from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from via.shared.database.base import Base, DOCUMENTAL_SCHEMA
from via.shared.database.types import Vector


class DocumentModel(Base):
    """Technical document metadata stored in the documental schema."""

    __tablename__ = "documents"
    __table_args__ = {"schema": DOCUMENTAL_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    format: Mapped[str] = mapped_column(String(10), nullable=False)
    crop_tags: Mapped[list] = mapped_column(JSONB, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uploaded_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")


class DocumentFragmentModel(Base):
    """Searchable document fragment stored only in the documental schema."""

    __tablename__ = "document_fragments"
    __table_args__ = {"schema": DOCUMENTAL_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{DOCUMENTAL_SCHEMA}.documents.id", ondelete="CASCADE"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page_ref: Mapped[int | None] = mapped_column(Integer)
    crop_tags: Mapped[list] = mapped_column(JSONB, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[object | None] = mapped_column(Vector(1536))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
