from uuid import uuid4

import pytest

from propertyscout.bootstrap import default_criteria
from propertyscout.fixtures import sample_properties
from propertyscout.nodes import create_outreach_agent
from propertyscout.outreach import OutreachDraftingService, TemplateOutreachDraftingService
from propertyscout.schemas import (
    AnalysisRecommendation,
    ContactCandidate,
    ContactType,
    FinancialMetrics,
    InvestmentAnalysis,
    Money,
    OutreachDraft,
    WorkflowStage,
)


def outreach_state():
    property_listing = sample_properties()["shortlist"]
    contact = ContactCandidate(
        contact_id=uuid4(),
        name="Alex Example",
        contact_type=ContactType.BROKER,
        email="alex@example.com",
        confidence=0.9,
    )
    analysis = InvestmentAnalysis(
        metrics=FinancialMetrics(
            purchase_price=Money(amount=210_000, currency="EUR"),
            gross_yield=0.072,
        ),
        recommendation=AnalysisRecommendation.SHORTLIST,
        thesis="Fixture analysis.",
    )
    return {
        "criteria": default_criteria(),
        "property": property_listing,
        "selected_contact": contact,
        "analysis": analysis,
        "current_stage": WorkflowStage.CONTACT_RESEARCH,
        "audit_events": [],
        "errors": [],
    }


def test_template_draft_is_personalized_and_does_not_send() -> None:
    state = outreach_state()
    update = create_outreach_agent(TemplateOutreachDraftingService())(state)
    draft = update["outreach_draft"]

    assert draft.recipient_email == "alex@example.com"
    assert "Hello Alex" in draft.body
    assert state["property"].title in draft.subject
    assert update["current_stage"] == WorkflowStage.AWAITING_OUTREACH_APPROVAL


class WrongRecipientService(OutreachDraftingService):
    def draft(self, property_listing, contact, analysis):
        return OutreachDraft(
            recipient_contact_id=uuid4(),
            recipient_email="wrong@example.com",
            subject="Wrong recipient",
            body="This must be rejected before approval.",
        )


def test_outreach_agent_rejects_recipient_mismatch() -> None:
    with pytest.raises(ValueError, match="recipient"):
        create_outreach_agent(WrongRecipientService())(outreach_state())
