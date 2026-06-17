"""Event handlers for wiring the evaluation Process Manager to the bus."""

from __future__ import annotations

from via.shared.event_bus.message import Message
from via.shared.orchestration.evaluation_process_manager.process_manager import (
    PROCESS_MANAGER_CONSUMER,
    EvaluationProcessManager,
)


class EvaluationProcessManagerEventHandler:
    """Callable adapter that delegates incoming events to the Process Manager."""

    def __init__(self, process_manager: EvaluationProcessManager, consumer_name: str = PROCESS_MANAGER_CONSUMER) -> None:
        """Create a handler with a stable idempotency consumer name."""

        self._process_manager = process_manager
        self._consumer_name = consumer_name

    def __call__(self, message: Message) -> None:
        """Process one message through the saga coordinator."""

        self._process_manager.handle_event(message, self._consumer_name)
