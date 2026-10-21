from uuid import uuid4

from langgraph.types import Command

from propertyscout.bootstrap import initial_state
from propertyscout.contact_research import ContactResearchService
from propertyscout.graph import build_graph
from propertyscout.schemas import ContactCandidate, ContactType, WorkflowOutcome


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


def test_one_confident_contact_is_selected_automatically() -> None:
    graph = build_graph(contact_service=SingleContactService())
    config = {"configurable": {"thread_id": "single-contact"}}
    paused = graph.invoke(initial_state("shortlist"), config)

    assert "__interrupt__" in paused

    outreach_paused = graph.invoke(Command(resume={"decision": "approved"}), config)

    assert "__interrupt__" in outreach_paused
    assert outreach_paused["outcome"] == WorkflowOutcome.CONTACT_READY
    assert outreach_paused["selected_contact"].email == "verified@example.com"
