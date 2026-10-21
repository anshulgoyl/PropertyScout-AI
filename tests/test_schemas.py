from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from propertyscout.schemas import (
    AnalysisRecommendation,
    FinancialMetrics,
    InvestmentAnalysis,
    MeetingDetails,
    Money,
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

