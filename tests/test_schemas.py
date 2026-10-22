from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from propertyscout.schemas import (
    AnalysisRecommendation,
    ConditionAverage,
    FinancialMetrics,
    InvestmentAnalysis,
    MarketBasis,
    MarketValuation,
    MeetingDetails,
    Money,
    PropertyCondition,
    PropertyListing,
)


def test_shortlist_rejects_missing_critical_data() -> None:
    with pytest.raises(ValidationError):
        InvestmentAnalysis(
            metrics=FinancialMetrics(purchase_price=Money(amount=250_000, currency="EUR")),
            recommendation=AnalysisRecommendation.SHORTLIST,
            thesis="Promising property, but rent is unknown.",
            missing_critical_data=["annual_rent"],
        )


def test_research_route_allows_missing_critical_data() -> None:
    analysis = InvestmentAnalysis(
        metrics=FinancialMetrics(purchase_price=Money(amount=250_000, currency="EUR")),
        recommendation=AnalysisRecommendation.RESEARCH,
        thesis="Rent evidence is required before a decision.",
        missing_critical_data=["annual_rent"],
    )

    assert analysis.recommendation == AnalysisRecommendation.RESEARCH


def test_meeting_end_must_follow_start() -> None:
    starts_at = datetime.now(UTC)

    with pytest.raises(ValidationError):
        MeetingDetails(
            starts_at=starts_at,
            ends_at=starts_at - timedelta(minutes=30),
            timezone="Europe/Berlin",
            attendee_emails=["broker@example.com"],
        )


def test_models_reject_unknown_agent_fields() -> None:
    with pytest.raises(ValidationError):
        Money(amount=100, currency="EUR", invented_by_model="unexpected")


def test_market_valuation_requires_positive_comp_reference() -> None:
    valuation = MarketValuation(
        estimated_market_value=Money(amount=300_000, currency="EUR"),
        comp_eur_per_sqm=4_800,
        value_gap=-0.06,
        comp_count=9,
        condition=PropertyCondition.WELL_MAINTAINED,
        basis="Cologne 50667 · 9 comparable listings",
    )

    assert valuation.adjustments == {}

    with pytest.raises(ValidationError):
        MarketValuation(
            estimated_market_value=Money(amount=300_000, currency="EUR"),
            comp_eur_per_sqm=0,
            value_gap=0.0,
            comp_count=0,
            basis="invalid",
        )


def test_property_listing_accepts_optional_value_signals() -> None:
    listing = PropertyListing(
        property_id="00000000-0000-0000-0000-000000000009",
        source_listing_id="signal-test",
        title="Renovated Cologne apartment",
        city="Cologne",
        country_code="DE",
        property_type="apartment",
        asking_price=Money(amount=240_000, currency="EUR"),
        build_year=1962,
        energy_class="C",
        condition=PropertyCondition.RENOVATED,
    )

    assert listing.build_year == 1962
    assert listing.energy_class == "C"
    assert listing.condition == PropertyCondition.RENOVATED

    with pytest.raises(ValidationError):
        PropertyListing(
            property_id="00000000-0000-0000-0000-000000000009",
            source_listing_id="signal-test",
            title="Bad build year",
            city="Cologne",
            country_code="DE",
            property_type="apartment",
            asking_price=Money(amount=240_000, currency="EUR"),
            build_year=1700,
        )


def test_market_basis_requires_positive_overall_reference() -> None:
    basis = MarketBasis(
        city="Cologne",
        postal_code="50667",
        property_type="apartment",
        overall_eur_per_sqm=4_900,
        overall_comp_count=12,
        by_condition=[
            ConditionAverage(
                condition=PropertyCondition.RENOVATED,
                eur_per_sqm=5_100,
                comp_count=5,
                source_urls=["https://example.com/listing"],
            )
        ],
        retrieved_at=datetime.now(UTC),
    )

    assert basis.by_condition[0].comp_count == 5
    assert basis.source == "Keenable comparable-listing search"

    with pytest.raises(ValidationError):
        MarketBasis(
            city="Cologne",
            property_type="apartment",
            overall_eur_per_sqm=0,
            overall_comp_count=0,
            retrieved_at=datetime.now(UTC),
        )

