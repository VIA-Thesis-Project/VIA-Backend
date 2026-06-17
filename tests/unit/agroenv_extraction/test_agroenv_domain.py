"""Unit tests for Agroenvironmental Extraction domain."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from via.bounded_contexts.agroenv_extraction.domain.agroenv_vector import AgroenvVector
from via.bounded_contexts.agroenv_extraction.domain.value_objects import AgroenvExtractionError, TemporalWindow, VariableStatus
from via.bounded_contexts.agroenv_extraction.domain.variable_entry import VariableEntry


def test_variable_entry_preserves_required_traceability_fields() -> None:
    entry = _entry()

    payload = entry.to_payload()
    for field in (
        "variable_name",
        "criterion_id",
        "crop_id",
        "phase_id",
        "dataset_key",
        "band",
        "unit",
        "temporal_resolution",
        "spatial_resolution",
        "scale",
        "reducer",
        "aggregation_method",
        "quality_mask",
        "fallback_allowed",
        "period_key",
        "source",
        "extraction_date",
        "status",
    ):
        assert field in payload
    assert payload["status"] == "OK"


def test_missing_variable_status_allows_empty_value() -> None:
    entry = _entry(status=VariableStatus.CRITERIO_FALTANTE, value=None, source="unavailable")

    assert entry.status == VariableStatus.CRITERIO_FALTANTE
    assert entry.value is None


def test_ok_variable_requires_value() -> None:
    with pytest.raises(AgroenvExtractionError):
        _entry(value=None)


def test_vector_requires_at_least_one_variable() -> None:
    with pytest.raises(AgroenvExtractionError):
        AgroenvVector(uuid4(), uuid4(), TemporalWindow({"start": "2026-01-01"}), [])


def _entry(status: VariableStatus = VariableStatus.OK, value: float | None = 0.8, source: str = "stub") -> VariableEntry:
    return VariableEntry(
        variable_name="ndvi",
        criterion_id="vigor",
        crop_id="cacao",
        phase_id="floracion",
        dataset_key="sentinel-2",
        band="B08",
        unit="index",
        temporal_resolution="monthly",
        spatial_resolution="10m",
        scale=10,
        reducer="median",
        aggregation_method="mean",
        quality_mask={"cloud": "masked"},
        fallback_allowed=True,
        value=value,
        source=source,
        extraction_date=date(2026, 1, 15),
        period_key="2026-01",
        status=status,
    )
