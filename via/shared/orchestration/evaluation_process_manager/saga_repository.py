"""Repository for evaluation saga state and transition audit rows."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from via.shared.orchestration.evaluation_process_manager.saga_orm import EvaluationSagaModel, SagaTransitionModel
from via.shared.orchestration.evaluation_process_manager.states import is_valid_transition


class EvaluationSagaRepository:
    """Persist and mutate evaluation saga records within caller transactions."""

    def __init__(self, session: Session) -> None:
        """Create a repository bound to a synchronous SQLAlchemy session."""

        self._session = session

    def add(self, saga: EvaluationSagaModel) -> None:
        """Add a new saga without committing the active transaction."""

        self._session.add(saga)

    def get(self, saga_id: UUID) -> EvaluationSagaModel | None:
        """Load one saga by id."""

        return self._session.get(EvaluationSagaModel, saga_id)

    def record_transition(
        self,
        saga_id: UUID,
        from_status: str | None,
        to_status: str,
        triggered_by: UUID | None,
        failure_cause: str | None = None,
    ) -> SagaTransitionModel:
        """Add an audit row for a saga state attempt."""

        transition = SagaTransitionModel(
            saga_id=saga_id,
            from_status=from_status,
            to_status=to_status,
            triggered_by=triggered_by,
            failure_cause=failure_cause,
        )
        self._session.add(transition)
        return transition

    def transition(
        self,
        saga: EvaluationSagaModel,
        to_status: str,
        triggered_by: UUID | None,
        failure_cause: str | None = None,
    ) -> bool:
        """Move the saga when valid, or record the invalid transition attempt."""

        from_status = saga.status
        if not is_valid_transition(from_status, to_status):
            self.record_invalid_transition(saga, to_status, triggered_by, failure_cause)
            return False
        saga.status = to_status
        self.record_transition(saga.id, from_status, to_status, triggered_by, failure_cause)
        return True

    def record_invalid_transition(
        self,
        saga: EvaluationSagaModel,
        attempted_status: str,
        triggered_by: UUID | None,
        failure_cause: str | None = None,
    ) -> SagaTransitionModel:
        """Record an invalid transition without mutating the saga state."""

        detail = failure_cause or "Transition is not allowed from current state"
        return self.record_transition(
            saga.id,
            saga.status,
            saga.status,
            triggered_by,
            f"Invalid transition to {attempted_status}: {detail}",
        )
