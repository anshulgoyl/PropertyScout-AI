from fastapi.testclient import TestClient

from propertyscout.api import create_app
from propertyscout.market_search import FixtureListingSearchService


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
    assert deals[2]["state"]["outcome"] == "needs_research"


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
