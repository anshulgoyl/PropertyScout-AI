from uuid import uuid4

from langgraph.types import Command

from propertyscout.bootstrap import initial_state
from datetime import UTC, datetime

from propertyscout.contact_research import (
    ContactResearchService,
    ListingPageContactResearchService,
)
from propertyscout.graph import build_graph
from propertyscout.schemas import ContactCandidate, ContactType, SourceEvidence, WorkflowOutcome


class SingleContactService(ContactResearchService):
    def search(self, property_listing):
        return [
            ContactCandidate(
                contact_id=uuid4(),
                name="Verified Example",
                contact_type=ContactType.BROKER,
                email="verified@example.com",
                confidence=0.95,
                evidence=property_listing.evidence,
            )
        ]


def test_listing_page_contact_service_extracts_only_same_listing_evidence() -> None:
    property_listing = initial_state("shortlist")["property"].model_copy(
        update={
            "listing_url": "https://example.com/listing/123",
            "evidence": [
                SourceEvidence(
                    source_name="listing page",
                    url="https://example.com/listing/123",
                    retrieved_at=datetime.now(UTC),
                    excerpt=(
                        "Ansprechpartner: Anna Beispiel\n"
                        "Maklerbüro: Beispiel Immobilien\n"
                        "Telefon: +49 211 123456\nanna@beispiel-immobilien.de"
                    ),
                ),
                SourceEvidence(
                    source_name="other page",
                    url="https://example.com/other",
                    retrieved_at=datetime.now(UTC),
                    excerpt="Telefon: +49 999 999999 · other@example.com",
                ),
            ],
        }
    )

    contacts = ListingPageContactResearchService().search(property_listing)

    assert len(contacts) == 1
    assert contacts[0].name == "Anna Beispiel"
    assert contacts[0].email == "anna@beispiel-immobilien.de"
    assert contacts[0].phone == "+49 211 123456"
    assert contacts[0].organization == "Beispiel Immobilien"


def test_one_confident_contact_is_selected_automatically() -> None:
    graph = build_graph(contact_service=SingleContactService())
    config = {"configurable": {"thread_id": "single-contact"}}
    paused = graph.invoke(initial_state("shortlist"), config)

    assert "__interrupt__" in paused

    outreach_paused = graph.invoke(Command(resume={"decision": "approved"}), config)

    assert "__interrupt__" in outreach_paused
    assert outreach_paused["outcome"] == WorkflowOutcome.CONTACT_READY
    assert outreach_paused["selected_contact"].email == "verified@example.com"
