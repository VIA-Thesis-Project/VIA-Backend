"""Unit tests for VIA task 24B — Runtime stub replacements.

Verifies that the real adapter implementations that replaced stubs can be
instantiated without raising RuntimeError, and that the extraction/evaluation
consumer factories wire them correctly.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy.orm import Session


# ─── Real adapter instantiation (no RuntimeError on construction) ─────────────


def test_extraction_acl_instantiates_without_error() -> None:
    from via.bounded_contexts.agroenv_extraction.infrastructure.extraction_acl import ExtractionAcl

    acl = ExtractionAcl()
    assert acl is not None


def test_sqlalchemy_extraction_repository_instantiates_with_session() -> None:
    from via.bounded_contexts.agroenv_extraction.infrastructure.extraction_repository import SqlAlchemyExtractionRepository

    session: Session = MagicMock(spec=Session)
    repo = SqlAlchemyExtractionRepository(session)
    assert repo is not None


def test_evaluation_repository_instantiates_with_session() -> None:
    from via.bounded_contexts.viability_evaluation.infrastructure.evaluation_repository import EvaluationRepository

    session: Session = MagicMock(spec=Session)
    repo = EvaluationRepository(session)
    assert repo is not None


# ─── Consumer factory assembly (no RuntimeError on construction) ──────────────


def test_extraction_consumer_builds_without_error(fake_session_factory) -> None:
    """_extraction_consumer must not raise during construction."""
    from via.shared.runtime.application_runtime import _extraction_consumer

    consumer = _extraction_consumer(fake_session_factory)
    assert consumer is not None


def test_evaluation_consumer_builds_without_error(fake_session_factory, fake_settings) -> None:
    """_evaluation_consumer must not raise during construction."""
    from via.shared.runtime.application_runtime import _evaluation_consumer

    consumer = _evaluation_consumer(fake_session_factory, fake_settings)
    assert consumer is not None


# ─── Fixtures ────────────────────────────────────────────────────────────────


import pytest


@pytest.fixture()
def fake_session_factory():
    """Return a callable session factory that yields mock sessions."""
    session = MagicMock(spec=Session)
    return MagicMock(return_value=session)


@pytest.fixture()
def fake_settings():
    from via.config import load_settings

    return load_settings({})
