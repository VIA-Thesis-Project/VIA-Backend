"""Event Bus consumer for viability evaluation commands."""

from __future__ import annotations

from via.bounded_contexts.viability_evaluation.application.command_service import ViabilityEvaluationCommandService
from via.shared.event_bus.message import Message
from via.shared.orchestration.evaluation_process_manager.commands import EJECUTAR_EVALUACION_VIABILIDAD


class ViabilityEvaluationConsumer:
    """Consume evaluation commands from the internal Event Bus."""

    def __init__(self, command_service: ViabilityEvaluationCommandService) -> None:
        """Create a consumer backed by an application command service."""

        self._command_service = command_service

    def handle(self, message: Message) -> None:
        """Handle one EjecutarEvaluacionViabilidad command."""

        if message.type != EJECUTAR_EVALUACION_VIABILIDAD:
            return
        self._command_service.handle_execute_command(message)
