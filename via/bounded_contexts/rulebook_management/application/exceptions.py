"""Application exceptions for Rulebook Management."""

from __future__ import annotations


class RulebookNotFoundError(LookupError):
    """Raised when a requested rulebook does not exist."""


class ActiveRulebookNotFoundError(LookupError):
    """Raised when a crop has no active rulebook."""


class RulebookApplicationError(ValueError):
    """Raised when an application-level rulebook command is invalid."""
