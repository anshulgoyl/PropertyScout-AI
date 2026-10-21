"""LangGraph orchestration for the first PropertyScout vertical slice."""

from __future__ import annotations

from typing import Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from propertyscout.analyst import InvestmentReasoner
from propertyscout.contact_research import ContactResearchService
from propertyscout.email_gateway import EmailGateway, FakeEmailGateway
from propertyscout.meeting_intelligence import MeetingBriefService
from propertyscout.nodes import (
    complete_workflow,
    contact_resolution,
    create_book_meeting,
    create_contact_researcher,
    create_investment_analyst,
    create_meeting_intelligence,
    create_outreach_agent,
    create_scheduling_agent,
    create_send_outreach,
    initialize_deal,
    mark_analysis_rejected,
    mark_contact_not_found,
    mark_scout_rejected,
    market_scout,
    outreach_approval,
    request_more_property_data,
    schedule_approval,
    select_confident_contact,
    shortlist_approval,
    wait_for_reply,
)
from propertyscout.outreach import OutreachDraftingService
from propertyscout.scheduling import (
    CalendarGateway,
    FakeCalendarGateway,
    ReplyInterpreter,
)
from propertyscout.schemas import (
    AnalysisRecommendation,
    ApprovalDecision,
    ApprovalRecord,
    AuditEvent,
    ContactCandidate,
    ContactType,
    EmailSendReceipt,
    FinancialMetrics,
    InboundReply,
    InvestmentAnalysis,
    InvestmentCriteria,
    MeetingBrief,
    MeetingDetails,
    Money,
    OutreachDraft,
    PropertyListing,
    ReplyIntent,
    SchedulingPreferences,
    ScoutAssessment,
    SourceEvidence,
    WorkflowOutcome,
    WorkflowStage,
)
from propertyscout.state import DealState


def route_after_scout(state: DealState) -> Literal["investment_analyst", "scout_rejected"]:
    if state["scout_assessment"].matches_hard_criteria:
        return "investment_analyst"
    return "scout_rejected"


def route_after_analysis(
    state: DealState,
) -> Literal["analysis_rejected", "request_more_property_data", "shortlist_approval"]:
    recommendation = state["analysis"].recommendation
    if recommendation == AnalysisRecommendation.REJECT:
        return "analysis_rejected"
    if recommendation == AnalysisRecommendation.RESEARCH:
        return "request_more_property_data"
    return "shortlist_approval"


def route_after_approval(
    state: DealState,
) -> Literal["contact_researcher", "complete", "request_more_property_data"]:
    decision = state["approvals"]["shortlist"].decision
    if decision == ApprovalDecision.REVISION_REQUESTED:
        return "request_more_property_data"
    if decision == ApprovalDecision.APPROVED:
        return "contact_researcher"

    return "complete"


def apply_approval_outcome(state: DealState) -> dict:
    decision = state["approvals"]["shortlist"].decision
    if decision == ApprovalDecision.APPROVED:
        outcome = WorkflowOutcome.SHORTLIST_APPROVED
    elif decision == ApprovalDecision.REJECTED:
        outcome = WorkflowOutcome.SHORTLIST_REJECTED
    else:
        outcome = WorkflowOutcome.NEEDS_RESEARCH
    return {"outcome": outcome}


def route_after_contact_research(
    state: DealState,
) -> Literal["contact_not_found", "contact_ready", "contact_resolution"]:
    candidates = state["contact_candidates"]
    if not candidates:
        return "contact_not_found"
    if len(candidates) == 1 and candidates[0].confidence >= 0.8:
        return "contact_ready"
    return "contact_resolution"


def route_after_outreach_approval(state: DealState) -> Literal["complete", "send_outreach"]:
    decision = state["approvals"]["outreach"].decision
    return "send_outreach" if decision == ApprovalDecision.APPROVED else "complete"


def route_after_reply(
    state: DealState,
) -> Literal["book_meeting", "schedule_approval", "end"]:
    if state["reply_intent"] != ReplyIntent.PROPOSED_TIMES:
        return "end"
    if state["requires_schedule_approval"]:
        return "schedule_approval"
    return "book_meeting"


def route_after_schedule_approval(state: DealState) -> Literal["book_meeting", "complete"]:
    decision = state["approvals"]["schedule_exception"].decision
    return "book_meeting" if decision == ApprovalDecision.APPROVED else "complete"


