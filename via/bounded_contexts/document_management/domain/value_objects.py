"""Value objects for Document Management."""

from __future__ import annotations

from enum import StrEnum


class DocumentDomainError(ValueError):
    """Raised when a technical document violates domain rules."""


class DocumentStatus(StrEnum):
    """Supported technical document lifecycle states."""

    ACTIVE = "ACTIVE"
    DELETED = "DELETED"


class DocumentFormat(StrEnum):
    """Supported stored document formats for the 9A base model."""

    PDF = "PDF"
    TXT = "TXT"


def normalize_crop_tags(crop_tags: list[str] | tuple[str, ...]) -> list[str]:
    """Normalize and validate crop tags."""

    normalized = [str(tag).strip() for tag in crop_tags if str(tag).strip()]
    if not normalized:
        raise DocumentDomainError("At least one crop tag is required")
    return list(dict.fromkeys(normalized))


def ensure_non_empty_text(value: str, field_name: str) -> str:
    """Return stripped text or raise when empty."""

    stripped = str(value).strip()
    if not stripped:
        raise DocumentDomainError(f"{field_name} is required")
    return stripped
