"""Synchronous relay worker for the transactional outbox."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from via.config import get_settings
from via.shared.event_bus.event_bus_interface import EventBus
from via.shared.outbox.models import OutboxMessageModel, OutboxStatus


class RelayWorker:
    """Poll pending outbox messages and publish them to the internal bus."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        event_bus: EventBus,
        poll_interval_seconds: int | None = None,
        batch_size: int = 20,
        max_retries: int = 5,
    ) -> None:
        settings = get_settings()
        self.session_factory = session_factory
        self.event_bus = event_bus
        self.poll_interval_seconds = poll_interval_seconds or settings.relay_worker_poll_interval_seconds
        self.batch_size = batch_size
        self.max_retries = max_retries
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the background relay thread if it is not running."""

        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self.run_forever, name="via-relay-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float | None = None) -> None:
        """Signal the relay thread to stop and wait for it."""

        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def run_forever(self) -> None:
        """Poll and relay messages until stopped."""

        while not self._stop_event.is_set():
            self.process_batch()
            time.sleep(self.poll_interval_seconds)

    def process_batch(self) -> int:
        """Process one ordered batch of pending outbox messages."""

        with self.session_factory() as session:
            messages = self._load_pending(session)
            for message in messages:
                self._publish_one(message)
            session.commit()
            return len(messages)

    def _load_pending(self, session: Session) -> list[OutboxMessageModel]:
        statement = (
            select(OutboxMessageModel)
            .where(OutboxMessageModel.status == OutboxStatus.PENDING.value)
            .order_by(OutboxMessageModel.created_at, OutboxMessageModel.id)
            .limit(self.batch_size)
            .with_for_update(skip_locked=True)
        )
        return list(session.execute(statement).scalars().all())

    def _publish_one(self, message: OutboxMessageModel) -> None:
        now = datetime.now(timezone.utc)
        try:
            self.event_bus.publish(message.to_message())
            message.status = OutboxStatus.DISPATCHED.value
            message.dispatched_at = now
            message.last_error = None
        except Exception as exc:
            message.retry_count += 1
            message.last_error = str(exc)
            if message.retry_count >= self.max_retries:
                message.status = OutboxStatus.PERMANENT_FAILURE.value