def build_graph(
    reasoner: InvestmentReasoner | None = None,
    contact_service: ContactResearchService | None = None,
    outreach_service: OutreachDraftingService | None = None,
    email_gateway: EmailGateway | None = None,
    reply_interpreter: ReplyInterpreter | None = None,
    calendar_gateway: CalendarGateway | None = None,
    meeting_brief_service: MeetingBriefService | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """Compile the workflow with an injectable durable checkpointer."""

    builder = StateGraph(DealState)
    builder.add_node("initialize_deal", initialize_deal)
    builder.add_node("market_scout", market_scout)
    builder.add_node("investment_analyst", create_investment_analyst(reasoner))
    builder.add_node("contact_researcher", create_contact_researcher(contact_service))
    builder.add_node("contact_resolution", contact_resolution)
    builder.add_node("contact_ready", select_confident_contact)
    builder.add_node("contact_not_found", mark_contact_not_found)
    builder.add_node("outreach_agent", create_outreach_agent(outreach_service))
    builder.add_node("outreach_approval", outreach_approval)
    builder.add_node("send_outreach", create_send_outreach(email_gateway or FakeEmailGateway()))
    builder.add_node("wait_for_reply", wait_for_reply)
    builder.add_node("scheduling_agent", create_scheduling_agent(reply_interpreter))
    builder.add_node("schedule_approval", schedule_approval)
    builder.add_node(
        "book_meeting", create_book_meeting(calendar_gateway or FakeCalendarGateway())
    )
    builder.add_node(
        "meeting_intelligence", create_meeting_intelligence(meeting_brief_service)
    )
    builder.add_node("scout_rejected", mark_scout_rejected)
    builder.add_node("analysis_rejected", mark_analysis_rejected)
    builder.add_node("request_more_property_data", request_more_property_data)
    builder.add_node("shortlist_approval", shortlist_approval)
    builder.add_node("apply_approval_outcome", apply_approval_outcome)
    builder.add_node("complete", complete_workflow)

    builder.add_edge(START, "initialize_deal")
    builder.add_edge("initialize_deal", "market_scout")
    builder.add_conditional_edges("market_scout", route_after_scout)
    builder.add_conditional_edges("investment_analyst", route_after_analysis)
    builder.add_edge("scout_rejected", "complete")
    builder.add_edge("analysis_rejected", "complete")
    builder.add_edge("request_more_property_data", "complete")
    builder.add_edge("shortlist_approval", "apply_approval_outcome")
    builder.add_conditional_edges(
        "apply_approval_outcome",
        route_after_approval,
        {
            "complete": "complete",
            "contact_researcher": "contact_researcher",
            "request_more_property_data": "request_more_property_data",
        },
    )
    builder.add_conditional_edges(
        "contact_researcher",
        route_after_contact_research,
        {
            "contact_not_found": "contact_not_found",
            "contact_ready": "contact_ready",
            "contact_resolution": "contact_resolution",
        },
    )
    builder.add_edge("contact_resolution", "outreach_agent")
    builder.add_edge("contact_ready", "outreach_agent")
    builder.add_edge("contact_not_found", "complete")
    builder.add_edge("outreach_agent", "outreach_approval")
    builder.add_conditional_edges(
        "outreach_approval",
        route_after_outreach_approval,
        {"send_outreach": "send_outreach", "complete": "complete"},
    )
    builder.add_edge("send_outreach", "wait_for_reply")
    builder.add_edge("wait_for_reply", "scheduling_agent")
    builder.add_conditional_edges(
        "scheduling_agent",
        route_after_reply,
        {
            "book_meeting": "book_meeting",
            "schedule_approval": "schedule_approval",
            "end": END,
        },
    )
    builder.add_conditional_edges(
        "schedule_approval",
        route_after_schedule_approval,
        {"book_meeting": "book_meeting", "complete": "complete"},
    )
    builder.add_edge("book_meeting", "meeting_intelligence")
    builder.add_edge("meeting_intelligence", END)
    builder.add_edge("complete", END)

    selected_checkpointer = checkpointer or InMemorySaver(serde=create_state_serializer())
    return builder.compile(checkpointer=selected_checkpointer)


def create_state_serializer() -> JsonPlusSerializer:
    """Create the explicit serializer allowlist shared by all checkpointers."""

    return JsonPlusSerializer(
        allowed_msgpack_modules=[
            AnalysisRecommendation,
            ApprovalDecision,
            ApprovalRecord,
            AuditEvent,
            ContactCandidate,
            ContactType,
            EmailSendReceipt,
            FinancialMetrics,
            InboundReply,
            InvestmentAnalysis,
            InvestmentCriteria,
            Money,
            MeetingBrief,
            MeetingDetails,
            OutreachDraft,
            PropertyListing,
            ReplyIntent,
            SchedulingPreferences,
            ScoutAssessment,
            SourceEvidence,
            WorkflowOutcome,
            WorkflowStage,
        ]
    )
