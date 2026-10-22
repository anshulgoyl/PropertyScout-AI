import json
from pathlib import Path

from propertyscout.analyst import build_market_basis
from propertyscout.bootstrap import default_criteria
from propertyscout.fixtures import sample_comparables
from propertyscout.graph import create_state_serializer
from propertyscout.market_search import (
    KeenableListingSearchService,
    build_property_query,
    city_aliases,
    comparable_queries,
    eur_price_values,
    extract_condition,
    normalize_search_result,
)
from propertyscout.nodes import market_scout
from propertyscout.schemas import InvestmentCriteria, Money, PropertyCondition


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


def duesseldorf_criteria() -> InvestmentCriteria:
    return InvestmentCriteria(
        locations=["Düsseldorf"],
        maximum_purchase_price=Money(amount=551_001, currency="EUR"),
        property_types=["apartment"],
        minimum_living_area_sqm=50,
        minimum_room_count=2,
        strategy="buy_to_let",
    )


FIXTURES = Path(__file__).parent / "fixtures"


def captured_results(filename: str) -> list[dict]:
    payload = json.loads((FIXTURES / filename).read_text(encoding="utf-8"))
    return payload["raw"]


def test_city_aliases_include_umlaut_transliteration_and_ascii_forms() -> None:
    assert city_aliases("Düsseldorf") == ("düsseldorf", "duesseldorf", "dusseldorf")
    assert city_aliases("Cologne") == ("cologne", "köln", "koeln")
    assert city_aliases("Munich") == ("munich", "münchen", "muenchen")


def test_duesseldorf_spelling_variants_are_normalized() -> None:
    client = FakeKeenableClient(
        [
            {
                "title": "Eigentumswohnung mit Süd-Terrasse in Düsseldorf-Urdenbach",
                "url": "https://example.com/listing/umlaut",
                "snippet": "Kaufpreis 515.000 €, 126 m², 3 Zimmer in Düsseldorf.",
            },
            {
                "title": "Eigentumswohnung mit Süd-Terrasse in Düsseldorf-Urdenbach",
                "url": "https://example.com/listing/transliterated",
                "snippet": "Kaufpreis 515.000 €, 126 m², 3 Zimmer in Duesseldorf.",
            },
            {
                "title": "Eigentumswohnung mit Süd-Terrasse in Düsseldorf-Urdenbach",
                "url": "https://example.com/listing/ascii",
                "snippet": "Kaufpreis 515.000 €, 126 m², 3 Zimmer in Dusseldorf.",
            },
        ]
    )

    listings = KeenableListingSearchService(client).search(duesseldorf_criteria())

    assert [str(listing.listing_url) for listing in listings] == [
        "https://example.com/listing/umlaut",
        "https://example.com/listing/transliterated",
        "https://example.com/listing/ascii",
    ]
    assert all(listing.asking_price.amount == 515_000 for listing in listings)


def test_eigentumswohnung_without_rental_intent_counts_as_purchase() -> None:
    result = {
        "title": "Schöne Eigentumswohnung in Düsseldorf",
        "url": "https://example.com/etw",
        "snippet": "126 m², 3 Zimmer, Baujahr 1990, Balkon. 515.000 €.",
    }

    listing = normalize_search_result(result, duesseldorf_criteria())

    assert listing is not None
    assert listing.asking_price.amount == 515_000


def test_zum_verkauf_counts_as_purchase_marker() -> None:
    result = {
        "title": "Wohnung mit Loggia in Düsseldorf-Bilk",
        "url": "https://example.com/verkauf",
        "snippet": "Zum Verkauf steht eine gepflegte 2-Zimmer-Wohnung. 238.500 €, 55 m².",
    }

    listing = normalize_search_result(result, duesseldorf_criteria())

    assert listing is not None
    assert listing.asking_price.amount == 238_500


