"""Shared LangGraph state for one property acquisition workflow."""

from __future__ import annotations

from operator import add
from typing import Annotated, NotRequired, TypedDict
from uuid import UUID

from propertyscout.schemas import (
    ApprovalRecord,
    AuditEvent,
    ContactCandidate,
    EmailSendReceipt,
    InboundReply,
    InvestmentAnalysis,
    InvestmentCriteria,
    MeetingBrief,
    MeetingDetails,
    OutreachDraft,
    PropertyListing,
    ReplyIntent,
    SchedulingPreferences,
    ScoutAssessment,
    WorkflowError,
    WorkflowOutcome,
    WorkflowStage,
)


class DealState(TypedDict):
    """State passed between graph nodes.

    Required fields identify the run and current workflow position. Optional fields
    appear as the deal advances. Event and error lists use reducers so parallel or
    repeated nodes append records instead of overwriting history.
    """

    run_id: UUID
    criteria: InvestmentCriteria
    current_stage: WorkflowStage

    candidate_properties: NotRequired[list[PropertyListing]]
    property: NotRequired[PropertyListing]
    scout_assessment: NotRequired[ScoutAssessment]
    analysis: NotRequired[InvestmentAnalysis]
    outcome: NotRequired[WorkflowOutcome]

    contact_candidates: NotRequired[list[ContactCandidate]]
    selected_contact: NotRequired[ContactCandidate]
    outreach_draft: NotRequired[OutreachDraft]
    email_send_receipt: NotRequired[EmailSendReceipt]
    meeting: NotRequired[MeetingDetails]
    meeting_brief: NotRequired[MeetingBrief]
    briefing_priorities: NotRequired[list[str]]

    approvals: NotRequired[dict[str, ApprovalRecord]]
    retry_counts: NotRequired[dict[str, int]]
    idempotency_keys: NotRequired[dict[str, str]]
    inbound_reply: NotRequired[InboundReply]
    reply_intent: NotRequired[ReplyIntent]
    scheduling_preferences: NotRequired[SchedulingPreferences]
    requires_schedule_approval: NotRequired[bool]

    audit_events: Annotated[list[AuditEvent], add]
    errors: Annotated[list[WorkflowError], add]
