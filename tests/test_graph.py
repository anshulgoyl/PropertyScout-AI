from datetime import datetime

from langgraph.types import Command

from propertyscout.bootstrap import initial_state
from propertyscout.graph import build_graph
from propertyscout.schemas import WorkflowOutcome, WorkflowStage


def invoke_fixture(property_key: str):
    graph = build_graph()
    config = {"configurable": {"thread_id": f"test-{property_key}"}}
    return graph, config, graph.invoke(initial_state(property_key), config)


def test_property_above_budget_is_rejected_by_scout() -> None:
    _, _, result = invoke_fixture("reject")

    assert result["outcome"] == WorkflowOutcome.SCOUT_REJECTED
    assert result["current_stage"] == WorkflowStage.COMPLETE
    assert "analysis" not in result


def test_missing_rent_routes_to_research() -> None:
    _, _, result = invoke_fixture("research")

    assert result["outcome"] == WorkflowOutcome.NEEDS_RESEARCH
    assert result["analysis"].missing_critical_data == ["annual_rent"]
    assert result["current_stage"] == WorkflowStage.COMPLETE


def test_promising_property_pauses_and_resumes_after_approval() -> None:
    graph, config, paused = invoke_fixture("shortlist")

    assert "__interrupt__" in paused
    assert "outcome" not in paused
    assert paused["current_stage"] == WorkflowStage.ANALYSIS

    contact_paused = graph.invoke(
        Command(resume={"decision": "approved", "decided_by": "test-investor"}),
        config,
    )

    assert "__interrupt__" in contact_paused
    assert len(contact_paused["contact_candidates"]) == 2

    selected_contact = contact_paused["contact_candidates"][0]
    outreach_paused = graph.invoke(
        Command(resume={"contact_id": str(selected_contact.contact_id)}),
        config,
    )

    assert "__interrupt__" in outreach_paused
    assert outreach_paused["outreach_draft"].recipient_contact_id == selected_contact.contact_id

    reply_paused = graph.invoke(
        Command(
            resume={
                "decision": "approved",
                "decided_by": "test-investor",
                "subject": "Approved edited subject",
                "body": "Approved edited message body.",
            }
        ),
        config,
    )

    assert "__interrupt__" in reply_paused
    assert reply_paused["outcome"] == WorkflowOutcome.OUTREACH_SENT
    assert reply_paused["current_stage"] == WorkflowStage.AWAITING_REPLY
    assert reply_paused["approvals"]["shortlist"].decided_by == "test-investor"
    assert reply_paused["selected_contact"].contact_id == selected_contact.contact_id
    assert reply_paused["outreach_draft"].subject == "Approved edited subject"
    assert reply_paused["outreach_draft"].body == "Approved edited message body."
    assert reply_paused["approvals"]["outreach"].decision.value == "approved"
    assert reply_paused["email_send_receipt"].recipient_email == selected_contact.email

    scheduled = graph.invoke(
        Command(
            resume={
                "message_id": "broker-reply-1",
                "sender_email": selected_contact.email,
                "received_at": datetime.now().astimezone().isoformat(),
                "body": "Wednesday at 14:00 works for me.",
                "proposed_times": ["2026-10-28T14:00:00+01:00"],
            }
        ),
        config,
    )

    assert scheduled["outcome"] == WorkflowOutcome.BRIEF_READY
    assert scheduled["current_stage"] == WorkflowStage.COMPLETE
    assert scheduled["meeting"].external_event_id.startswith("fake-event-")
    assert scheduled["meeting_brief"].open_questions
