from propertyscout.analyst import build_market_basis
from propertyscout.bootstrap import default_criteria
from propertyscout.fixtures import sample_comparables
from propertyscout.graph import create_state_serializer
from propertyscout.market_search import (
    KeenableListingSearchService,
    build_property_query,
    comparable_queries,
    extract_condition,
)
from propertyscout.schemas import PropertyCondition


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


class QueuedKeenableClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.inputs = []

    def invoke(self, tool_input):
        self.inputs.append(tool_input)
        return self.responses.pop(0) if self.responses else []


def test_normalizer_extracts_value_signals() -> None:
    client = FakeKeenableClient(
        [
            {
                "title": "Sanierte Wohnung kaufen in Köln",
                "url": "https://example.com/listing/signals",
                "snippet": (
                    "240.000 € Kaufpreis, 62 m², 3 Zi., 50667 Köln, "
                    "Baujahr 1962, Energieklasse C, vollständig saniert."
                ),
            }
        ]
    )

    listing = KeenableListingSearchService(client).search(default_criteria())[0]

    assert listing.build_year == 1962
    assert listing.energy_class == "C"
    assert listing.condition == PropertyCondition.RENOVATED


def test_condition_priority_prefers_worst_marker() -> None:
    assert (
        extract_condition("Teilsaniert, teilweise renoviert, sonst saniert.")
        == PropertyCondition.PARTIALLY_RENOVATED
    )
    assert (
        extract_condition("Neubau mit neuwertiger Ausstattung.")
        == PropertyCondition.NEW_CONSTRUCTION
    )
    assert (
        extract_condition("Gepflegte Wohnung in zentraler Lage.")
        == PropertyCondition.WELL_MAINTAINED
    )
    assert (
        extract_condition("Renovierungsbedürftige Etage.")
        == PropertyCondition.RENOVATION_REQUIRED
    )
    assert extract_condition("Kein Zustandshinweis im Text.") is None


def test_comparable_queries_put_postcode_first() -> None:
    criteria = default_criteria().model_copy(update={"postal_codes": ["50667"]})

    queries = comparable_queries(criteria)

    assert queries[0] == "Eigentumswohnung kaufen Cologne 50667"
    assert queries[1] == "Eigentumswohnung kaufen Cologne"


def test_search_comps_stops_after_reaching_minimum_comps() -> None:
    client = QueuedKeenableClient(
        [
            [
                {
                    "title": "Wohnung kaufen in Köln",
                    "url": "https://example.com/comp/1",
                    "snippet": "200.000 € Kaufpreis, 50 m², 50667 Köln",
                }
            ]
        ]
    )
    criteria = default_criteria().model_copy(update={"postal_codes": ["50667"]})

    comps = KeenableListingSearchService(client).search_comps(
        criteria, minimum_comps=1, maximum_queries=3
    )

    assert len(comps) == 1
    assert len(client.inputs) == 1


def test_search_comps_deduplicates_and_keeps_querying() -> None:
    client = QueuedKeenableClient(
        [
            [
                {
                    "title": "Wohnung kaufen in Köln",
                    "url": "https://example.com/comp/1",
                    "snippet": "200.000 € Kaufpreis, 50 m², 50667 Köln",
                }
            ],
            [
                {
                    "title": "Wohnung kaufen in Köln",
                    "url": "https://example.com/comp/1",
                    "snippet": "200.000 € Kaufpreis, 50 m², Köln",
                }
            ],
            [],
        ]
    )
    criteria = default_criteria().model_copy(update={"postal_codes": ["50667"]})

    comps = KeenableListingSearchService(client).search_comps(
        criteria, minimum_comps=5, maximum_queries=3
    )

    assert len(comps) == 1
    assert len(client.inputs) == 2


def test_search_comps_skips_failed_query_variants() -> None:
    client = QueuedKeenableClient(
        [
            "provider error",
            [
                {
                    "title": "Wohnung kaufen in Köln",
                    "url": "https://example.com/comp/2",
                    "snippet": "210.000 € Kaufpreis, 60 m², Köln",
                }
            ],
        ]
    )
    criteria = default_criteria().model_copy(update={"postal_codes": ["50667"]})

    comps = KeenableListingSearchService(client).search_comps(
        criteria, minimum_comps=1, maximum_queries=3
    )

    assert len(comps) == 1
    assert len(client.inputs) == 2


def test_build_market_basis_computes_medians_per_condition() -> None:
    basis = build_market_basis(sample_comparables(), default_criteria())

    assert basis is not None
    assert basis.overall_comp_count == 9
    assert basis.overall_eur_per_sqm == 4938.0
    assert basis.city == "Cologne"

    renovated = next(
        bucket
        for bucket in basis.by_condition
        if bucket.condition == PropertyCondition.RENOVATED
    )
    assert renovated.eur_per_sqm == 5100.0
    assert renovated.comp_count == 3
    assert len(renovated.source_urls) == 3


def test_build_market_basis_excludes_subject_urls_and_unusable_comps() -> None:
    comps = sample_comparables()
    excluded_comp = comps[0]
    unusable_comp = comps[1].model_copy(update={"living_area_sqm": None})

    basis = build_market_basis(
        [excluded_comp, unusable_comp, *comps[2:]],
        default_criteria(),
        exclude_urls={str(excluded_comp.listing_url)},
    )

    assert basis is not None
    assert basis.overall_comp_count == 7
    assert basis.overall_eur_per_sqm == 4900.0


def test_build_market_basis_returns_none_without_usable_comps() -> None:
    assert build_market_basis([], default_criteria()) is None
