from propertyscout.analyst import (
    InvestmentReasoner,
    analyse_property,
    select_comparable_listings,
)
from propertyscout.bootstrap import default_criteria, fixture_market_basis
from propertyscout.fixtures import sample_properties
from propertyscout.schemas import (
    AnalysisRecommendation,
    FinancialMetrics,
    InvestmentCriteria,
    InvestmentJudgment,
    MarketValuation,
    Money,
    PropertyCondition,
    PropertyListing,
)


class FakeReasoner(InvestmentReasoner):
    def judge(
        self,
        property_listing: PropertyListing,
        criteria: InvestmentCriteria,
        metrics: FinancialMetrics,
        valuation: MarketValuation | None = None,
    ) -> InvestmentJudgment:
        return InvestmentJudgment(
            recommendation=AnalysisRecommendation.SHORTLIST,
            thesis="Fake qualitative judgment for an offline test.",
            strengths=["The fixture is priced near the comparable-based estimate."],
            risks=["The fixture does not contain operating expenses."],
        )


def test_value_based_metrics_are_not_changed_by_the_reasoner() -> None:
    analysis = analyse_property(
        sample_properties()["shortlist"],
        default_criteria(),
        FakeReasoner(),
        fixture_market_basis(),
    )

    assert analysis.metrics.gross_yield == 15_120 / 210_000
    assert analysis.metrics.estimated_total_cost.amount == 231_000
    assert analysis.valuation is not None
    assert analysis.valuation.estimated_market_value.amount == round(62 * 4938.0, 2)
    assert analysis.score_components is not None
    assert analysis.score == round(sum(analysis.score_components.values()))
    assert analysis.recommendation == AnalysisRecommendation.SHORTLIST
    assert "Fake qualitative judgment for an offline test." in analysis.thesis


def test_analysis_exposes_explainable_confidence_and_score_drivers() -> None:
    analysis = analyse_property(
        sample_properties()["shortlist"],
        default_criteria(),
        FakeReasoner(),
        fixture_market_basis(),
    )

    assert analysis.confidence.level == "high"
    assert analysis.confidence.reason
    assert [driver.key for driver in analysis.score_drivers] == [
        "price_vs_market",
        "comparable_evidence",
        "rent_evidence",
        "building_energy_risk",
        "data_completeness",
    ]


def test_missing_critical_data_has_low_analysis_confidence() -> None:
    analysis = analyse_property(
        sample_properties()["research"].model_copy(update={"living_area_sqm": None}),
        default_criteria(),
        FakeReasoner(),
        fixture_market_basis(),
    )

    assert analysis.confidence.level == "low"
    assert "living area" in analysis.confidence.reason.lower()


def test_missing_area_routes_to_research() -> None:
    listing = sample_properties()["research"].model_copy(
        update={"living_area_sqm": None}
    )

    analysis = analyse_property(
        listing, default_criteria(), FakeReasoner(), fixture_market_basis()
    )

    assert analysis.recommendation == AnalysisRecommendation.RESEARCH
    assert analysis.missing_critical_data == ["living_area_sqm"]


def test_missing_market_basis_routes_to_research() -> None:
    analysis = analyse_property(
        sample_properties()["research"], default_criteria(), FakeReasoner(), None
    )

    assert analysis.recommendation == AnalysisRecommendation.RESEARCH
    assert analysis.missing_critical_data == ["market_basis"]


def test_discovery_comparable_selection_excludes_subject_and_confirmed_duplicates() -> None:
    subject = sample_properties()["shortlist"].model_copy(
        update={"postal_code": "50667", "room_count": 3}
    )
    same_postcode = subject.model_copy(
        update={
            "source_listing_id": "same-postcode",
            "listing_url": "https://example.com/comp/same-postcode",
            "asking_price": Money(amount=220_000, currency="EUR"),
        }
    )
    nearby_postcode = subject.model_copy(
        update={
            "source_listing_id": "nearby-postcode",
            "listing_url": "https://example.com/comp/nearby-postcode",
            "postal_code": "50668",
            "asking_price": Money(amount=230_000, currency="EUR"),
        }
    )
    numeric_but_unconfirmed = subject.model_copy(
        update={
            "source_listing_id": "numeric-but-unconfirmed",
            "listing_url": "https://example.com/comp/numeric-but-unconfirmed",
            "postal_code": "50666",
            "asking_price": Money(amount=225_000, currency="EUR"),
        }
    )
    confirmed_duplicate = subject.model_copy(
        update={
            "source_listing_id": "confirmed-duplicate",
            "listing_url": "https://example.com/comp/confirmed-duplicate",
            "asking_price": Money(amount=240_000, currency="EUR"),
        }
    )
    selected = select_comparable_listings(
        subject,
        [
            subject,
            numeric_but_unconfirmed,
            nearby_postcode,
            confirmed_duplicate,
            same_postcode,
        ],
        confirmed_duplicate_urls={"https://example.com/comp/confirmed-duplicate"},
        nearby_postcodes=["50668"],
    )

    assert [listing.source_listing_id for listing in selected] == [
        "same-postcode",
        "nearby-postcode",
        "numeric-but-unconfirmed",
    ]


def test_condition_bucket_median_is_used_when_available() -> None:
    listing = sample_properties()["shortlist"].model_copy(
        update={"condition": PropertyCondition.RENOVATED}
    )

    analysis = analyse_property(
        listing, default_criteria(), FakeReasoner(), fixture_market_basis()
    )

    assert analysis.valuation is not None
    assert analysis.valuation.comp_eur_per_sqm == 5_100
    assert analysis.valuation.comp_count == 3
    assert analysis.valuation.adjustments == {}


def test_condition_fallback_applies_documented_adjustment() -> None:
    listing = sample_properties()["shortlist"].model_copy(
        update={"condition": PropertyCondition.WELL_MAINTAINED}
    )

    analysis = analyse_property(
        listing, default_criteria(), FakeReasoner(), fixture_market_basis()
    )

    assert analysis.valuation is not None
    assert analysis.valuation.adjustments == {"condition_fallback": 1.03}
    assert analysis.valuation.comp_eur_per_sqm == round(4938.0 * 1.03, 2)


def test_overpriced_property_is_rejected_by_value_gap() -> None:
    listing = sample_properties()["shortlist"].model_copy(
        update={"asking_price": Money(amount=460_000, currency="EUR")}
    )

    analysis = analyse_property(
        listing, default_criteria(), FakeReasoner(), fixture_market_basis()
    )

    assert analysis.recommendation == AnalysisRecommendation.REJECT


def test_moderately_overpriced_property_warrants_review() -> None:
    listing = sample_properties()["shortlist"].model_copy(
        update={"asking_price": Money(amount=380_000, currency="EUR")}
    )

    analysis = analyse_property(
        listing, default_criteria(), FakeReasoner(), fixture_market_basis()
    )

    assert analysis.recommendation == AnalysisRecommendation.REVIEW
