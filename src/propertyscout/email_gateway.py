"""Email side-effect boundary and an in-memory fake gateway."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from propertyscout.schemas import EmailSendReceipt, OutreachDraft


class EmailGateway(Protocol):
    def send(self, draft: OutreachDraft, idempotency_key: str) -> EmailSendReceipt: ...


class FakeEmailGateway:
    """Records messages in memory and deduplicates repeated send requests."""

    def __init__(self) -> None:
        self.sent_messages: dict[str, EmailSendReceipt] = {}
        self.send_attempts = 0

    def send(self, draft: OutreachDraft, idempotency_key: str) -> EmailSendReceipt:
        self.send_attempts += 1
        existing = self.sent_messages.get(idempotency_key)
        if existing is not None:
            return existing

        receipt = EmailSendReceipt(
            provider_message_id=f"fake-{uuid4()}",
            idempotency_key=idempotency_key,
            recipient_email=draft.recipient_email,
            sent_at=datetime.now(UTC),
        )
        self.sent_messages[idempotency_key] = receipt
        return receipt

