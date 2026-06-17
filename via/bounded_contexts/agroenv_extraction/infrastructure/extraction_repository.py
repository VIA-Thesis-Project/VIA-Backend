"""SQLAlchemy repository for Agroenvironmental Extraction."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from via.bounded_contexts.agroenv_extraction.application.ports import IExtractionRepository
from via.bounded_contexts.agroenv_extraction.domain.agroenv_vector import AgroenvVector
from via.bounded_contexts.agroenv_extraction.domain.variable_entry import VariableEntry
from via.bounded_contexts.agroenv_extraction.infrastructure.orm_models import AgroenvVariableEntryModel, AgroenvVectorModel


class SqlAlchemyExtractionRepository(IExtractionRepository):
    """Persist agroenvironmental vectors with a synchronous SQLAlchemy Session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, vector: AgroenvVector) -> None:
        """Persist one vector header and all variable entries."""

        self._session.add(
            AgroenvVectorModel(
                id=vector.id,
                evaluation_id=vector.evaluation_id,
                parcel_id=vector.parcel_id,
                temporal_window=vector.temporal_window.to_mapping(),
                extracted_at=vector.extracted_at,
            )
        )
        # Flush the vector INSERT before entries so the FK constraint is satisfied.
        # SQLAlchemy's UoW does not auto-order cross-schema FK inserts without a
        # mapped relationship(), so we enforce ordering explicitly.
        self._session.flush()
        for entry in vector.variables:
            self._session.add(_entry_to_model(vector.id, entry))


def _entry_to_model(vector_id: object, entry: VariableEntry) -> AgroenvVariableEntryModel:
    return AgroenvVariableEntryModel(
        id=entry.id,
        vector_id=vector_id,
        variable_name=entry.variable_name,
        criterion_id=entry.criterion_id,
        crop_id=entry.crop_id,
        phase_id=entry.phase_id,
        dataset_key=entry.dataset_key,
        band=entry.band,
        unit=entry.unit,
        temporal_resolution=entry.temporal_resolution,
        spatial_resolution=entry.spatial_resolution,
        scale=Decimal(str(entry.scale)) if entry.scale is not None else None,
        reducer=entry.reducer,
        aggregation_method=entry.aggregation_method,
        quality_mask=entry.quality_mask,
        fallback_allowed=entry.fallback_allowed,
        value=Decimal(str(entry.value)) if entry.value is not None else None,
        source=entry.source,
        extraction_date=entry.extraction_date,
        period_key=entry.period_key,
        status=entry.status.value,
    )
