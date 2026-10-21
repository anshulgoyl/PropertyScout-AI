from datetime import datetime
from uuid import uuid4

import pytest
from langgraph.types import Command

from propertyscout.bootstrap import initial_state
from propertyscout.graph import build_graph
from propertyscout.scheduling import FakeCalendarGateway
from propertyscout.schemas import MeetingDetails, WorkflowOutcome, WorkflowStage


def advance_to_reply_pause(calendar_gateway: FakeCalendarGateway | None = None):
    graph = build_graph(calendar_gateway=calendar_gateway)
    config = {"configurable": {"thread_id": f"schedule-{uuid4()}"}}
    paused = graph.invoke(initial_state("shortlist"), config)
    contact_paused = graph.invoke(Command(resume={"decision": "approved"}), config)
    selected = contact_paused["contact_candidates"][0]
    outreach_paused = graph.invoke(
        Command(resume={"contact_id": str(selected.contact_id)}), config
    )
    assert "__interrupt__" in outreach_paused
    reply_paused = graph.invoke(Command(resume={"decision": "approved"}), config)
    assert "__interrupt__" in paused
    assert "__interrupt__" in reply_paused
    return graph, config, selected, reply_paused


def reply(selected, proposed_time: str) -> dict:
    return {
        "message_id": f"reply-{uuid4()}",
        "sender_email": selected.email,
        "received_at": "2026-10-21T12:00:00+02:00",
        "body": "That time works for me.",
        "proposed_times": [proposed_time],
    }


def test_in_policy_time_is_booked_without_extra_approval() -> None:
    graph, config, selected, _ = advance_to_reply_pause()

    result = graph.invoke(
        Command(resume=reply(selected, "2026-10-28T14:00:00+01:00")), config
    )

    assert result["outcome"] == WorkflowOutcome.BRIEF_READY
    assert result["current_stage"] == WorkflowStage.COMPLETE
    assert result["requires_schedule_approval"] is False


def test_out_of_policy_time_requires_approval_before_booking() -> None:
    graph, config, selected, _ = advance_to_reply_pause()
    approval_paused = graph.invoke(
        Command(resume=reply(selected, "2026-10-28T20:00:00+01:00")), config
    )

    assert "__interrupt__" in approval_paused
    assert approval_paused["requires_schedule_approval"] is True

    result = graph.invoke(
        Command(resume={"decision": "approved", "decided_by": "test-investor"}),
        config,
    )
    assert result["outcome"] == WorkflowOutcome.BRIEF_READY
    assert result["approvals"]["schedule_exception"].decided_by == "test-investor"


def test_out_of_policy_time_can_be_rejected() -> None:
    graph, config, selected, _ = advance_to_reply_pause()
    graph.invoke(
        Command(resume=reply(selected, "2026-10-31T14:00:00+01:00")), config
    )

    result = graph.invoke(Command(resume={"decision": "rejected"}), config)

    assert result["outcome"] == WorkflowOutcome.SCHEDULE_REJECTED
    assert result["current_stage"] == WorkflowStage.COMPLETE


def test_reply_from_unexpected_sender_is_rejected() -> None:
    graph, config, selected, _ = advance_to_reply_pause()
    inbound = reply(selected, "2026-10-28T14:00:00+01:00")
    inbound["sender_email"] = "impostor@example.com"

    with pytest.raises(ValueError, match="sender does not match"):
        graph.invoke(Command(resume=inbound), config)


def test_fake_calendar_gateway_is_idempotent() -> None:
    gateway = FakeCalendarGateway()
    meeting = MeetingDetails(
        starts_at=datetime.fromisoformat("2026-10-28T14:00:00+01:00"),
        ends_at=datetime.fromisoformat("2026-10-28T14:30:00+01:00"),
        timezone="Europe/Berlin",
        attendee_emails=["broker@example.com"],
    )

    first = gateway.book(meeting, "stable-key")
    second = gateway.book(meeting, "stable-key")

    assert first == second
    assert len(gateway.bookings) == 1
    assert gateway.booking_attempts == 2
