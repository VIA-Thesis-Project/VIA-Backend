"""Event Bus consumer for recommendation commands."""

from __future__ import annotations

from via.bounded_contexts.recommendation.application.command_service import RecommendationMessageCommandService
from via.shared.event_bus.message import Message
from via.shared.orchestration.evaluation_process_manager.commands import GENERAR_RECOMENDACION_SOLICITADA


class RecommendationConsumer:
    """Consume recommendation commands from the internal Event Bus."""

    def __init__(self, command_service: RecommendationMessageCommandService) -> None:
        """Create a consumer backed by an application command service."""

        self._command_service = command_service

    def handle(self, message: Message) -> None:
        """Handle one GenerarRecomendacionSolicitada command."""

        if message.type != GENERAR_RECOMENDACION_SOLICITADA:
            return
        self._command_service.handle_generation_requested(message)
