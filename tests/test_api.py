from fastapi.testclient import TestClient

from propertyscout.api import (
    _pdf_import_listing,
    create_app,
    derive_workflow_status,
    present_workflow,
)
from propertyscout.graph import create_state_serializer
from propertyscout.discovery import DiscoveryService
from propertyscout.fixtures import sample_properties
from propertyscout.market_search import FixtureListingSearchService
from propertyscout.postcode_proximity import PostcodeCoordinateIndex
from propertyscout.schemas import ComparableSelection, DiscoverySelectionContext
from tests.test_discovery import FakeSearchClient, replay_service


def fixture_client(tmp_path) -> TestClient:
    return TestClient(
        create_app(
            tmp_path / "api.sqlite",
            listing_search_service=FixtureListingSearchService(),
            use_llm=False,
        )
    )


def test_api_starts_lists_and_reads_persisted_deals(tmp_path) -> None:
    client = fixture_client(tmp_path)

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/").history[0].status_code == 307
    assert client.get("/deals").json() == []

    response = client.post("/deals", json={"property_key": "reject"})
    assert response.status_code == 201
    created = response.json()
    assert created["state"]["outcome"] == "scout_rejected"
    assert created["interrupts"] == []

    fetched = client.get(f"/deals/{created['thread_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["state"]["property"]["title"] == "Cologne apartment above budget"

    listed = client.get("/deals")
    assert [deal["thread_id"] for deal in listed.json()] == [created["thread_id"]]


def test_deal_api_exposes_analysis_confidence_and_five_score_drivers(tmp_path) -> None:
    client = fixture_client(tmp_path)

    created = client.post("/deals", json={"property_key": "shortlist"}).json()
    analysis = created["state"]["analysis"]

    assert analysis["confidence"]["level"] in {"high", "medium", "low", "unknown"}
    assert analysis["confidence"]["reason"]
    assert [driver["key"] for driver in analysis["score_drivers"]] == [
        "price_vs_market",
        "comparable_evidence",
        "rent_evidence",
        "building_energy_risk",
        "data_completeness",
    ]


def test_pdf_import_listing_extracts_plainly_stated_property_facts() -> None:
    listing = _pdf_import_listing(
        """
        Helle Eigentumswohnung in Essen
        Kaufpreis: 249.000 EUR · 2,5 Zimmer · Wohnfläche 65,5 m²
        Energieklasse E · 45127 Essen
        https://example.com/listing/42
        """,
        "expose.pdf",
    )

    assert listing.asking_price.amount == 249000
    assert listing.room_count == 2.5
    assert listing.living_area_sqm == 65.5
    assert listing.energy_class == "E"
    assert str(listing.listing_url) == "https://example.com/listing/42"


def test_pdf_import_listing_accepts_labelled_purchase_price_without_currency() -> None:
    listing = _pdf_import_listing(
        "Kaufpreis: 460120\n3 Zimmer\nWohnfläche: 82 m²\n45127 Essen",
        "expose.pdf",
    )

    assert listing.asking_price.amount == 460120


def test_pdf_import_listing_prefers_purchase_price_over_price_per_sqm() -> None:
    listing = _pdf_import_listing(
        "Kaufpreis\n460.120 €\n2.014 €/m²\n4 Zimmer\n100 m²\n40210 Düsseldorf",
        "expose.pdf",
    )

    assert listing.asking_price.amount == 460120


def test_api_resumes_current_human_interrupt(tmp_path) -> None:
    client = fixture_client(tmp_path)
    created = client.post("/deals", json={"property_key": "shortlist"}).json()

    assert created["interrupts"][0]["approval_type"] == "shortlist"

    response = client.post(
        f"/deals/{created['thread_id']}/resume",
        json={"response": {"decision": "approved", "decided_by": "api-test"}},
    )

    assert response.status_code == 200
    resumed = response.json()
    assert resumed["state"]["approvals"]["shortlist"]["decided_by"] == "api-test"
    assert resumed["interrupts"][0]["approval_type"] == "contact_resolution"


def test_api_rejects_resume_when_deal_is_not_paused(tmp_path) -> None:
    client = fixture_client(tmp_path)
    created = client.post("/deals", json={"property_key": "reject"}).json()

    response = client.post(
        f"/deals/{created['thread_id']}/resume",
        json={"response": {"decision": "approved"}},
    )

    assert response.status_code == 409


def test_contact_not_found_remains_actionable_in_contact_research() -> None:
    status, pending, diagnostic = derive_workflow_status(
        {"current_stage": "contact_research", "outcome": "contact_not_found"},
        [],
        [],
    )

    assert (status, pending, diagnostic) == ("needs_research", None, None)


def test_workflow_presentation_prioritises_missing_broker_information() -> None:
    presentation = present_workflow(
        {
            "current_stage": "analysis",
            "analysis": {"missing_critical_data": ["annual_rent"]},
        },
        "needs_research",
        None,
        [],
    )

    assert presentation.label == "Needs Broker Info"
    assert presentation.next_action.label == "Ask for More Information"
    assert presentation.next_action.destination == "contact"


def test_workflow_presentation_turns_shortlist_approval_into_contact_action() -> None:
    presentation = present_workflow(
        {"current_stage": "awaiting_shortlist_approval"},
        "waiting_human",
        "shortlist",
        [],
    )

    assert presentation.label == "Needs Your Review"
    assert presentation.next_action.label == "Move to Contact Research"
    assert presentation.next_action.destination == "contact"


def test_api_returns_not_found_for_unknown_thread(tmp_path) -> None:
    client = fixture_client(tmp_path)

    response = client.get("/deals/does-not-exist")

    assert response.status_code == 404


def test_search_endpoint_maps_simple_form_to_agent_criteria(tmp_path) -> None:
    client = fixture_client(tmp_path)

    response = client.post(
        "/searches",
        json={
            "city": "Cologne",
            "minimum_rooms": 3,
            "minimum_size_sqm": 60,
            "maximum_price": 300000,
            "property_type": "apartment",
            "minimum_gross_yield_percent": 6,
            "required_features": ["balcony"],
        },
    )

    assert response.status_code == 201
    search = response.json()
    assert len(search["deals"]) == 3
    first_state = search["deals"][0]["state"]
    assert first_state["criteria"]["minimum_room_count"] == 3
    assert first_state["criteria"]["minimum_living_area_sqm"] == 60
    assert first_state["criteria"]["minimum_gross_yield"] == 0.06
    assert first_state["criteria"]["required_features"] == ["balcony"]


def test_required_feature_is_applied_by_market_scout(tmp_path) -> None:
    client = fixture_client(tmp_path)

    response = client.post(
        "/searches",
        json={
            "city": "Cologne",
            "maximum_price": 500000,
            "property_type": "apartment",
            "required_features": ["parking"],
        },
    )

    assert response.status_code == 201
    deals = response.json()["deals"]
    assert deals[0]["state"]["outcome"] == "scout_rejected"
    assert "Missing required features" in deals[0]["state"]["scout_assessment"]["reasons"][0]
    assert deals[2]["interrupts"][0]["approval_type"] == "shortlist"


def test_postcode_filter_rejects_fixture_outside_target_area(tmp_path) -> None:
    client = fixture_client(tmp_path)

    response = client.post(
        "/searches",
        json={
            "city": "Cologne",
            "postal_code": "99999",
            "maximum_price": 300000,
            "property_type": "apartment",
        },
    )

    assert response.status_code == 201
    assert all(
        deal["state"]["outcome"] == "scout_rejected"
        for deal in response.json()["deals"]
    )
def test_deal_view_reports_waiting_human_with_pending_type(tmp_path) -> None:
    client = fixture_client(tmp_path)

    created = client.post("/deals", json={"property_key": "shortlist"}).json()

    assert created["status"] == "waiting_human"
    assert created["pending_approval_type"] == "shortlist"
    assert created["diagnostic"] is None


def test_terminal_reject_deal_reports_rejected_status(tmp_path) -> None:
    client = fixture_client(tmp_path)

    created = client.post("/deals", json={"property_key": "reject"}).json()

    assert created["status"] == "rejected"
    assert created["pending_approval_type"] is None
    assert created["state"]["outcome"] == "scout_rejected"


def test_research_fixture_reaches_shortlist_approval_with_valuation(tmp_path) -> None:
    client = fixture_client(tmp_path)

    created = client.post("/deals", json={"property_key": "research"}).json()

    assert created["status"] == "waiting_human"
    assert created["pending_approval_type"] == "shortlist"
    valuation = created["state"]["analysis"]["valuation"]
    assert valuation["comp_count"] == 9
    assert valuation["estimated_market_value"]["amount"] == 286_404.0


def test_status_advances_to_next_interrupt_after_approval(tmp_path) -> None:
    client = fixture_client(tmp_path)
    created = client.post("/deals", json={"property_key": "shortlist"}).json()

    resumed = client.post(
        f"/deals/{created['thread_id']}/resume",
        json={"response": {"decision": "approved", "decided_by": "status-test"}},
    ).json()

    assert resumed["status"] == "waiting_human"
    assert resumed["pending_approval_type"] == "contact_resolution"


def test_interrupt_priority_ignores_historical_errors() -> None:
    state = {
        "current_stage": "analysis",
        "errors": [
            {
                "node": "investment_analyst",
                "error_type": "retryable",
                "message": "recovered earlier",
                "retryable": True,
                "occurred_at": "2026-10-21T00:00:00Z",
                "details": {},
            }
        ],
    }

    status, pending, diagnostic = derive_workflow_status(
        state, [{"approval_type": "outreach"}], ["outreach_approval"]
    )

    assert status == "waiting_human"
    assert pending == "outreach"
    assert diagnostic is None


def test_ended_graph_without_outcome_is_failed_with_diagnostic() -> None:
    status, pending, diagnostic = derive_workflow_status(
        {"current_stage": "analysis"}, [], []
    )

    assert status == "failed"
    assert pending is None
    assert diagnostic["reason"] == "graph ended without an outcome"


def test_unknown_outcome_reports_diagnostic() -> None:
    status, pending, diagnostic = derive_workflow_status(
        {"outcome": "something_new", "current_stage": "complete"}, [], []
    )

    assert status == "unknown"
    assert pending is None
    assert diagnostic["outcome"] == "something_new"
    assert diagnostic["reason"] == "outcome is not in the terminal-outcome map"


def _advance_to_reply_interrupt(client: TestClient, thread_id: str) -> dict:
    """Walk a shortlist fixture deal to the inbound-reply interrupt."""

    resumed = client.post(
        f"/deals/{thread_id}/resume",
        json={"response": {"decision": "approved"}},
    ).json()
    with_email = [
        candidate
        for candidate in resumed["interrupts"][0]["candidates"]
        if candidate["email"]
    ]
    contact_id = with_email[0]["contact_id"]
    contact_email = with_email[0]["email"]

    resumed = client.post(
        f"/deals/{thread_id}/resume",
        json={"response": {"contact_id": contact_id}},
    ).json()
    assert resumed["pending_approval_type"] == "outreach"

    resumed = client.post(
        f"/deals/{thread_id}/resume",
        json={"response": {"decision": "approved"}},
    ).json()
    assert resumed["status"] == "waiting_human"
    assert resumed["pending_approval_type"] == "inbound_reply"
    assert resumed["interrupts"][0]["expected_sender_email"] == contact_email
    return resumed


def test_awaiting_followup_is_terminal_and_not_resumable(tmp_path) -> None:
    client = fixture_client(tmp_path)
    created = client.post("/deals", json={"property_key": "shortlist"}).json()
    thread_id = created["thread_id"]

    resumed = _advance_to_reply_interrupt(client, thread_id)
    sender_email = resumed["interrupts"][0]["expected_sender_email"]

    reply = {
        "message_id": "reply-question-1",
        "sender_email": sender_email,
        "received_at": "2026-10-21T10:00:00Z",
        "body": "Could you share more details about the renovation status?",
    }
    resumed = client.post(
        f"/deals/{thread_id}/resume", json={"response": reply}
    ).json()

    assert resumed["status"] == "awaiting_followup"
    assert resumed["state"]["outcome"] == "awaiting_followup"
    assert resumed["interrupts"] == []

    retry = client.post(f"/deals/{thread_id}/resume", json={"response": reply})
    assert retry.status_code == 409


def test_inbound_reply_from_unexpected_sender_is_rejected(tmp_path) -> None:
    client = fixture_client(tmp_path)
    created = client.post("/deals", json={"property_key": "shortlist"}).json()
    thread_id = created["thread_id"]

    resumed = _advance_to_reply_interrupt(client, thread_id)
    sender_email = resumed["interrupts"][0]["expected_sender_email"]

    forged_reply = {
        "message_id": "reply-forged-1",
        "sender_email": f"not-{sender_email}",
        "received_at": "2026-10-21T10:00:00Z",
        "body": "I can call you tomorrow.",
    }
    response = client.post(
        f"/deals/{thread_id}/resume", json={"response": forged_reply}
    )

    assert response.status_code == 422


def test_outreach_resume_accepts_subject_and_body_override(tmp_path) -> None:
    client = fixture_client(tmp_path)
    created = client.post("/deals", json={"property_key": "shortlist"}).json()
    thread_id = created["thread_id"]

    resumed = client.post(
        f"/deals/{thread_id}/resume",
        json={"response": {"decision": "approved"}},
    ).json()
    with_email = [
        candidate
        for candidate in resumed["interrupts"][0]["candidates"]
        if candidate["email"]
    ]
    resumed = client.post(
        f"/deals/{thread_id}/resume",
        json={"response": {"contact_id": with_email[0]["contact_id"]}},
    ).json()

    resumed = client.post(
        f"/deals/{thread_id}/resume",
        json={
            "response": {
                "decision": "approved",
                "subject": "Edited subject",
                "body": "Edited body with the agreed viewing time.",
            }
        },
    ).json()

    assert resumed["state"]["outreach_draft"]["subject"] == "Edited subject"
    assert (
        resumed["state"]["outreach_draft"]["body"]
        == "Edited body with the agreed viewing time."
    )
    assert resumed["state"]["outcome"] == "outreach_sent"
    assert resumed["status"] == "waiting_human"
    assert resumed["pending_approval_type"] == "inbound_reply"


def test_outreach_resume_rejects_empty_edited_subject(tmp_path) -> None:
    client = fixture_client(tmp_path)
    created = client.post("/deals", json={"property_key": "shortlist"}).json()
    thread_id = created["thread_id"]

    resumed = client.post(
        f"/deals/{thread_id}/resume",
        json={"response": {"decision": "approved"}},
    ).json()
    with_email = [
        candidate
        for candidate in resumed["interrupts"][0]["candidates"]
        if candidate["email"]
    ]
    resumed = client.post(
        f"/deals/{thread_id}/resume",
        json={"response": {"contact_id": with_email[0]["contact_id"]}},
    ).json()

    response = client.post(
        f"/deals/{thread_id}/resume",
        json={
            "response": {
                "decision": "approved",
                "subject": "   ",
            }
        },
    )

    assert response.status_code == 422


def test_out_of_policy_reply_routes_to_schedule_exception_then_completes(
    tmp_path,
) -> None:
    client = fixture_client(tmp_path)
    created = client.post("/deals", json={"property_key": "shortlist"}).json()
    thread_id = created["thread_id"]

    resumed = _advance_to_reply_interrupt(client, thread_id)
    sender_email = resumed["interrupts"][0]["expected_sender_email"]

    late_reply = {
        "message_id": "reply-late-1",
        "sender_email": sender_email,
        "received_at": "2026-10-21T19:30:00Z",
        "body": "I propose Saturday 20:00.",
        "proposed_times": ["2026-10-24T20:00:00+02:00"],
    }
    resumed = client.post(
        f"/deals/{thread_id}/resume", json={"response": late_reply}
    ).json()

    assert resumed["status"] == "waiting_human"
    assert resumed["pending_approval_type"] == "schedule_exception"

    resumed = client.post(
        f"/deals/{thread_id}/resume",
        json={"response": {"decision": "approved", "decided_by": "status-test"}},
    ).json()

    assert resumed["status"] == "completed"
    assert resumed["state"]["outcome"] == "brief_ready"
    assert resumed["state"]["current_stage"] == "complete"


def test_schedule_exception_rejection_is_terminal_rejected(tmp_path) -> None:
    client = fixture_client(tmp_path)
    created = client.post("/deals", json={"property_key": "shortlist"}).json()
    thread_id = created["thread_id"]

    resumed = _advance_to_reply_interrupt(client, thread_id)
    sender_email = resumed["interrupts"][0]["expected_sender_email"]

    late_reply = {
        "message_id": "reply-late-2",
        "sender_email": sender_email,
        "received_at": "2026-10-21T19:30:00Z",
        "body": "I propose Saturday 20:00.",
        "proposed_times": ["2026-10-24T20:00:00+02:00"],
    }
    resumed = client.post(
        f"/deals/{thread_id}/resume", json={"response": late_reply}
    ).json()
    assert resumed["pending_approval_type"] == "schedule_exception"

    resumed = client.post(
        f"/deals/{thread_id}/resume",
        json={"response": {"decision": "rejected"}},
    ).json()

    assert resumed["status"] == "rejected"
    assert resumed["state"]["outcome"] == "schedule_rejected"


def test_ui_dashboard_section_is_served(tmp_path) -> None:
    client = fixture_client(tmp_path)

    page = client.get("/app/")
    assert page.status_code == 200
    assert 'id="dashboard"' in page.text
    assert 'id="deal-grid"' in page.text
    assert 'id="deal-tabs"' in page.text
    assert 'id="refresh-deals"' in page.text
    assert 'id="discovery"' in page.text
    assert 'id="discovery-grid"' in page.text
    assert 'id="refresh-discoveries"' in page.text
    assert 'id="clear-discoveries"' in page.text
    assert 'app.js?v=20261029-11' in page.text
    assert 'styles.css?v=20261029-04' in page.text

    script = client.get("/app/app.js")
    assert script.status_code == 200
    assert "loadDeals" in script.text
    assert "loadDiscoveries" in script.text
    assert "criteria: requestFromForm()" in script.text
    assert "Deal Score" in script.text
    assert "View listing" in script.text
    assert "deal-comparable-toggle" in script.text
    assert "Comparable" in script.text
    assert "updateWorkflowStage" in script.text
    assert "focusWorkflowDeal" in script.text
    assert "Scouting properties" in script.text
    assert "clearDiscoveryView" in script.text
    assert "Market valuation" in script.text
    assert "schedule_exception" in script.text

    stylesheet = client.get("/app/styles.css")
    assert stylesheet.status_code == 200
    assert ".approval-panel" in stylesheet.text
    assert ".discovery-card" in stylesheet.text
    assert ".deal-links" in stylesheet.text


def test_dashboard_client_renders_evidence_confidence_and_score_drivers(tmp_path) -> None:
    client = fixture_client(tmp_path)

    script = client.get("/app/app.js")

    assert "Evidence confidence" in script.text
    assert "score_drivers" in script.text


def test_dashboard_client_renders_the_next_best_action(tmp_path) -> None:
    client = fixture_client(tmp_path)

    script = client.get("/app/app.js")

    assert "Next best action" in script.text
    assert "next_best_action" in script.text


def discovery_client(tmp_path) -> TestClient:
    service, _fetch = replay_service(
        search_budget=10, index_fetch_budget=10, detail_fetch_budget=70
    )
    return TestClient(
        create_app(
            tmp_path / "api.sqlite",
            discovery_service=service,
            comp_search_service=FixtureListingSearchService(),
            discovery_dir=tmp_path / "discoveries",
            postcode_index=PostcodeCoordinateIndex.empty(),
            use_llm=False,
        )
    )


def discovery_search_body() -> dict:
    return {
        "city": "Düsseldorf",
        "postal_code": "40597",
        "minimum_rooms": 2,
        "minimum_size_sqm": 40,
        "maximum_price": 300000,
        "property_type": "apartment",
    }


def run_discovery(client: TestClient) -> dict:
    response = client.post("/searches", json=discovery_search_body())
    assert response.status_code == 201, response.text
    return response.json()


def test_discovery_search_returns_inventory_without_auto_deals(tmp_path) -> None:
    client = discovery_client(tmp_path)
    search = run_discovery(client)

    assert search["deals"] == []  # no analysis workflows start automatically
    discovery = search["discovery"]
    assert discovery is not None
    assert discovery["counts"]["complete"] >= 1
    assert discovery["counts"]["index_page"] >= 1
    assert discovery["search_calls"] >= 1
    assert discovery["keenable_credits_used"] == (
        discovery["search_calls"]
        + discovery["index_fetches"]
        + discovery["detail_fetches"]
    )
    assert discovery["search_errors"] == []
    assert discovery["csv_path"].endswith(
        f"discovery_{discovery['search_id']}.csv"
    )
    assert (tmp_path / "discoveries" / f"discovery_{discovery['search_id']}.csv").exists()
    assert client.get("/deals").json() == []


def test_discovery_endpoint_returns_all_records_with_status_and_criteria(tmp_path) -> None:
    client = discovery_client(tmp_path)
    search = run_discovery(client)
    search_id = search["discovery"]["search_id"]

    history = client.get("/discoveries").json()
    assert [item["search_id"] for item in history] == [search_id]

    run = client.get(f"/discoveries/{search_id}").json()
    assert run["search_id"] == search_id
    assert sum(run["counts"].values()) == len(run["records"])
    statuses = {record["status"] for record in run["records"]}
    assert {"complete", "index_page"} <= statuses

    complete = next(r for r in run["records"] if r["status"] == "complete")
    assert complete["price_eur"] is not None
    assert complete["area_m2"] is not None
    assert complete["rooms"] is not None
    assert complete["city"] == "Düsseldorf"
    assert complete["url"].startswith("https://")
    assert complete["matches_criteria"] is True

    index = next(r for r in run["records"] if r["status"] == "index_page")
    assert "index-page" in index["reasons"]
    assert index["matches_criteria"] is False


def test_selected_complete_listing_starts_analysis_with_verified_comps(tmp_path) -> None:
    client = discovery_client(tmp_path)
    search = run_discovery(client)
    search_id = search["discovery"]["search_id"]

    run = client.get(f"/discoveries/{search_id}").json()
    complete = next(r for r in run["records"] if r["status"] == "complete")
    index = next(r for r in run["records"] if r["status"] == "index_page")

    blocked = client.post(
        f"/discoveries/{search_id}/deals", json={"url": index["url"]}
    )
    assert blocked.status_code == 409

    unknown = client.post(
        f"/discoveries/{search_id}/deals", json={"url": "https://unknown.example/x"}
    )
    assert unknown.status_code == 404

    response = client.post(f"/discoveries/{search_id}/deals", json={"url": complete["url"]})
    assert response.status_code == 201, response.text
    deal = response.json()
    assert deal["state"]["property"]["listing_url"] == complete["url"]
    context = deal["state"]["discovery_context"]
    assert context["search_id"] == search_id
    assert context["selected_listing_url"] == complete["url"]
    assert context["selected_source_listing_id"] == deal["state"]["property"]["source_listing_id"]
    assert complete["url"] in {
        listing["listing_url"] for listing in context["validated_listings"]
    }
    comparable_selections = deal["state"]["comparable_selections"]
    assert comparable_selections
    assert all(selection["rank"] >= 1 for selection in comparable_selections)
    assert all(
        selection["listing"]["listing_url"] != complete["url"]
        for selection in comparable_selections
    )
    assert all(selection["selection_reason"] for selection in comparable_selections)
    assert deal["state"]["market_basis"]  # verified comps from the injected service


def test_discovery_inventory_is_the_first_comparable_source(tmp_path) -> None:
    client = discovery_client(tmp_path)
    search = run_discovery(client)
    search_id = search["discovery"]["search_id"]
    run = client.get(f"/discoveries/{search_id}").json()
    complete = next(record for record in run["records"] if record["status"] == "complete")

    response = client.post(f"/discoveries/{search_id}/deals", json={"url": complete["url"]})

    assert response.status_code == 201, response.text
    context = response.json()["state"]["discovery_context"]
    subject_url = context["selected_listing_url"]
    inventory_urls = {listing["listing_url"] for listing in context["validated_listings"]}
    assert subject_url in inventory_urls


def test_discovery_deal_survives_a_failed_comparable_fallback(tmp_path) -> None:
    class FailingComparableSearch:
        def search_comps(self, criteria, minimum_comps, maximum_queries):
            raise RuntimeError("provider unavailable")

    service, _fetch = replay_service(
        search_budget=10, index_fetch_budget=10, detail_fetch_budget=70
    )
    client = TestClient(
        create_app(
            tmp_path / "api.sqlite",
            discovery_service=service,
            comp_search_service=FailingComparableSearch(),
            discovery_dir=tmp_path / "discoveries",
            postcode_index=PostcodeCoordinateIndex.empty(),
            use_llm=False,
        )
    )
    search = run_discovery(client)
    search_id = search["discovery"]["search_id"]
    records = client.get(f"/discoveries/{search_id}").json()["records"]
    complete = next(record for record in records if record["status"] == "complete")

    response = client.post(f"/discoveries/{search_id}/deals", json={"url": complete["url"]})

    assert response.status_code == 201, response.text
    assert response.json()["state"]["comparable_selections"] == []


def test_discovery_context_and_comparables_are_serializer_safe() -> None:
    serializer = create_state_serializer()
    context_type, context_payload = serializer.dumps_typed(
        DiscoverySelectionContext(
            search_id="discovery-test",
            selected_listing_url="https://example.com/listing/subject",
            selected_source_listing_id="subject",
        )
    )
    comparable_type, comparable_payload = serializer.dumps_typed(
        ComparableSelection(
            listing=sample_properties()["shortlist"],
            source="validated_discovery_inventory",
            rank=1,
            selection_reason="same postcode",
        )
    )

    assert serializer.loads_typed((context_type, context_payload)).search_id == "discovery-test"
    assert serializer.loads_typed((comparable_type, comparable_payload)).rank == 1


def test_discovery_history_survives_restart(tmp_path) -> None:
    first = discovery_client(tmp_path)
    search = run_discovery(first)
    search_id = search["discovery"]["search_id"]

    second = discovery_client(tmp_path)  # fresh app, same discovery_dir
    history = second.get("/discoveries").json()
    assert [item["search_id"] for item in history] == [search_id]
    run = second.get(f"/discoveries/{search_id}").json()
    assert run["keenable_credits_used"] == search["discovery"]["keenable_credits_used"]
    assert len(run["records"]) == len(
        (tmp_path / "discoveries" / f"discovery_{search_id}.csv").read_text(
            encoding="utf-8"
        ).splitlines()
    ) - 1


def test_clear_discovery_removes_only_its_inventory(tmp_path) -> None:
    client = discovery_client(tmp_path)
    search = run_discovery(client)
    search_id = search["discovery"]["search_id"]

    response = client.delete(f"/discoveries/{search_id}")

    assert response.status_code == 204
    assert client.get(f"/discoveries/{search_id}").status_code == 404
    assert client.get("/discoveries").json() == []
    assert client.get("/deals").json() == []


def test_discovery_selection_after_restart_accepts_the_retried_criteria(tmp_path) -> None:
    first = discovery_client(tmp_path)
    search = run_discovery(first)
    search_id = search["discovery"]["search_id"]
    second = discovery_client(tmp_path)
    records = second.get(f"/discoveries/{search_id}").json()["records"]
    complete = next(record for record in records if record["status"] == "complete")

    response = second.post(
        f"/discoveries/{search_id}/deals",
        json={"url": complete["url"], "criteria": discovery_search_body()},
    )

    assert response.status_code == 201, response.text


def test_discovery_search_failure_returns_502(tmp_path) -> None:
    service = DiscoveryService(
        search_client=FakeSearchClient(results=[], fail=True),
        fetch_client=None,
        search_budget=3,
    )
    app = create_app(
        tmp_path / "api.sqlite",
        discovery_service=service,
        discovery_dir=tmp_path / "discoveries",
        use_llm=False,
    )
    client = TestClient(app)
    response = client.post("/searches", json=discovery_search_body())
    assert response.status_code == 502
    assert "RuntimeError" in response.json()["detail"]
    assert client.get("/discoveries").json() == []


# __DISCOVERY_TESTS3__





