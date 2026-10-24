import json
from pathlib import Path

import pytest

from propertyscout.analyst import build_market_basis
from propertyscout.bootstrap import default_criteria
from propertyscout.config import detail_fetch_limit_from_env, search_query_limit_from_env
from propertyscout.fixtures import sample_comparables
from propertyscout.graph import create_state_serializer
from propertyscout.market_search import (
    KeenableListingSearchService,
    build_property_query,
    canonical_url,
    city_aliases,
    comparable_queries,
    eur_price_values,
    extract_condition,
    merge_page_listing,
    normalize_search_result,
    search_queries,
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


class FakeKeenableFetch:
    def __init__(self, pages):
        self.pages = dict(pages)
        self.calls = []

    def invoke(self, tool_input):
        self.calls.append(tool_input)
        return self.pages.get(tool_input["url"], "fetch unavailable")


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

    service = KeenableListingSearchService(
        FakeKeenableClient([rental, rental_etw]), search_query_limit=1
    )

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

    service = KeenableListingSearchService(
        FakeKeenableClient([result]), search_query_limit=1
    )

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

    service = KeenableListingSearchService(
        FakeKeenableClient([result]), search_query_limit=1
    )

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
        QueuedKeenableClient(
            [captured_results("keenable_duesseldorf_natural_query.json")]
        ),
        fetch_client=FakeKeenableFetch({}),
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
        QueuedKeenableClient(
            [captured_results("keenable_duesseldorf_pipeline_query.json")]
        ),
        fetch_client=FakeKeenableFetch({}),
    )
    assert pipeline.search(criteria) == []
    pipeline_reasons = [entry["reasons"] for entry in pipeline.last_rejections]
    assert len(pipeline_reasons) == 10
    # Both formerly accepted candidates were attribute-stitched aggregator
    # pages; they are quarantined instead of fabricating composite listings.
    assert pipeline_reasons.count(["multi-listing-page"]) == 2
    assert sum("rental-intent" in reasons for reasons in pipeline_reasons) == 6
    assert sum("no-price" in reasons for reasons in pipeline_reasons) == 8
    assert pipeline.last_fetches[0]["status"] == "fetch-error"

    natural = KeenableListingSearchService(
        QueuedKeenableClient(
            [captured_results("keenable_duesseldorf_natural_query.json")]
        ),
        fetch_client=FakeKeenableFetch({}),
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
        QueuedKeenableClient(
            [captured_results("keenable_duesseldorf_site_scoped_query.json")]
        ),
        fetch_client=FakeKeenableFetch({}),
    )
    assert site_scoped.search(criteria) == []
    assert len(site_scoped.last_rejections) == 10
    assert all(site_scoped.last_rejections)



@pytest.mark.parametrize(
    "city",
    ["Düsseldorf", "Cologne", "Wuppertal", "Berlin", "München"],
)
def test_search_queries_primary_then_fallback_variants(city: str) -> None:
    criteria = duesseldorf_criteria().model_copy(
        update={"locations": [city]}
    )

    queries = search_queries(criteria)

    # Primary query always comes first.
    assert queries[0] == build_property_query(criteria)

    # Generate multiple search variations.
    assert len(queries) > 3

    # No duplicate queries.
    assert len(queries) == len(set(queries))

    # Search queries must include the requested city.
 
    aliases = city_aliases(city)
    assert all(
    any(alias.casefold() in query.casefold() for alias in aliases)
    for query in queries
)

    # Original broad fallback must remain available.
    assert f"Eigentumswohnung kaufen {city}" in queries



def test_canonical_url_strips_tracking_and_keeps_identifiers() -> None:
    assert (
        canonical_url("https://example.com/listing/123?utm_source=x&fbclid=y&id=9")
        == "https://example.com/listing/123?id=9"
    )
    assert (
        canonical_url("https://Example.com/Listing/123/")
        == "https://example.com/Listing/123"
    )
    assert (
        canonical_url(
            "https://immobilienscout24.de/anbieten?amp;utm_campaign=x&amp;utm_source=y"
        )
        == "https://immobilienscout24.de/anbieten"
    )