def test_sale_listing_mentioning_rental_income_is_accepted() -> None:
    result = {
        "title": "Vermietete Eigentumswohnung zur Kapitalanlage in Düsseldorf",
        "url": "https://example.com/vermietet",
        "snippet": (
            "Kaufpreis 295.000 €, 68 m², 3 Zimmer. "
            "Vermietet, Kaltmiete 950 € monatlich."
        ),
    }

    listing = normalize_search_result(result, duesseldorf_criteria())

    assert listing is not None
    assert listing.asking_price.amount == 295_000


def test_rental_listings_are_rejected_as_rental_intent() -> None:
    rental = {
        "title": "2-Zimmer Wohnung mieten in Düsseldorf 40489 - 54 m²",
        "url": "https://example.com/rental",
        "snippet": "Wohnfläche 54 m², Zimmer 2, Verfügbar ab 13.06.2026.",
    }
    rental_etw = {
        "title": "Eigentumswohnung mieten in Düsseldorf",
        "url": "https://example.com/etw-rental",
        "snippet": "3 Zimmer, 88 m², zur Vermietung ab sofort.",
    }

    service = KeenableListingSearchService(FakeKeenableClient([rental, rental_etw]))

    assert service.search(duesseldorf_criteria()) == []
    assert service.last_rejections == [
        {
            "title": rental["title"],
            "url": rental["url"],
            "reasons": ["rental-intent", "no-price"],
        },
        {
            "title": rental_etw["title"],
            "url": rental_etw["url"],
            "reasons": ["rental-intent", "no-price"],
        },
    ]


def test_usd_amount_on_next_line_is_not_recorded_as_eur_price() -> None:
    result = {
        "title": "Eigentumswohnung mit Süd-Terrasse im Herzen von Urdenbach",
        "url": "https://example.com/usd-adjacent",
        "snippet": (
            "Drängenburger Straße, Dusseldorf, Germany\n"
            "$556,200\n€515,000 · as listed\n"
            "The property comprises 3 bedrooms and 126 square metres of interior space."
        ),
    }

    listing = normalize_search_result(result, duesseldorf_criteria())

    assert listing is not None
    assert listing.asking_price.amount == 515_000
    assert listing.living_area_sqm == 126
    assert listing.room_count == 3


def test_eur_price_values_skip_dollar_prefixed_amounts() -> None:
    assert eur_price_values("$556,200 €515,000") == [515_000.0]
    assert eur_price_values("€515,000") == [515_000.0]
    assert eur_price_values("785.000,00 €") == [785_000.0]


def test_multi_price_aggregator_page_is_quarantined() -> None:
    result = {
        "title": "Wohnung kaufen in Düsseldorf – Aktuelle Angebote",
        "url": "https://example.com/aggregator-prices",
        "snippet": (
            "Penthouse Oberkassel, 55 m², 2 Zimmer\n365.000 € Kaufpreis\n"
            "Erdgeschoss-Wohnung, 50 m², 2 Zimmer\n259.000 € Kaufpreis\n"
            "2,5 Zimmer mit Balkon\n238.500 € Kaufpreis"
        ),
    }

    service = KeenableListingSearchService(FakeKeenableClient([result]))

    assert service.search(duesseldorf_criteria()) == []
    assert service.last_rejections == [
        {
            "title": result["title"],
            "url": result["url"],
            "reasons": ["multi-listing-page"],
        }
    ]


def test_multi_postcode_aggregator_page_is_quarantined() -> None:
    result = {
        "title": "2-Zimmer-Wohnung kaufen in Düsseldorf - immobilo",
        "url": "https://example.com/aggregator-postcodes",
        "snippet": (
            "Kaufpreis\n40217 Düsseldorf\nWohnfläche: 70m², Zimmer: 2\n785.000,00 €\n"
            "Kaufpreis\n40589 Düsseldorf\nWohnfläche: 88m², Zimmer: 2\n785.000,00 €"
        ),
    }

    service = KeenableListingSearchService(FakeKeenableClient([result]))

    assert service.search(duesseldorf_criteria()) == []
    assert service.last_rejections[0]["reasons"] == ["multi-listing-page"]


