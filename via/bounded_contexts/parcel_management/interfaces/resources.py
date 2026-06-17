"""HTTP resources for Parcel Management."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel


class ParcelMetadataResource(BaseModel):
    """Parcel metadata submitted and returned by the API."""

    name: str
    description: str
    crs: str


class ParcelCreateRequest(BaseModel):
    """Request body for registering a parcel."""

    geometry: dict[str, Any]
    metadata: ParcelMetadataResource


class ParcelUpdateRequest(BaseModel):
    """Request body for updating parcel geometry or metadata."""

    geometry: dict[str, Any] | None = None
    metadata: ParcelMetadataResource | None = None


class ParcelResponse(BaseModel):
    """Parcel response resource."""

    id: UUID
    owner_id: UUID
    geometry: dict[str, Any]
    metadata: ParcelMetadataResource