def test_enrichment_fetches_page_for_incomplete_listing() -> None:
    incomplete = {
        "title": "Eigentumswohnung in Düsseldorf-Benrath",
        "url": "https://example.com/listing/etw",
        "snippet": "Kaufpreis 295.000 € in Düsseldorf.",
    }
    fetch = FakeKeenableFetch(
        {
            "https://example.com/listing/etw": {
                "title": "Eigentumswohnung in Düsseldorf-Benrath",
                "content": (
                    "Kaufpreis 295.000 €\nWohnfläche: 68 m²\n3 Zimmer\n"
                    "Baujahr 1990\nBalkon\n40229 Düsseldorf"
                ),
            }
        }
    )
    search = FakeKeenableClient([incomplete])
    service = KeenableListingSearchService(
        search, fetch_client=fetch, search_query_limit=1
    )

    listings = service.search(duesseldorf_criteria())

    assert len(listings) == 1
    listing = listings[0]
    assert listing.asking_price.amount == 295_000
    assert listing.living_area_sqm == 68
    assert listing.room_count == 3
    assert listing.postal_code == "40229"
    assert listing.build_year == 1990
    assert len(listing.evidence) == 2
    assert listing.evidence[1].source_name == "Keenable page fetch"
    assert len(search.inputs) == 1
    assert fetch.calls == [{"url": "https://example.com/listing/etw"}]
    assert service.last_fetches == [
        {"url": "https://example.com/listing/etw", "status": "accepted"}
    ]
    assert service.last_incomplete == []


def test_fetch_recovers_listing_for_no_price_candidate() -> None:
    fetch = FakeKeenableFetch(
        {
            "https://www.kleinanzeigen.de/s-wohnung-kaufen/benrath/2-zimmer-wohnung/k0c196l16753": {
                "title": "Exklusive 3-Zimmer-Eigentumswohnung in Düsseldorf-Benrath",
                "content": (
                    "Kaufpreis 689.000 €\nWohnfläche: 114,2 m²\n3 Zimmer\n"
                    "40229 Düsseldorf-Benrath\nBaujahr 2015\nBalkon"
                ),
            }
        }
    )
    search = QueuedKeenableClient(
        [captured_results("keenable_duesseldorf_pipeline_query.json")]
    )
    service = KeenableListingSearchService(search, fetch_client=fetch)

    listings = service.search(duesseldorf_criteria())

    assert len(listings) == 1
    listing = listings[0]
    assert listing.asking_price.amount == 689_000
    assert listing.living_area_sqm == 114.2
    assert listing.room_count == 3
    assert listing.postal_code == "40229"
    assert str(listing.listing_url).startswith("https://www.kleinanzeigen.de/")
    assert len(search.inputs) == 1
    # Two no-price candidates (kleinanzeigen, von-poll) are fetched; only the
    # one with a real detail page is recovered.
    assert len(fetch.calls) == 2
    assert service.last_fetches[0]["status"] == "accepted"
    assert service.last_fetches[1]["status"] == "fetch-error"
    assert len(service.last_incomplete) == 0


def test_detail_fetch_limit_bounds_fetch_calls() -> None:
    results = [
        {
            "title": f"Eigentumswohnung in Düsseldorf {index}",
            "url": f"https://example.com/listing/{index}",
            "snippet": "Preis auf Anfrage in Düsseldorf.",
        }
        for index in range(4)
    ]
    fetch = FakeKeenableFetch({})
    service = KeenableListingSearchService(
        FakeKeenableClient(results),
        fetch_client=fetch,
        detail_fetch_limit=2,
        search_query_limit=1,
    )

    assert service.search(duesseldorf_criteria()) == []

    assert len(fetch.calls) == 2
    assert len(service.last_fetches) == 2
    assert all(entry["status"] == "fetch-error" for entry in service.last_fetches)
    assert sum(
        entry["reasons"] == ["no-price"] for entry in service.last_rejections
    ) == 4


def test_fetch_error_records_failure_and_uses_fallback_query() -> None:
    fetch = FakeKeenableFetch({})
    search = QueuedKeenableClient(
        [
            captured_results("keenable_duesseldorf_pipeline_query.json"),
            captured_results("keenable_duesseldorf_natural_query.json"),
        ]
    )
    service = KeenableListingSearchService(search, fetch_client=fetch)

    listings = service.search(duesseldorf_criteria())

    assert [listing.asking_price.amount for listing in listings] == [
        195_000.0,
        515_000.0,
        669_999.0,
    ]
    assert len(search.inputs) == 2
    assert service.last_fetches[0]["status"] == "fetch-error"
    assert len(fetch.calls) == 3


