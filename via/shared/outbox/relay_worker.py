"""Synchronous relay worker for the transactional outbox.

Dispatch happens in three phases so no database locks are held while message
handlers run (handlers may call GEE or LLM providers and take minutes):

1. Claim: select PENDING rows FOR UPDATE SKIP LOCKED, mark them IN_PROGRESS
   and commit immediately, releasing all locks.
2. Publish: deliver each claimed message to the in-process bus with no open
   transaction.
3. Finalize: in a new short transaction, mark DISPATCHED on success or revert
   to PENDING (incrementing retry_count) / PERMANENT_FAILURE on failure.

If the process dies between claim and finalize, rows stay IN_PROGRESS and are
reclaimed after ``stale_claim_timeout_seconds`` — at-least-once delivery, with
consumer-level idempotency (processed_message_ids) absorbing redeliveries.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from via.config import get_settings
from via.shared.event_bus.event_bus_interface import EventBus
from via.shared.event_bus.message import Message
from via.shared.outbox.models import OutboxMessageModel, OutboxStatus


DEFAULT_STALE_CLAIM_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class ClaimedMessage:
    """Detached copy of one claimed outbox row, safe to use without locks."""

    message_id: UUID
    message: Message


class RelayWorker:
    """Poll pending outbox messages and publish them to the internal bus."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        event_bus: EventBus,
        poll_interval_seconds: int | None = None,
        batch_size: int = 20,
        max_retries: int = 5,
        stale_claim_timeout_seconds: int = DEFAULT_STALE_CLAIM_TIMEOUT_SECONDS,
    ) -> None:
        settings = get_settings()
        self.session_factory = session_factory
        self.event_bus = event_bus
        self.poll_interval_seconds = poll_interval_seconds or settings.relay_worker_poll_interval_seconds
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.stale_claim_timeout_seconds = stale_claim_timeout_seconds
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
        """Claim, publish and finalize one ordered batch of outbox messages."""

        claimed = self._claim_batch()
        if not claimed:
            return 0
        outcomes = [(item.message_id, self._publish_one(item.message)) for item in claimed]
        self._finalize_batch(outcomes)
        return len(claimed)

    def _claim_batch(self) -> list[ClaimedMessage]:
        """Mark one batch IN_PROGRESS and commit, releasing row locks immediately."""

        with self.session_factory() as session:
            rows = self._load_pending(session)
            now = datetime.now(timezone.utc)
            claimed: list[ClaimedMessage] = []
            for row in rows:
                row.status = OutboxStatus.IN_PROGRESS.value
                row.claimed_at = now
                claimed.append(ClaimedMessage(message_id=row.id, message=row.to_message()))
            session.commit()
            return claimed

    def _load_pending(self, session: Session) -> list[OutboxMessageModel]:
        stale_cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.stale_claim_timeout_seconds)
        statement = (
            select(OutboxMessageModel)
            .where(
                or_(
                    OutboxMessageModel.status == OutboxStatus.PENDING.value,
                    and_(
                        OutboxMessageModel.status == OutboxStatus.IN_PROGRESS.value,
                        OutboxMessageModel.claimed_at < stale_cutoff,
                    ),
                )
            )
            .order_by(OutboxMessageModel.created_at, OutboxMessageModel.id)
            .limit(self.batch_size)
            .with_for_update(skip_locked=True)
        )
        return list(session.execute(statement).scalars().all())

    def _publish_one(self, message: Message) -> str | None:
        """Publish outside any transaction; return None on success or the error text."""

        try:
            self.event_bus.publish(message)
            return None
        except Exception as exc:
            return str(exc)

    def _finalize_batch(self, outcomes: list[tuple[UUID, str | None]]) -> None:
        """Record publish outcomes in one short transaction."""

        with self.session_factory() as session:
            for message_id, error in outcomes:
                row = session.get(OutboxMessageModel, message_id)
                if row is None:
                    continue
                self._apply_outcome(row, error)
            session.commit()

    def _apply_outcome(self, row: OutboxMessageModel, error: str | None) -> None:
        """Mutate one claimed row according to its publish outcome."""

        row.claimed_at = None
        if error is None:
            row.status = OutboxStatus.DISPATCHED.value
            row.dispatched_at = datetime.now(timezone.utc)
            row.last_error = None
            return
        row.retry_count += 1
        row.last_error = error
        if row.retry_count >= self.max_retries:
            row.status = OutboxStatus.PERMANENT_FAILURE.value
        else:
            row.status = OutboxStatus.PENDING.value
