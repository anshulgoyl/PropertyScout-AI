"""Graph nodes for the first PropertyScout vertical slice."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from langgraph.types import interrupt

from propertyscout.analyst import InvestmentReasoner, RuleBasedReasoner, analyse_property
from propertyscout.contact_research import ContactResearchService, FixtureContactResearchService
from propertyscout.email_gateway import EmailGateway
from propertyscout.meeting_intelligence import (
    MeetingBriefService,
    TemplateMeetingBriefService,
)
from propertyscout.outreach import OutreachDraftingService, TemplateOutreachDraftingService
from propertyscout.scheduling import (
    CalendarGateway,
    ReplyInterpreter,
    RuleBasedReplyInterpreter,
    is_within_availability,
    proposed_meeting,
)
from propertyscout.schemas import (
    ApprovalDecision,
    ApprovalRecord,
    AuditEvent,
    InboundReply,
    ReplyIntent,
    SchedulingPreferences,
    ScoutAssessment,
    WorkflowOutcome,
    WorkflowStage,
)
from propertyscout.state import DealState


def _event(actor: str, action: str, **details: object) -> AuditEvent:
    return AuditEvent(
        event_id=uuid4(),
        occurred_at=datetime.now(UTC),
        actor=actor,
        action=action,
        details=details,
    )


def initialize_deal(state: DealState) -> dict:
    """Validate the minimum state needed to start one property workflow."""

    if "property" not in state:
        raise ValueError("A property is required to start an MVP deal workflow")

    return {
        "current_stage": WorkflowStage.DISCOVERY,
        "audit_events": [_event("orchestrator", "deal_initialized")],
    }


def market_scout(state: DealState) -> dict:
    """Apply transparent hard filters before spending effort on analysis."""

    criteria = state["criteria"]
    property_listing = state["property"]
    reasons: list[str] = []

    normalized_locations = {location.casefold() for location in criteria.locations}
    if property_listing.city.casefold() not in normalized_locations:
        reasons.append(f"Location {property_listing.city!r} is outside the target locations")

    normalized_types = {property_type.casefold() for property_type in criteria.property_types}
    if property_listing.property_type.casefold() not in normalized_types:
        reasons.append(
            f"Property type {property_listing.property_type!r} is outside the target types"
        )

    if criteria.postal_codes and property_listing.postal_code not in criteria.postal_codes:
        reasons.append("Postal code is outside the configured target area")

    budget = criteria.maximum_purchase_price
    if property_listing.asking_price.currency != budget.currency:
        reasons.append("Listing and budget currencies do not match")
    elif property_listing.asking_price.amount > budget.amount:
        reasons.append("Asking price exceeds the maximum purchase price")

    minimum_area = criteria.minimum_living_area_sqm
    if minimum_area is not None:
        if property_listing.living_area_sqm is None:
            reasons.append("Living area is required to evaluate the minimum-area criterion")
        elif property_listing.living_area_sqm < minimum_area:
            reasons.append("Living area is below the configured minimum")

    minimum_rooms = criteria.minimum_room_count
    if minimum_rooms is not None:
        if property_listing.room_count is None:
            reasons.append("Room count is required to evaluate the minimum-room criterion")
        elif property_listing.room_count < minimum_rooms:
            reasons.append("Room count is below the configured minimum")

    listing_features = {feature.casefold() for feature in property_listing.features}
    missing_features = [
        feature
        for feature in criteria.required_features
        if feature.casefold() not in listing_features
    ]
    if missing_features:
        reasons.append(f"Missing required features: {', '.join(missing_features)}")
    excluded_matches = [
        feature
        for feature in criteria.excluded_features
        if feature.casefold() in listing_features
    ]
    if excluded_matches:
        reasons.append(f"Contains excluded features: {', '.join(excluded_matches)}")

    assessment = ScoutAssessment(matches_hard_criteria=not reasons, reasons=reasons)
    return {
        "scout_assessment": assessment,
        "audit_events": [
            _event(
                "market_scout",
                "property_screened",
                matches_hard_criteria=assessment.matches_hard_criteria,
                reasons=assessment.reasons,
            )
        ],
    }


def create_investment_analyst(reasoner: InvestmentReasoner | None = None):
    """Create a graph node with an injectable qualitative reasoner."""

    selected_reasoner = reasoner or RuleBasedReasoner()

    def investment_analyst(state: DealState) -> dict:
        analysis = analyse_property(state["property"], state["criteria"], selected_reasoner)
        return {
            "analysis": analysis,
            "current_stage": WorkflowStage.ANALYSIS,
            "audit_events": [
                _event(
                    "investment_analyst",
                    "property_analysed",
                    recommendation=analysis.recommendation.value,
                    score=analysis.score,
                )
            ],
        }

    return investment_analyst


def create_contact_researcher(service: ContactResearchService | None = None):
    """Create a contact-research node with an injectable data service."""

    selected_service = service or FixtureContactResearchService()

    def contact_researcher(state: DealState) -> dict:
        candidates = selected_service.search(state["property"])
        return {
            "contact_candidates": candidates,
            "current_stage": WorkflowStage.CONTACT_RESEARCH,
            "audit_events": [
                _event(
                    "contact_researcher",
                    "contacts_researched",
                    candidate_count=len(candidates),
                )
            ],
        }

    return contact_researcher


def select_confident_contact(state: DealState) -> dict:
    candidate = state["contact_candidates"][0]
    return {
        "selected_contact": candidate,
        "outcome": WorkflowOutcome.CONTACT_READY,
        "audit_events": [
            _event(
                "contact_researcher",
                "contact_selected_automatically",
                contact_id=str(candidate.contact_id),
            )
        ],
    }


def mark_contact_not_found(state: DealState) -> dict:
    return {
        "outcome": WorkflowOutcome.CONTACT_NOT_FOUND,
        "audit_events": [_event("contact_researcher", "contact_not_found")],
    }


def contact_resolution(state: DealState) -> dict:
    """Pause when several plausible contacts require a human choice."""

    response = interrupt(
        {
            "approval_type": "contact_resolution",
            "property_id": str(state["property"].property_id),
            "candidates": [
                candidate.model_dump(mode="json")
                for candidate in state["contact_candidates"]
            ],
        }
    )
    if not isinstance(response, dict):
        raise TypeError("Contact-resolution response must be a dictionary")

    selected_id = str(response.get("contact_id", ""))
    selected = next(
        (
            candidate
            for candidate in state["contact_candidates"]
            if str(candidate.contact_id) == selected_id
        ),
        None,
    )
    if selected is None:
        raise ValueError("Selected contact_id is not one of the presented candidates")

    return {
        "selected_contact": selected,
        "outcome": WorkflowOutcome.CONTACT_READY,
        "audit_events": [
            _event(
                "human",
                "contact_resolved",
                contact_id=str(selected.contact_id),
            )
        ],
    }


def create_outreach_agent(service: OutreachDraftingService | None = None):
    """Create a draft-only outreach node with no sending capability."""

    selected_service = service or TemplateOutreachDraftingService()

    def outreach_agent(state: DealState) -> dict:
        contact = state["selected_contact"]
        draft = selected_service.draft(state["property"], contact, state["analysis"])
        if draft.recipient_contact_id != contact.contact_id:
            raise ValueError("Draft recipient does not match the selected contact")
        if draft.recipient_email != contact.email:
            raise ValueError("Draft email does not match the selected contact")

        return {
            "outreach_draft": draft,
            "current_stage": WorkflowStage.AWAITING_OUTREACH_APPROVAL,
            "audit_events": [
                _event(
                    "outreach_agent",
                    "outreach_drafted",
                    recipient_contact_id=str(contact.contact_id),
                )
            ],
        }

    return outreach_agent


def outreach_approval(state: DealState) -> dict:
    """Pause for approval of the exact recipient, subject, and body."""

    draft = state["outreach_draft"]
    response = interrupt(
        {
            "approval_type": "outreach",
            "draft": draft.model_dump(mode="json"),
            "allowed_decisions": [
                ApprovalDecision.APPROVED.value,
                ApprovalDecision.REJECTED.value,
                ApprovalDecision.REVISION_REQUESTED.value,
            ],
        }
    )
    if not isinstance(response, dict):
        raise TypeError("Outreach-approval response must be a dictionary")

    decision = ApprovalDecision(response.get("decision"))
    final_draft = draft
    if decision == ApprovalDecision.APPROVED:
        subject = response.get("subject", draft.subject)
        body = response.get("body", draft.body)
        final_draft = draft.model_copy(update={"subject": subject, "body": body})
        if not final_draft.subject.strip() or not final_draft.body.strip():
            raise ValueError("Approved outreach subject and body cannot be empty")

    approval = ApprovalRecord(
        approval_type="outreach",
        decision=decision,
        decided_by=response.get("decided_by", "investor"),
        decided_at=datetime.now(UTC),
        feedback=response.get("feedback"),
    )
    if decision == ApprovalDecision.APPROVED:
        outcome = WorkflowOutcome.OUTREACH_APPROVED
    elif decision == ApprovalDecision.REJECTED:
        outcome = WorkflowOutcome.OUTREACH_REJECTED
    else:
        outcome = WorkflowOutcome.OUTREACH_REVISION_REQUESTED

    return {
        "outreach_draft": final_draft,
        "approvals": {**state.get("approvals", {}), "outreach": approval},
        "outcome": outcome,
        "audit_events": [
            _event("human", "outreach_decided", decision=decision.value)
        ],
    }


def create_send_outreach(gateway: EmailGateway):
    """Create an idempotent external-action node for approved outreach."""

    def send_outreach(state: DealState) -> dict:
        approval = state.get("approvals", {}).get("outreach")
        if approval is None or approval.decision != ApprovalDecision.APPROVED:
            raise ValueError("Outreach must be approved before it can be sent")

        draft = state["outreach_draft"]
        contact = state["selected_contact"]
        if draft.recipient_contact_id != contact.contact_id or draft.recipient_email != contact.email:
            raise ValueError("Approved draft recipient no longer matches the selected contact")

        key_material = "\n".join(
            [
                str(state["run_id"]),
                str(draft.recipient_contact_id),
                draft.recipient_email,
                draft.subject,
                draft.body,
            ]
        )
        idempotency_key = hashlib.sha256(key_material.encode()).hexdigest()
        receipt = gateway.send(draft, idempotency_key)

        return {
            "email_send_receipt": receipt,
            "idempotency_keys": {
                **state.get("idempotency_keys", {}),
                "initial_outreach": idempotency_key,
            },
            "current_stage": WorkflowStage.AWAITING_REPLY,
            "outcome": WorkflowOutcome.OUTREACH_SENT,
            "audit_events": [
                _event(
                    "outreach_sender",
                    "outreach_sent",
                    provider_message_id=receipt.provider_message_id,
                    idempotency_key=idempotency_key,
                )
            ],
        }

    return send_outreach


def wait_for_reply(state: DealState) -> dict:
    """Pause the durable workflow until a reply arrives from the selected contact."""

    contact = state["selected_contact"]
    response = interrupt(
        {
            "input_type": "inbound_reply",
            "expected_sender_email": contact.email,
            "in_reply_to": state["email_send_receipt"].provider_message_id,
        }
    )
    if not isinstance(response, dict):
        raise TypeError("Inbound reply must be a dictionary")

    reply = InboundReply.model_validate(response)
    if contact.email is None or reply.sender_email.casefold() != contact.email.casefold():
        raise ValueError("Inbound reply sender does not match the selected contact")

    return {
        "inbound_reply": reply,
        "current_stage": WorkflowStage.SCHEDULING,
        "audit_events": [
            _event(
                "reply_listener",
                "broker_reply_received",
                message_id=reply.message_id,
                sender_email=reply.sender_email,
            )
        ],
    }


def create_scheduling_agent(interpreter: ReplyInterpreter | None = None):
    """Create a scheduling node with injectable reply interpretation."""

    selected_interpreter = interpreter or RuleBasedReplyInterpreter()

    def scheduling_agent(state: DealState) -> dict:
        reply = state["inbound_reply"]
        intent = selected_interpreter.classify(reply)
        result: dict = {
            "reply_intent": intent,
            "audit_events": [
                _event("scheduling_agent", "reply_classified", intent=intent.value)
            ],
        }

        if intent == ReplyIntent.DECLINED:
            result.update(
                current_stage=WorkflowStage.COMPLETE,
                outcome=WorkflowOutcome.BROKER_DECLINED,
            )
        elif intent in (ReplyIntent.QUESTION, ReplyIntent.OTHER):
            result.update(
                current_stage=WorkflowStage.AWAITING_REPLY,
                outcome=WorkflowOutcome.AWAITING_FOLLOWUP,
            )
        else:
            preferences = state.get("scheduling_preferences", SchedulingPreferences())
            contact_email = state["selected_contact"].email
            if contact_email is None:
                raise ValueError("Selected contact must have an email for scheduling")
            meeting = proposed_meeting(reply, preferences, contact_email)
            result.update(
                meeting=meeting,
                requires_schedule_approval=not is_within_availability(
                    meeting, preferences
                ),
            )
        return result

    return scheduling_agent


def schedule_approval(state: DealState) -> dict:
    """Pause for approval when a proposed time is outside configured availability."""

    response = interrupt(
        {
            "approval_type": "schedule_exception",
            "reason": "Proposed time is outside configured availability",
            "meeting": state["meeting"].model_dump(mode="json"),
            "allowed_decisions": [
                ApprovalDecision.APPROVED.value,
                ApprovalDecision.REJECTED.value,
            ],
        }
    )
    if not isinstance(response, dict):
        raise TypeError("Schedule-approval response must be a dictionary")

    decision = ApprovalDecision(response.get("decision"))
    if decision not in (ApprovalDecision.APPROVED, ApprovalDecision.REJECTED):
        raise ValueError("Schedule exception must be approved or rejected")
    approval = ApprovalRecord(
        approval_type="schedule_exception",
        decision=decision,
        decided_by=response.get("decided_by", "investor"),
        decided_at=datetime.now(UTC),
        feedback=response.get("feedback"),
    )
    result = {
        "approvals": {**state.get("approvals", {}), "schedule_exception": approval},
        "audit_events": [
            _event("human", "schedule_exception_decided", decision=decision.value)
        ],
    }
    if decision == ApprovalDecision.REJECTED:
        result["outcome"] = WorkflowOutcome.SCHEDULE_REJECTED
    return result


def create_book_meeting(gateway: CalendarGateway):
    """Create an idempotent calendar-booking node."""

    def book_meeting(state: DealState) -> dict:
        if state.get("requires_schedule_approval", False):
            approval = state.get("approvals", {}).get("schedule_exception")
            if approval is None or approval.decision != ApprovalDecision.APPROVED:
                raise ValueError("An out-of-policy meeting must be approved before booking")

        meeting = state["meeting"]
        key_material = "\n".join(
            [
                str(state["run_id"]),
                meeting.starts_at.isoformat(),
                meeting.ends_at.isoformat(),
                *sorted(meeting.attendee_emails),
            ]
        )
        idempotency_key = hashlib.sha256(key_material.encode()).hexdigest()
        booked = gateway.book(meeting, idempotency_key)
        return {
            "meeting": booked,
            "idempotency_keys": {
                **state.get("idempotency_keys", {}),
                "broker_meeting": idempotency_key,
            },
            "current_stage": WorkflowStage.MEETING_PREPARATION,
            "outcome": WorkflowOutcome.MEETING_SCHEDULED,
            "audit_events": [
                _event(
                    "scheduling_agent",
                    "meeting_booked",
                    external_event_id=booked.external_event_id,
                    idempotency_key=idempotency_key,
                )
            ],
        }

    return book_meeting


def create_meeting_intelligence(service: MeetingBriefService | None = None):
    """Create the final specialist node that prepares a structured call brief."""

    selected_service = service or TemplateMeetingBriefService()

    def meeting_intelligence(state: DealState) -> dict:
        meeting = state["meeting"]
        if meeting.external_event_id is None:
            raise ValueError("A confirmed meeting is required before preparing the brief")
        brief = selected_service.prepare(
            state["property"],
            state["analysis"],
            meeting,
            state["inbound_reply"],
            state.get("briefing_priorities", []),
        )
        return {
            "meeting_brief": brief,
            "current_stage": WorkflowStage.COMPLETE,
            "outcome": WorkflowOutcome.BRIEF_READY,
            "audit_events": [
                _event(
                    "meeting_intelligence",
                    "meeting_brief_prepared",
                    question_count=len(brief.open_questions),
                    risk_count=len(brief.risks),
                )
            ],
        }

    return meeting_intelligence


def mark_scout_rejected(state: DealState) -> dict:
    return {
        "outcome": WorkflowOutcome.SCOUT_REJECTED,
        "audit_events": [_event("orchestrator", "property_rejected_by_scout")],
    }


def mark_analysis_rejected(state: DealState) -> dict:
    return {
        "outcome": WorkflowOutcome.ANALYSIS_REJECTED,
        "audit_events": [_event("orchestrator", "property_rejected_by_analysis")],
    }


def request_more_property_data(state: DealState) -> dict:
    return {
        "outcome": WorkflowOutcome.NEEDS_RESEARCH,
        "audit_events": [
            _event(
                "orchestrator",
                "property_research_requested",
                missing_fields=state["analysis"].missing_critical_data,
            )
        ],
    }


def shortlist_approval(state: DealState) -> dict:
    """Pause until a human decides what to do with this candidate."""

    response = interrupt(
        {
            "approval_type": "shortlist",
            "property": state["property"].model_dump(mode="json"),
            "analysis": state["analysis"].model_dump(mode="json"),
            "allowed_decisions": [
                ApprovalDecision.APPROVED.value,
                ApprovalDecision.REJECTED.value,
                ApprovalDecision.REVISION_REQUESTED.value,
            ],
        }
    )

    if not isinstance(response, dict):
        raise TypeError("Approval response must be a dictionary")

    decision = ApprovalDecision(response.get("decision"))
    approval = ApprovalRecord(
        approval_type="shortlist",
        decision=decision,
        decided_by=response.get("decided_by", "investor"),
        decided_at=datetime.now(UTC),
        feedback=response.get("feedback"),
    )
    return {
        "approvals": {**state.get("approvals", {}), "shortlist": approval},
        "audit_events": [
            _event("human", "shortlist_decided", decision=decision.value)
        ],
    }


def complete_workflow(state: DealState) -> dict:
    return {
        "current_stage": WorkflowStage.COMPLETE,
        "audit_events": [
            _event(
                "orchestrator",
                "workflow_completed",
                outcome=state.get("outcome", "unknown"),
            )
        ],
    }
