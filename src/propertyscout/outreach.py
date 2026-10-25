"""Safe, pluggable outreach drafting services."""

from __future__ import annotations

from typing import Protocol

from propertyscout.schemas import (
    ContactCandidate,
    InvestmentAnalysis,
    OutreachDraft,
    PropertyListing,
)


class OutreachDraftingService(Protocol):
    def draft(
        self,
        property_listing: PropertyListing,
        contact: ContactCandidate,
        analysis: InvestmentAnalysis,
    ) -> OutreachDraft: ...


class TemplateOutreachDraftingService:
    """Deterministic baseline before adding model-generated copy."""

    def draft(
        self,
        property_listing: PropertyListing,
        contact: ContactCandidate,
        analysis: InvestmentAnalysis,
    ) -> OutreachDraft:
        if not contact.email:
            raise ValueError("The selected contact has no email address")

        requested_information = [
            "current rent schedule and tenancy status",
            "the latest service-charge statement, non-recoverable costs and reserve position",
            "recent renovation, maintenance and energy-efficiency records",
            "available floor plans, energy certificate and owners' association documents",
        ]
        first_name = contact.name.split()[0]
        subject = f"Interested in {property_listing.title} in {property_listing.city}"
        body = (
            f"Hello {first_name},\n\n"
            f"I came across '{property_listing.title}' in {property_listing.city} "
            "and it genuinely stood out to me. I would love to understand the property "
            "a little better and explore whether it could be a good fit. Before arranging "
            "a viewing, could you please share:\n\n"
            + "\n".join(f"- {item}" for item in requested_information)
            + "\n\nI am especially keen to understand the condition of the building and any "
            "upcoming costs, so I can assess the opportunity responsibly. If convenient, "
            "I would be delighted to arrange a short call or viewing at a time that suits you.\n\n"
            "Thank you very much, and I look forward to hearing from you.\n\nBest regards"
        )
        return OutreachDraft(
            recipient_contact_id=contact.contact_id,
            recipient_email=contact.email,
            subject=subject,
            body=body,
            requested_information=requested_information,
        )

