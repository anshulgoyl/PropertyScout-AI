"""Pluggable contact research services for approved properties."""

from __future__ import annotations

import re
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from propertyscout.schemas import ContactCandidate, ContactType, PropertyListing


class ContactResearchService(Protocol):
    def search(self, property_listing: PropertyListing) -> list[ContactCandidate]: ...


_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_LABELLED_PHONE = re.compile(
    r"(?:telefon(?:nummer)?|tel\.?|mobil(?:telefon)?|phone)\s*[:\-]?\s*"
    r"(?P<value>(?:\+49|0)[\d\s()/.\-]{6,})",
    re.IGNORECASE,
)
_CONTACT_NAME = re.compile(
    r"(?:ihr\s+)?(?:ansprechpartner(?:in)?|kontakt(?:person)?|makler(?:in)?|"
    r"verkäufer(?:in)?)\s*[:\-]\s*(?P<value>[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'\-]+(?:\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'\-]+){0,3})",
    re.IGNORECASE,
)
_ORGANIZATION = re.compile(
    r"(?:anbieter|firma|immobilienbüro|maklerbüro)\s*[:\-]\s*(?P<value>[^\n]{2,100})",
    re.IGNORECASE,
)
_BROKER_LANGUAGE = re.compile(
    r"\b(makler|immobilienmakler|immobilienbüro|immobilienagentur|agentur|"
    r"real\s+estate|hausverwaltung|provision\s+für\s+käufer|"
    r"u-?w-?i\s+ulrike\s+wollscheid\s+immobilien)\b",
    re.IGNORECASE,
)
_PRIVATE_LANGUAGE = re.compile(
    r"\b(von\s+privat|privatanbieter|privatverkauf|private[rs]?\s+anbieter|"
    r"direkt\s+vom\s+eigentümer|ohne\s+makler)\b",
    re.IGNORECASE,
)


def _canonical_url(value: object) -> str:
    """Compare listing evidence without tracking parameters or fragments."""

    text = str(value or "").strip()
    parts = urlsplit(text)
    if not parts.scheme or not parts.netloc:
        return text.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


class ListingPageContactResearchService:
    """Extract public contact details saved from the selected listing page only."""

    def search(self, property_listing: PropertyListing) -> list[ContactCandidate]:
        listing_url = _canonical_url(property_listing.listing_url)
        evidence = [
            item
            for item in property_listing.evidence
            if _canonical_url(item.url) == listing_url and item.excerpt
        ]
        text = "\n".join(str(item.excerpt) for item in evidence)
        if not text:
            return self._fixture_fallback(property_listing)

        email_match = _EMAIL.search(text)
        phone_match = _LABELLED_PHONE.search(text)
        name_match = _CONTACT_NAME.search(text)
        organization_match = _ORGANIZATION.search(text)
        email = email_match.group(0) if email_match else None
        phone = re.sub(r"\s+", " ", phone_match.group("value")).strip(" .;,") if phone_match else None
        name = name_match.group("value").strip() if name_match else None
        organization = organization_match.group("value").strip(" .;,") if organization_match else None
        if not email and not phone:
            return self._fixture_fallback(property_listing)

        confidence = 0.55 + (0.2 if name else 0) + (0.15 if email else 0) + (0.1 if phone else 0)
        contact_key = email or phone or name or organization or "listing-contact"
        return [
            ContactCandidate(
                contact_id=uuid5(NAMESPACE_URL, f"{listing_url}#contact:{contact_key}"),
                name=name or organization or "Listing contact",
                organization=organization,
                contact_type=(
                    ContactType.BROKER
                    if _BROKER_LANGUAGE.search(text)
                    else ContactType.SELLER
                    if _PRIVATE_LANGUAGE.search(text)
                    else ContactType.UNKNOWN
                ),
                email=email,
                phone=phone,
                confidence=min(confidence, 0.98),
                evidence=evidence,
            )
        ]

    @staticmethod
    def _fixture_fallback(property_listing: PropertyListing) -> list[ContactCandidate]:
        """Keep the offline sample workflow available; never used for live listings."""

        if property_listing.source_listing_id != "fixture-shortlist":
            return []
        return FixtureContactResearchService().search(property_listing)


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

