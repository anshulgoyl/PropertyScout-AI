from propertyscout.analyst import InvestmentReasoner, analyse_property
from propertyscout.bootstrap import default_criteria
from propertyscout.fixtures import sample_properties
from propertyscout.schemas import (
    AnalysisRecommendation,
    FinancialMetrics,
    InvestmentCriteria,
    InvestmentJudgment,
    PropertyListing,
)


class FakeReasoner(InvestmentReasoner):
    def judge(
        self,
        property_listing: PropertyListing,
        criteria: InvestmentCriteria,
        metrics: FinancialMetrics,
    ) -> InvestmentJudgment:
        return InvestmentJudgment(
            recommendation=AnalysisRecommendation.SHORTLIST,
            thesis="Fake qualitative judgment for an offline test.",
            strengths=["The fixture meets the supplied yield threshold."],
            risks=["The fixture does not contain operating expenses."],
        )


def test_fake_reasoner_cannot_change_calculated_metrics() -> None:
    analysis = analyse_property(
        sample_properties()["shortlist"],
        default_criteria(),
        FakeReasoner(),
    )

    assert analysis.metrics.gross_yield == 15_120 / 210_000
    assert analysis.metrics.estimated_total_cost.amount == 231_000
    assert analysis.thesis == "Fake qualitative judgment for an offline test."


def test_missing_data_skips_qualitative_shortlist_recommendation() -> None:
    analysis = analyse_property(
        sample_properties()["research"],
        default_criteria(),
        FakeReasoner(),
    )

    assert analysis.recommendation == AnalysisRecommendation.RESEARCH
    assert analysis.missing_critical_data == ["annual_rent"]
