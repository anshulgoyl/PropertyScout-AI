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
            "annual service charges and non-recoverable costs",
            "recent renovation and maintenance records",
        ]
        first_name = contact.name.split()[0]
        subject = f"Inquiry about {property_listing.title} in {property_listing.city}"
        body = (
            f"Hello {first_name},\n\n"
            f"I am reviewing the property '{property_listing.title}' in "
            f"{property_listing.city} and would like to understand it in more detail. "
            "Could you please share the following information?\n\n"
            + "\n".join(f"- {item}" for item in requested_information)
            + "\n\nI would also be happy to arrange a short call.\n\nBest regards"
        )
        return OutreachDraft(
            recipient_contact_id=contact.contact_id,
            recipient_email=contact.email,
            subject=subject,
            body=body,
            requested_information=requested_information,
        )