def test_fetched_multi_listing_page_is_rejected() -> None:
    incomplete = {
        "title": "Eigentumswohnung in Düsseldorf",
        "url": "https://example.com/listing/multi",
        "snippet": "Kaufpreis 295.000 € in Düsseldorf.",
    }
    fetch = FakeKeenableFetch(
        {
            "https://example.com/listing/multi": {
                "title": "Eigentumswohnung in Düsseldorf",
                "content": (
                    "Kaufpreis 295.000 €\nKaufpreis 250.000 €\n"
                    "40217 Düsseldorf\n40589 Düsseldorf"
                ),
            }
        }
    )
    service = KeenableListingSearchService(
        FakeKeenableClient([incomplete]),
        fetch_client=fetch,
        search_query_limit=1,
    )

    assert service.search(duesseldorf_criteria()) == []

    assert service.last_fetches[0]["status"] == "rejected"
    assert service.last_fetches[0]["reasons"] == ["multi-listing-page"]
    assert service.last_incomplete[0]["reasons"] == ["multi-listing-page"]


def test_conflicting_page_price_and_postal_quarantines_candidate() -> None:
    incomplete = {
        "title": "Eigentumswohnung in Düsseldorf",
        "url": "https://example.com/listing/conflict",
        "snippet": "Kaufpreis 295.000 €\n40217 Düsseldorf.",
    }
    fetch = FakeKeenableFetch(
        {
            "https://example.com/listing/conflict": {
                "title": "Eigentumswohnung in Düsseldorf",
                "content": (
                    "Kaufpreis 350.000 €\n40213 Düsseldorf\n"
                    "Wohnfläche: 68 m²\n3 Zimmer"
                ),
            }
        }
    )
    service = KeenableListingSearchService(
        FakeKeenableClient([incomplete]),
        fetch_client=fetch,
        search_query_limit=1,
    )

    assert service.search(duesseldorf_criteria()) == []

    assert service.last_fetches[0]["status"] == "rejected"
    assert "conflicting-attributes" in service.last_fetches[0]["reasons"]
    assert "price-conflict" in service.last_fetches[0]["reasons"]
    assert service.last_fetches[0]["prices"] == {
        "snippet": 295_000.0,
        "page": 350_000.0,
    }


def test_page_price_adopted_with_warning_when_identity_is_clear() -> None:
    incomplete = {
        "title": "Eigentumswohnung in Düsseldorf",
        "url": "https://example.com/listing/update",
        "snippet": "Kaufpreis 295.000 € in Düsseldorf.",
    }
    fetch = FakeKeenableFetch(
        {
            "https://example.com/listing/update": {
                "title": "Eigentumswohnung in Düsseldorf",
                "content": (
                    "Kaufpreis 298.000 €\nWohnfläche: 68 m²\n3 Zimmer\nDüsseldorf"
                ),
            }
        }
    )
    service = KeenableListingSearchService(
        FakeKeenableClient([incomplete]),
        fetch_client=fetch,
        search_query_limit=1,
    )

    listings = service.search(duesseldorf_criteria())

    assert listings[0].asking_price.amount == 298_000
    assert listings[0].living_area_sqm == 68
    assert listings[0].room_count == 3
    assert service.last_fetches[0]["status"] == "price-updated"
    assert service.last_fetches[0]["prices"] == {
        "snippet": 295_000.0,
        "page": 298_000.0,
    }


def test_duplicate_urls_are_deduplicated_across_queries() -> None:
    incomplete_snippet = "Kaufpreis 295.000 € in Düsseldorf."
    search = QueuedKeenableClient(
        [
            [
                {
                    "title": "Eigentumswohnung in Düsseldorf",
                    "url": "https://example.com/listing/1?utm_source=portal",
                    "snippet": incomplete_snippet,
                }
            ],
            [
                {
                    "title": "Eigentumswohnung in Düsseldorf",
                    "url": "https://example.com/listing/1?utm_source=other",
                    "snippet": incomplete_snippet,
                }
            ],
        ]
    )
    fetch = FakeKeenableFetch({})
    service = KeenableListingSearchService(search, fetch_client=fetch)

    listings = service.search(duesseldorf_criteria())

    assert listings == []
    assert len(search.inputs) == 3
    # The same canonical URL is fetched once, never again across fallback queries.
    assert len(fetch.calls) == 1
    assert sum(
        entry["reasons"] == ["duplicate-url"] for entry in service.last_rejections
    ) == 1


