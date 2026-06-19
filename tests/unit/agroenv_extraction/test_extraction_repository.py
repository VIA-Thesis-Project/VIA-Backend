"""Unit tests for Agroenvironmental Extraction repository mapping."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from sqlalchemy import Text

from via.bounded_contexts.agroenv_extraction.domain.agroenv_vector import AgroenvVector
from via.bounded_contexts.agroenv_extraction.domain.value_objects import TemporalWindow, VariableStatus
from via.bounded_contexts.agroenv_extraction.domain.variable_entry import VariableEntry
from via.bounded_contexts.agroenv_extraction.infrastructure.extraction_repository import SqlAlchemyExtractionRepository
from via.bounded_contexts.agroenv_extraction.infrastructure.orm_models import AgroenvVariableEntryModel, AgroenvVectorModel


LONG_SOURCE = "GEE:ECMWF/ERA5_LAND/MONTHLY_AGGR:temperature_2m:centroid_sample:scale=11132"


def test_repository_maps_vector_and_variable_traceability_to_existing_tables() -> None:
    session = FakeSession()
    vector = AgroenvVector(uuid4(), uuid4(), TemporalWindow({"start": "2026-01-01"}), [_entry()])

    SqlAlchemyExtractionRepository(session).save(vector)  # type: ignore[arg-type]

    vector_model = next(model for model in session.added if isinstance(model, AgroenvVectorModel))
    entry_model = next(model for model in session.added if isinstance(model, AgroenvVariableEntryModel))
    assert vector_model.evaluation_id == vector.evaluation_id
    assert entry_model.variable_name == "ndvi"
    assert entry_model.criterion_id == "vigor"
    assert entry_model.crop_id == "cacao"
    assert entry_model.phase_id == "floracion"
    assert entry_model.dataset_key == "sentinel-2"
    assert entry_model.band == "B08"
    assert entry_model.unit == "index"
    assert entry_model.temporal_resolution == "monthly"
    assert entry_model.spatial_resolution == "10m"
    assert entry_model.reducer == "median"
    assert entry_model.aggregation_method == "mean"
    assert entry_model.quality_mask == {"cloud": "masked"}
    assert entry_model.fallback_allowed is True
    assert entry_model.period_key == "2026-01"
    assert entry_model.status == "OK"


def test_repository_persists_long_source_without_truncating_traceability() -> None:
    session = FakeSession()
    vector = AgroenvVector(uuid4(), uuid4(), TemporalWindow({"start": "2026-01-01"}), [_entry(source=LONG_SOURCE)])

    SqlAlchemyExtractionRepository(session).save(vector)  # type: ignore[arg-type]

    entry_model = next(model for model in session.added if isinstance(model, AgroenvVariableEntryModel))
    assert entry_model.source == LONG_SOURCE
    assert "centroid_sample" in entry_model.source
    assert entry_model.source.endswith("scale=11132")


def test_agroenv_variable_entry_trace_columns_allow_demo_source_lengths() -> None:
    columns = AgroenvVariableEntryModel.__table__.c

    assert isinstance(columns.source.type, Text)
    assert columns.dataset_key.type.length == 150
    assert columns.band.type.length == 128
    assert columns.variable_name.type.length == 100
    assert columns.period_key.type.length == 100
    assert columns.unit.type.length == 50
    assert columns.status.type.length == 20


class FakeSession:
    """Session double that records ORM instances."""

    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def flush(self) -> None:
        pass


def _entry(source: str = "stub") -> VariableEntry:
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
        value=0.8,
        source=source,
        extraction_date=date(2026, 1, 15),
        period_key="2026-01",
        status=VariableStatus.OK,
    )
