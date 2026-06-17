"""Import all ORM models so Alembic can see shared metadata."""

from __future__ import annotations

from via.bounded_contexts.agroenv_extraction.infrastructure import orm_models as agroenv_models
from via.bounded_contexts.document_management.infrastructure import orm_models as document_models
from via.bounded_contexts.iam.infrastructure import orm_models as iam_models
from via.bounded_contexts.parcel_management.infrastructure import orm_models as parcel_models
from via.bounded_contexts.recommendation.infrastructure import orm_models as recommendation_models
from via.bounded_contexts.rulebook_management.infrastructure import orm_models as rulebook_models
from via.bounded_contexts.viability_evaluation.infrastructure import orm_models as evaluation_models
from via.shared.idempotency import processed_message_store as idempotency_models
from via.shared.orchestration.evaluation_process_manager import saga_orm as saga_models
from via.shared.outbox import models as outbox_models

__all__ = [
    "agroenv_models",
    "document_models",
    "evaluation_models",
    "iam_models",
    "idempotency_models",
    "outbox_models",
    "parcel_models",
    "recommendation_models",
    "rulebook_models",
    "saga_models",
]
