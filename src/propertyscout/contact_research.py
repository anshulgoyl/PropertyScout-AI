"""Pluggable contact research services for approved properties."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from propertyscout.schemas import ContactCandidate, ContactType, PropertyListing


class ContactResearchService(Protocol):
    def search(self, property_listing: PropertyListing) -> list[ContactCandidate]: ...


class FixtureContactResearchService:
    """Deterministic, non-personal sample contacts for tests and demonstrations."""

    def search(self, property_listing: PropertyListing) -> list[ContactCandidate]:
        if property_listing.source_listing_id != "fixture-shortlist":
            return []

        return [
            ContactCandidate(
                contact_id=UUID("10000000-0000-0000-0000-000000000001"),
                name="Alex Example",
                organization="Example Immobilien GmbH",
                contact_type=ContactType.BROKER,
                email="alex@example.com",
                confidence=0.86,
                evidence=property_listing.evidence,
            ),
            ContactCandidate(
                contact_id=UUID("10000000-0000-0000-0000-000000000002"),
                name="Sam Example",
                organization="Example Immobilien GmbH",
                contact_type=ContactType.AGENCY,
                email="office@example.com",
                confidence=0.72,
                evidence=property_listing.evidence,
            ),
        ]

