"""Event Bus consumer for Agroenvironmental Extraction commands."""

from __future__ import annotations

from via.bounded_contexts.agroenv_extraction.application.command_service import AgroenvExtractionCommandService
from via.shared.event_bus.message import Message
from via.shared.orchestration.evaluation_process_manager.commands import INICIAR_EXTRACCION_AGROAMBIENTAL


class AgroenvExtractionConsumer:
    """Consume extraction commands from the internal Event Bus."""

    def __init__(self, command_service: AgroenvExtractionCommandService) -> None:
        """Create a consumer backed by an application command service."""

        self._command_service = command_service

    def handle(self, message: Message) -> None:
        """Handle one IniciarExtraccionAgroambiental command."""

        if message.type != INICIAR_EXTRACCION_AGROAMBIENTAL:
            return
        self._command_service.handle_start_command(message)
