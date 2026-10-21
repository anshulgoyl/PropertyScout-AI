"""Investment analysis calculations and pluggable qualitative reasoners."""

from __future__ import annotations

import json
from typing import Protocol

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from propertyscout.config import ModelSettings
from propertyscout.schemas import (
    AnalysisRecommendation,
    FinancialMetrics,
    InvestmentAnalysis,
    InvestmentCriteria,
    InvestmentJudgment,
    Money,
    PropertyListing,
)

PURCHASE_COST_RATE = 0.10


class InvestmentReasoner(Protocol):
    """Provider-neutral interface for qualitative investment judgment."""

    def judge(
        self,
        property_listing: PropertyListing,
        criteria: InvestmentCriteria,
        metrics: FinancialMetrics,
    ) -> InvestmentJudgment: ...


class RuleBasedReasoner:
    """Deterministic default used for tests and development."""

    def judge(
        self,
        property_listing: PropertyListing,
        criteria: InvestmentCriteria,
        metrics: FinancialMetrics,
    ) -> InvestmentJudgment:
        gross_yield = metrics.gross_yield
        minimum_yield = criteria.minimum_gross_yield
        meets_yield = gross_yield is not None and (
            minimum_yield is None or gross_yield >= minimum_yield
        )
        return InvestmentJudgment(
            recommendation=(
                AnalysisRecommendation.SHORTLIST
                if meets_yield
                else AnalysisRecommendation.REJECT
            ),
            thesis=(
                "The property meets the configured gross-yield threshold."
                if meets_yield
                else "The property is below the configured gross-yield threshold."
            ),
            strengths=[f"Calculated gross yield is {gross_yield:.2%}."]
            if meets_yield and gross_yield is not None
            else [],
            risks=["Operating costs and financing are not included in this MVP analysis."],
        )


class LLMInvestmentReasoner:
    """Qualitative reasoner backed by any compatible LangChain chat model."""

    def __init__(self, model: BaseChatModel) -> None:
        self._structured_model = model.with_structured_output(
            InvestmentJudgment,
            method="json_schema",
        )

    def judge(
        self,
        property_listing: PropertyListing,
        criteria: InvestmentCriteria,
        metrics: FinancialMetrics,
    ) -> InvestmentJudgment:
        facts = {
            "property": property_listing.model_dump(mode="json"),
            "investment_criteria": criteria.model_dump(mode="json"),
            "calculated_metrics": metrics.model_dump(mode="json"),
        }
        result = self._structured_model.invoke(
            [
                SystemMessage(
                    content=(
                        "You are a cautious real-estate investment analyst. Evaluate only the "
                        "provided facts and calculated metrics. Never recalculate or alter numeric "
                        "metrics. Identify material strengths and risks. Recommend reject, review, "
                        "research, or shortlist. Do not claim legal, tax, or financial certainty."
                    )
                ),
                HumanMessage(content=json.dumps(facts, indent=2)),
            ]
        )
        if not isinstance(result, InvestmentJudgment):
            return InvestmentJudgment.model_validate(result)
        return result


def create_nebius_reasoner(settings: ModelSettings | None = None) -> LLMInvestmentReasoner:
    settings = settings or ModelSettings.from_env()
    if settings.provider != "nebius":
        raise ValueError("create_nebius_reasoner requires provider='nebius'")

    model = ChatOpenAI(
        model=settings.model,
        api_key=settings.api_key,
        base_url=settings.base_url,
        temperature=settings.temperature,
        max_retries=2,
    )
    return LLMInvestmentReasoner(model)


def analyse_property(
    property_listing: PropertyListing,
    criteria: InvestmentCriteria,
    reasoner: InvestmentReasoner,
) -> InvestmentAnalysis:
    """Combine trusted calculations with a bounded qualitative judgment."""

    price = property_listing.asking_price
    total_cost = Money(
        amount=round(price.amount * (1 + PURCHASE_COST_RATE), 2),
        currency=price.currency,
    )

    if property_listing.annual_rent is None:
        return InvestmentAnalysis(
            metrics=FinancialMetrics(purchase_price=price, estimated_total_cost=total_cost),
            recommendation=AnalysisRecommendation.RESEARCH,
            thesis="Rental income is required before the yield can be assessed.",
            assumptions=["Acquisition costs are estimated at 10% of purchase price."],
            risks=["The investment return cannot be evaluated without rental income."],
            missing_critical_data=["annual_rent"],
            evidence=property_listing.evidence,
        )

    if property_listing.annual_rent.currency != price.currency:
        return InvestmentAnalysis(
            metrics=FinancialMetrics(
                purchase_price=price,
                estimated_total_cost=total_cost,
                annual_rent=property_listing.annual_rent,
            ),
            recommendation=AnalysisRecommendation.RESEARCH,
            thesis="Rental income and purchase price require a common currency.",
            risks=["No exchange-rate evidence is available."],
            missing_critical_data=["exchange_rate"],
            evidence=property_listing.evidence,
        )

    gross_yield = property_listing.annual_rent.amount / price.amount
    metrics = FinancialMetrics(
        purchase_price=price,
        estimated_total_cost=total_cost,
        annual_rent=property_listing.annual_rent,
        gross_yield=gross_yield,
    )
    judgment = reasoner.judge(property_listing, criteria, metrics)

    minimum_yield = criteria.minimum_gross_yield
    if minimum_yield is not None and gross_yield < minimum_yield:
        recommendation = AnalysisRecommendation.REJECT
    elif judgment.recommendation == AnalysisRecommendation.RESEARCH:
        recommendation = AnalysisRecommendation.REVIEW
    else:
        recommendation = judgment.recommendation

    return InvestmentAnalysis(
        metrics=metrics,
        score=max(0, min(100, round(gross_yield * 1_000))),
        recommendation=recommendation,
        thesis=judgment.thesis,
        assumptions=[
            "Gross yield equals annual rent divided by asking price.",
            "Acquisition costs are estimated at 10% of purchase price.",
        ],
        strengths=judgment.strengths,
        risks=judgment.risks,
        evidence=property_listing.evidence,
    )

