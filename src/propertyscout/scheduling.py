"""Reply interpretation, availability rules, and fake calendar integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from propertyscout.schemas import (
    InboundReply,
    MeetingDetails,
    ReplyIntent,
    SchedulingPreferences,
)


class ReplyInterpreter(Protocol):
    def classify(self, reply: InboundReply) -> ReplyIntent: ...


class RuleBasedReplyInterpreter:
    def classify(self, reply: InboundReply) -> ReplyIntent:
        normalized = reply.body.casefold()
        if any(word in normalized for word in ("decline", "not interested", "no thank")):
            return ReplyIntent.DECLINED
        if reply.proposed_times:
            return ReplyIntent.PROPOSED_TIMES
        if "?" in reply.body:
            return ReplyIntent.QUESTION
        return ReplyIntent.OTHER


class CalendarGateway(Protocol):
    def book(self, meeting: MeetingDetails, idempotency_key: str) -> MeetingDetails: ...


class FakeCalendarGateway:
    """Memory-only calendar tool with idempotent booking behavior."""

    def __init__(self) -> None:
        self.bookings: dict[str, MeetingDetails] = {}
        self.booking_attempts = 0

    def book(self, meeting: MeetingDetails, idempotency_key: str) -> MeetingDetails:
        self.booking_attempts += 1
        existing = self.bookings.get(idempotency_key)
        if existing is not None:
            return existing

        booked = meeting.model_copy(update={"external_event_id": f"fake-event-{uuid4()}"})
        self.bookings[idempotency_key] = booked
        return booked


def proposed_meeting(
    reply: InboundReply,
    preferences: SchedulingPreferences,
    attendee_email: str,
) -> MeetingDetails:
    if not reply.proposed_times:
        raise ValueError("A proposed meeting requires at least one proposed time")

    starts_at = reply.proposed_times[0]
    if starts_at.tzinfo is None:
        raise ValueError("Proposed meeting times must include a timezone")

    return MeetingDetails(
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=preferences.meeting_duration_minutes),
        timezone=preferences.timezone,
        attendee_emails=[attendee_email],
    )


def is_within_availability(
    meeting: MeetingDetails,
    preferences: SchedulingPreferences,
) -> bool:
    local_start = meeting.starts_at.astimezone(ZoneInfo(preferences.timezone))
    local_end = meeting.ends_at.astimezone(ZoneInfo(preferences.timezone))
    return (
        local_start.weekday() in preferences.available_weekdays
        and local_start.date() == local_end.date()
        and local_start.hour >= preferences.available_start_hour
        and (
            local_end.hour < preferences.available_end_hour
            or (
                local_end.hour == preferences.available_end_hour
                and local_end.minute == 0
            )
        )
    )
