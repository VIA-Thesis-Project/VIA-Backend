"""Unit tests for the in-memory event bus."""

from __future__ import annotations

from via.shared.event_bus import InMemoryEventBus, Message, MessageKind


def test_message_contract_has_required_fields() -> None:
    message = Message.command("DoWork", {"value": 1})

    assert message.id is not None
    assert message.type == "DoWork"
    assert message.kind == MessageKind.COMMAND
    assert message.payload == {"value": 1}
    assert message.created_at is not None
    assert message.correlation_id is None


def test_in_memory_bus_routes_synchronously_to_registered_handlers() -> None:
    bus = InMemoryEventBus()
    seen: list[Message] = []
    message = Message.event("SomethingHappened", {"ok": True})

    bus.register("SomethingHappened", seen.append)
    bus.publish(message)

    assert seen == [message]
