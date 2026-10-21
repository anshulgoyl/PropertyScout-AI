from datetime import datetime

from propertyscout.analyst import RuleBasedReasoner, analyse_property
from propertyscout.bootstrap import default_criteria
from propertyscout.fixtures import sample_properties
from propertyscout.meeting_intelligence import TemplateMeetingBriefService
from propertyscout.schemas import InboundReply, MeetingDetails


def test_template_brief_uses_verified_analysis_and_user_priorities() -> None:
    property_listing = sample_properties()["shortlist"]
    analysis = analyse_property(property_listing, default_criteria(), RuleBasedReasoner())
    meeting = MeetingDetails(
        starts_at=datetime.fromisoformat("2026-10-28T14:00:00+01:00"),
        ends_at=datetime.fromisoformat("2026-10-28T14:30:00+01:00"),
        timezone="Europe/Berlin",
        attendee_emails=["broker@example.com"],
        external_event_id="fake-event-1",
    )
    reply = InboundReply(
        message_id="reply-1",
        sender_email="broker@example.com",
        received_at=datetime.fromisoformat("2026-10-21T12:00:00+02:00"),
        body="Wednesday works.",
        proposed_times=[meeting.starts_at],
    )

    brief = TemplateMeetingBriefService().prepare(
        property_listing,
        analysis,
        meeting,
        reply,
        ["Confirm whether the tenant has given notice."],
    )

    assert "210,000 EUR" in brief.investment_summary
    assert "7.20%" in brief.investment_summary
    assert "Confirm whether the tenant has given notice." in brief.open_questions
    assert brief.risks == analysis.risks
    assert brief.evidence == analysis.evidence


def test_template_brief_deduplicates_user_priorities() -> None:
    property_listing = sample_properties()["shortlist"]
    analysis = analyse_property(property_listing, default_criteria(), RuleBasedReasoner())
    meeting = MeetingDetails(
        starts_at=datetime.fromisoformat("2026-10-28T14:00:00+01:00"),
        ends_at=datetime.fromisoformat("2026-10-28T14:30:00+01:00"),
        timezone="Europe/Berlin",
        attendee_emails=["broker@example.com"],
        external_event_id="fake-event-1",
    )
    reply = InboundReply(
        message_id="reply-1",
        sender_email="broker@example.com",
        received_at=datetime.fromisoformat("2026-10-21T12:00:00+02:00"),
        body="Wednesday works.",
    )

    brief = TemplateMeetingBriefService().prepare(
        property_listing,
        analysis,
        meeting,
        reply,
        ["Ask about the roof.", "Ask about the roof."],
    )

    assert brief.open_questions.count("Ask about the roof.") == 1