def test_single_property_listing_within_all_criteria_passes_scout() -> None:
    # Captured Keenable snapshot: an ImmoScout24 mirror listing whose price,
    # area, and room count demonstrably belong to one identifiable property.
    result = captured_results("keenable_duesseldorf_natural_query.json")[1]

    listing = normalize_search_result(result, duesseldorf_criteria())

    assert listing is not None
    assert listing.asking_price.amount == 515_000
    assert listing.living_area_sqm == 126
    assert listing.room_count == 3
    assert str(listing.listing_url).startswith("https://untera.io/listings/")

    state = market_scout({"criteria": duesseldorf_criteria(), "property": listing})
    assert state["scout_assessment"].matches_hard_criteria is True
    assert state["scout_assessment"].reasons == []


def test_captured_natural_query_candidates_respect_hard_filters() -> None:
    criteria = duesseldorf_criteria()
    listings = KeenableListingSearchService(
        FakeKeenableClient(captured_results("keenable_duesseldorf_natural_query.json"))
    ).search(criteria)

    assert [listing.asking_price.amount for listing in listings] == [
        195_000.0,
        515_000.0,
        669_999.0,
    ]

    assessments = {
        str(listing.listing_url): market_scout(
            {"criteria": criteria, "property": listing}
        )["scout_assessment"]
        for listing in listings
    }
    urdenbach_url = next(url for url in assessments if "xNjQxMzI2MDM" in url)
    assert assessments[urdenbach_url].matches_hard_criteria is True
    assert assessments[urdenbach_url].reasons == []

    aggregator_url = next(url for url in assessments if "immobilie1.de" in url)
    assert (
        "Living area is below the configured minimum" in assessments[aggregator_url].reasons
    )

    luisen_url = next(url for url in assessments if "xNjU4NjQ3Mzk" in url)
    assert (
        "Asking price exceeds the maximum purchase price" in assessments[luisen_url].reasons
    )


def test_captured_duesseldorf_snapshots_replay_with_quarantine() -> None:
    criteria = duesseldorf_criteria()

    pipeline = KeenableListingSearchService(
        FakeKeenableClient(captured_results("keenable_duesseldorf_pipeline_query.json"))
    )
    assert pipeline.search(criteria) == []
    pipeline_reasons = [entry["reasons"] for entry in pipeline.last_rejections]
    assert len(pipeline_reasons) == 10
    # Both formerly accepted candidates were attribute-stitched aggregator
    # pages; they are quarantined instead of fabricating composite listings.
    assert pipeline_reasons.count(["multi-listing-page"]) == 2
    assert sum("rental-intent" in reasons for reasons in pipeline_reasons) == 6
    assert sum("no-price" in reasons for reasons in pipeline_reasons) == 8

    natural = KeenableListingSearchService(
        FakeKeenableClient(captured_results("keenable_duesseldorf_natural_query.json"))
    )
    listings = natural.search(criteria)
    assert [listing.asking_price.amount for listing in listings] == [
        195_000.0,
        515_000.0,
        669_999.0,
    ]
    natural_reasons = [entry["reasons"] for entry in natural.last_rejections]
    assert len(natural_reasons) == 7
    assert sum("multi-listing-page" in reasons for reasons in natural_reasons) == 3
    assert sum("no-price" in reasons for reasons in natural_reasons) == 3
    assert sum("no-city-match" in reasons for reasons in natural_reasons) == 1

    site_scoped = KeenableListingSearchService(
        FakeKeenableClient(captured_results("keenable_duesseldorf_site_scoped_query.json"))
    )
    assert site_scoped.search(criteria) == []
    assert len(site_scoped.last_rejections) == 10
    assert all(site_scoped.last_rejections)