def test_incomplete_listings_stay_out_of_search_results() -> None:
    complete = {
        "title": "Eigentumswohnung in Düsseldorf",
        "url": "https://example.com/listing/complete",
        "snippet": "Kaufpreis 295.000 €, 68 m², 3 Zimmer in Düsseldorf.",
    }
    incomplete = {
        "title": "Eigentumswohnung in Düsseldorf",
        "url": "https://example.com/listing/incomplete",
        "snippet": "Kaufpreis 320.000 € in Düsseldorf.",
    }
    fetch = FakeKeenableFetch({})
    service = KeenableListingSearchService(
        FakeKeenableClient([complete, incomplete]),
        fetch_client=fetch,
        detail_fetch_limit=0,
        search_query_limit=1,
    )

    listings = service.search(duesseldorf_criteria())

    assert [str(listing.listing_url) for listing in listings] == [
        "https://example.com/listing/complete"
    ]
    assert len(service.last_incomplete) == 1
    assert service.last_incomplete[0]["missing"] == ["living_area", "room_count"]
    assert fetch.calls == []


def test_search_query_budget_is_respected() -> None:
    search = QueuedKeenableClient([[], []])
    fetch = FakeKeenableFetch({})
    service = KeenableListingSearchService(
        search, fetch_client=fetch, search_query_limit=2
    )

    assert service.search(duesseldorf_criteria()) == []

    assert len(search.inputs) == 2


def test_discovery_budget_env_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROPERTYSCOUT_DETAIL_FETCH_LIMIT", "1")
    monkeypatch.setenv("PROPERTYSCOUT_SEARCH_QUERY_LIMIT", "5")
    assert detail_fetch_limit_from_env() == 1
    assert search_query_limit_from_env() == 5

    monkeypatch.delenv("PROPERTYSCOUT_DETAIL_FETCH_LIMIT", raising=False)
    monkeypatch.delenv("PROPERTYSCOUT_SEARCH_QUERY_LIMIT", raising=False)
    assert detail_fetch_limit_from_env() == 3
    assert search_query_limit_from_env() == 3

    monkeypatch.setenv("PROPERTYSCOUT_DETAIL_FETCH_LIMIT", "abc")
    with pytest.raises(ValueError):
        detail_fetch_limit_from_env()
    monkeypatch.setenv("PROPERTYSCOUT_DETAIL_FETCH_LIMIT", "11")
    with pytest.raises(ValueError):
        detail_fetch_limit_from_env()


def duesseldorf_meerbusch_criteria() -> InvestmentCriteria:
    return InvestmentCriteria(
        locations=["Düsseldorf", "Meerbusch"],
        maximum_purchase_price=Money(amount=551_001, currency="EUR"),
        property_types=["apartment"],
        minimum_room_count=2,
        minimum_living_area_sqm=50,
        strategy="buy_to_let",
    )


def test_merge_page_listing_recognizes_all_configured_locations() -> None:
    criteria = duesseldorf_meerbusch_criteria()
    page = {
        "url": "https://www.immoportal.com/expose/111152",
        "title": "Helle Wohnung in Meerbusch",
        "content": "Kaufpreis 299.000 €\n62 m²\n3 Zimmer\n40668 Meerbusch",
    }

    merged, reasons = merge_page_listing(page, page["url"], criteria, None)
    assert reasons == []
    assert merged.city == "Meerbusch"  # actual property city preserved
    assert merged.postal_code == "40668"
    assert merged.living_area_sqm == 62
    assert merged.room_count == 3

    # A single-location criteria keeps rejecting Meerbusch-only pages.
    primary_only = criteria.model_copy(update={"locations": ["Düsseldorf"]})
    rejected, reasons = merge_page_listing(page, page["url"], primary_only, None)
    assert rejected is None
    assert reasons == ["no-city-match"]

    # A page that describes the primary location first keeps its label.
    primary_page = {
        "url": "https://www.immobilo.de/immobilien/wohnung-H4VFJW",
        "title": "Eigentumswohnung in Düsseldorf, Nähe Meerbusch",
        "content": "Kaufpreis 299.000 €\n62 m²\n3 Zimmer\n40211 Düsseldorf",
    }
    labeled, reasons = merge_page_listing(primary_page, primary_page["url"], criteria, None)
    assert reasons == []
    assert labeled.city == "Düsseldorf"

