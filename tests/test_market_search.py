from propertyscout.bootstrap import default_criteria
from propertyscout.graph import create_state_serializer
from propertyscout.market_search import (
    KeenableListingSearchService,
    build_property_query,
)


class FakeKeenableClient:
    def __init__(self, results):
        self.results = results
        self.inputs = []

    def invoke(self, tool_input):
        self.inputs.append(tool_input)
        return self.results


def test_keenable_search_normalizes_grounded_purchase_listing() -> None:
    client = FakeKeenableClient(
        [
            {
                "title": "Wohnung kaufen in Köln-Altstadt",
                "url": "https://example.com/listing/123",
                "snippet": (
                    "210.000,00 € 3 Zi. 62 m² Kaufpreis 50667 Köln "
                    "Immobilientyp: Wohnung mit Balkon und Aufzug."
                ),
            }
        ]
    )

    listings = KeenableListingSearchService(client).search(default_criteria())

    assert len(listings) == 1
    listing = listings[0]
    assert listing.asking_price.amount == 210_000
    assert listing.room_count == 3
    assert listing.living_area_sqm == 62
    assert listing.postal_code == "50667"
    assert listing.missing_fields == ["annual_rent"]
    assert str(listing.evidence[0].url) == "https://example.com/listing/123"
    serializer = create_state_serializer()
    type_name, payload = serializer.dumps_typed(listing)
    assert serializer.loads_typed((type_name, payload)) == listing


def test_keenable_search_drops_rentals_and_wrong_city_results() -> None:
    client = FakeKeenableClient(
        [
            {
                "title": "Wohnung mieten in Köln",
                "url": "https://example.com/rental",
                "snippet": "1.400 € Kaltmiete, 3 Zimmer, 70 m², 50667 Köln",
            },
            {
                "title": "Wohnung kaufen in Bonn",
                "url": "https://example.com/bonn",
                "snippet": "250.000 € Kaufpreis, 3 Zimmer, 70 m², 53111 Bonn",
            },
        ]
    )

    assert KeenableListingSearchService(client).search(default_criteria()) == []


def test_keenable_search_accepts_english_currency_and_purchase_labels() -> None:
    client = FakeKeenableClient(
        [
            {
                "title": "Buy an apartment in Cologne",
                "url": "https://example.com/listing/english",
                "snippet": "Purchase price €235,000 · 2 rooms · 62 m2 · 50735 Cologne",
            }
        ]
    )

    listing = KeenableListingSearchService(client).search(default_criteria())[0]

    assert listing.asking_price.amount == 235_000
    assert listing.room_count == 2


def test_property_query_contains_critical_search_constraints() -> None:
    query = build_property_query(default_criteria())

    assert "Eigentumswohnung" in query
    assert "cologne" in query.casefold() and "köln" in query.casefold()
    assert "300000 EUR" in query
    assert "50 m²" in query
