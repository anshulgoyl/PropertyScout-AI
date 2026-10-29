"""Investment analysis calculations and pluggable qualitative reasoners."""

from __future__ import annotations

import json
import statistics
from datetime import UTC, datetime
from typing import Protocol

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from propertyscout.config import ModelSettings
from propertyscout.schemas import (
    AnalysisRecommendation,
    ConditionAverage,
    EvidenceConfidence,
    FinancialMetrics,
    InvestmentAnalysis,
    InvestmentCriteria,
    InvestmentJudgment,
    MarketBasis,
    MarketValuation,
    Money,
    PropertyCondition,
    PropertyListing,
    ScoreDriver,
)

PURCHASE_COST_RATE = 0.10

MIN_PLAUSIBLE_EUR_PER_SQM = 500.0
MAX_PLAUSIBLE_EUR_PER_SQM = 30_000.0

# Value-gap routing thresholds (asking price versus estimated market value).
SHORTLIST_MAX_GAP = 0.05
REJECT_GAP_THRESHOLD = 0.25

# A condition bucket needs this many comps before its median is trusted.
MIN_CONDITION_COMPS = 3

# Applied to the overall median only when no condition-specific comp bucket
# reaches ``MIN_CONDITION_COMPS``. Values are documented analysis assumptions.
CONDITION_ADJUSTMENTS: dict[PropertyCondition, float] = {
    PropertyCondition.RENOVATION_REQUIRED: 0.85,
    PropertyCondition.PARTIALLY_RENOVATED: 0.92,
    PropertyCondition.RENOVATED: 1.00,
    PropertyCondition.WELL_MAINTAINED: 1.03,
    PropertyCondition.NEW_CONSTRUCTION: 1.10,
}

SCORE_WEIGHTS = {
    "value_gap": 45.0,
    "comp_confidence": 20.0,
    "condition_energy": 20.0,
    "data_completeness": 15.0,
}

_ENERGY_POINTS = {
    "A++": 18.0,
    "A+": 18.0,
    "A": 18.0,
    "B": 15.0,
    "C": 12.0,
    "D": 9.0,
    "E": 6.0,
    "F": 3.0,
    "G": 0.0,
}

_CONDITION_BONUS: dict[PropertyCondition, float] = {
    PropertyCondition.NEW_CONSTRUCTION: 2.0,
    PropertyCondition.RENOVATED: 2.0,
    PropertyCondition.WELL_MAINTAINED: 1.0,
    PropertyCondition.PARTIALLY_RENOVATED: 0.0,
    PropertyCondition.RENOVATION_REQUIRED: -4.0,
}


def build_market_basis(
    comps: list[PropertyListing],
    criteria: InvestmentCriteria,
    exclude_urls: set[str] | None = None,
) -> MarketBasis | None:
    """Build the local market basis from normalized comparable listings.

    The overall median price per square metre plus one median per extracted
    condition bucket form the market reference for every deal of one search.
    Comps without a price and living area, with implausible per-square-metre
    values, or excluded by URL (for example subject listings that also appear
    in the comp pool) are dropped. Returns ``None`` when no usable comp
    remains so callers can route to research instead of inventing a basis.
    """

    excluded = {str(url).rstrip("/") for url in (exclude_urls or [])}
    overall: list[float] = []
    buckets: dict[PropertyCondition, list[tuple[float, str]]] = {}
    for comp in comps:
        if comp.asking_price is None or not comp.living_area_sqm:
            continue
        if comp.asking_price.currency != "EUR":
            continue
        url = str(comp.listing_url).rstrip("/") if comp.listing_url else ""
        if url and url in excluded:
            continue
        value = comp.asking_price.amount / comp.living_area_sqm
        if not MIN_PLAUSIBLE_EUR_PER_SQM <= value <= MAX_PLAUSIBLE_EUR_PER_SQM:
            continue
        overall.append(value)
        if comp.condition is not None:
            buckets.setdefault(comp.condition, []).append((value, url))

    if not overall:
        return None

    condition_averages = [
        ConditionAverage(
            condition=condition,
            eur_per_sqm=round(statistics.median([value for value, _ in values]), 2),
            comp_count=len(values),
            source_urls=sorted({url for _, url in values}),
        )
        for condition, values in sorted(
            buckets.items(), key=lambda item: item[0].name
        )
    ]
    return MarketBasis(
        city=criteria.locations[0],
        postal_code=criteria.postal_codes[0] if criteria.postal_codes else None,
        property_type=criteria.property_types[0],
        overall_eur_per_sqm=round(statistics.median(overall), 2),
        overall_comp_count=len(overall),
        by_condition=condition_averages,
        retrieved_at=datetime.now(UTC),
    )


def select_comparable_listings(
    subject: PropertyListing,
    candidates: list[PropertyListing],
    *,
    confirmed_duplicate_urls: set[str] | None = None,
    nearby_postcodes: list[str] | None = None,
) -> list[PropertyListing]:
    """Return usable comparables in deterministic location-first order.

    Postal-code numbers are identifiers, not coordinates.  Consequently this
    function gives priority only to the subject postcode and to postcodes
    explicitly provided in ``nearby_postcodes`` by a geographic resolver.  It
    never assumes that numerically adjacent German postcodes are nearby.
    """

    def canonical(value: object) -> str:
        return str(value or "").rstrip("/")

    subject_url = canonical(subject.listing_url)
    excluded_urls = {canonical(url) for url in (confirmed_duplicate_urls or set())}
    excluded_urls.add(subject_url)
    nearby_rank = {
        postcode: index + 1
        for index, postcode in enumerate(nearby_postcodes or [])
        if postcode and postcode != subject.postal_code
    }
    selected: list[tuple[tuple[float, float, str], PropertyListing]] = []
    seen_urls: set[str] = set()

    for candidate in candidates:
        url = canonical(candidate.listing_url)
        if not url or url in excluded_urls or url in seen_urls:
            continue
        if candidate.source_listing_id == subject.source_listing_id:
            continue
        if candidate.property_type.casefold() != subject.property_type.casefold():
            continue
        if candidate.asking_price.currency != subject.asking_price.currency:
            continue
        if candidate.living_area_sqm is None or candidate.asking_price.amount <= 0:
            continue
        seen_urls.add(url)
        if candidate.postal_code == subject.postal_code:
            postcode_rank = 0
        elif candidate.postal_code in nearby_rank:
            postcode_rank = nearby_rank[candidate.postal_code]
        else:
            postcode_rank = len(nearby_rank) + 1

        subject_area = subject.living_area_sqm or candidate.living_area_sqm
        area_gap = abs(candidate.living_area_sqm - subject_area) / subject_area
        room_gap = abs((candidate.room_count or 0) - (subject.room_count or 0))
        selected.append(((postcode_rank, area_gap + room_gap * 0.1, url), candidate))

    return [candidate for _, candidate in sorted(selected, key=lambda item: item[0])]


class InvestmentReasoner(Protocol):
    """Provider-neutral interface for qualitative investment judgment."""

    def judge(
        self,
        property_listing: PropertyListing,
        criteria: InvestmentCriteria,
        metrics: FinancialMetrics,
        valuation: MarketValuation | None = None,
    ) -> InvestmentJudgment: ...


class RuleBasedReasoner:
    """Deterministic default used for tests and development."""

    def judge(
        self,
        property_listing: PropertyListing,
        criteria: InvestmentCriteria,
        metrics: FinancialMetrics,
        valuation: MarketValuation | None = None,
    ) -> InvestmentJudgment:
        if valuation is None:
            return InvestmentJudgment(
                recommendation=AnalysisRecommendation.RESEARCH,
                thesis="A comparable-based market value estimate is required before judging.",
                risks=["No comparable market basis is attached to this deal."],
            )

        gap = valuation.value_gap
        strengths: list[str] = []
        if gap <= 0:
            strengths.append(
                f"The asking price is {gap:.1%} versus the comparable-based estimate."
            )
        risks = [
            "Operating costs and financing are not part of this analysis.",
            "Renting potential is evaluated in a later stage.",
        ]
        if gap > 0:
            risks.append(
                f"The asking price is {gap:+.1%} above the comparable-based estimate."
            )
        return InvestmentJudgment(
            recommendation=(
                AnalysisRecommendation.REVIEW
                if gap > SHORTLIST_MAX_GAP
                else AnalysisRecommendation.SHORTLIST
            ),
            thesis=(
                f"The comparable-based reference is {valuation.comp_eur_per_sqm:,.0f} "
                f"EUR/m² from {valuation.comp_count} comparable listings; the asking "
                f"price sits {gap:+.1%} relative to the estimated market value."
            ),
            strengths=strengths,
            risks=risks,
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
        valuation: MarketValuation | None = None,
    ) -> InvestmentJudgment:
        facts = {
            "property": property_listing.model_dump(mode="json"),
            "investment_criteria": criteria.model_dump(mode="json"),
            "calculated_metrics": metrics.model_dump(mode="json"),
            "market_valuation": (
                valuation.model_dump(mode="json") if valuation else None
            ),
        }
        result = self._structured_model.invoke(
            [
                SystemMessage(
                    content=(
                        "You are a cautious real-estate investment analyst. Evaluate only the "
                        "provided facts, calculated metrics, and comparable-based valuation. Never "
                        "recalculate or alter numeric metrics. Judge the price relative to the "
                        "estimated market value. Recommend reject, review, research, or shortlist. "
                        "Do not claim legal, tax, or financial certainty."
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


def _score_components(
    valuation: MarketValuation,
    property_listing: PropertyListing,
) -> dict[str, float]:
    """Deterministic score components; every number stays in Python."""

    value_gap_points = SCORE_WEIGHTS["value_gap"] * (
        1 - (valuation.value_gap + 0.25) / 0.5
    )
    value_gap_points = max(0.0, min(SCORE_WEIGHTS["value_gap"], value_gap_points))

    if valuation.comp_count >= 12:
        comp_points = 20.0
    elif valuation.comp_count >= 8:
        comp_points = 15.0
    elif valuation.comp_count >= 4:
        comp_points = 8.0
    else:
        comp_points = 3.0

    energy_points = _ENERGY_POINTS.get(property_listing.energy_class, 8.0)
    condition_bonus = _CONDITION_BONUS.get(property_listing.condition, 0.0)
    condition_energy = max(
        0.0, min(SCORE_WEIGHTS["condition_energy"], energy_points + condition_bonus)
    )

    missing_signals = sum(
        1
        for signal in (
            property_listing.build_year,
            property_listing.energy_class,
            property_listing.condition,
        )
        if signal is None
    )
    completeness = max(6.0, SCORE_WEIGHTS["data_completeness"] - 3.0 * missing_signals)

    return {
        "value_gap": round(value_gap_points, 2),
        "comp_confidence": round(comp_points, 2),
        "condition_energy": round(condition_energy, 2),
        "data_completeness": round(completeness, 2),
    }


def _analysis_confidence(
    property_listing: PropertyListing,
    valuation: MarketValuation | None,
    missing_critical_data: list[str],
) -> EvidenceConfidence:
    """Describe evidence quality without implying investment quality."""

    if missing_critical_data:
        labels = {
            "living_area_sqm": "living area",
            "market_basis": "local comparable-market evidence",
        }
        missing = ", ".join(labels.get(item, item.replace("_", " ")) for item in missing_critical_data)
        return EvidenceConfidence(
            level="low",
            reason=f"The analysis needs {missing} before a comparable-based value can be trusted.",
        )
    if valuation is None:
        return EvidenceConfidence(
            level="unknown",
            reason="No comparable-based valuation is available yet.",
        )
    if valuation.comp_count >= 8 and property_listing.annual_rent is not None:
        return EvidenceConfidence(
            level="high",
            reason="The estimate uses a broad comparable set and the listing includes annual rent evidence.",
        )
    if valuation.comp_count >= 4:
        return EvidenceConfidence(
            level="medium",
            reason="A comparable-based estimate is available, but some supporting evidence is limited.",
        )
    return EvidenceConfidence(
        level="low",
        reason="The estimate is based on a limited set of comparable listings.",
    )


def _score_drivers(
    property_listing: PropertyListing,
    valuation: MarketValuation,
    score_components: dict[str, float],
) -> list[ScoreDriver]:
    """Translate internal score components into five visible investor drivers."""

    rent_known = property_listing.annual_rent is not None
    building_fields = [property_listing.build_year, property_listing.energy_class, property_listing.condition]
    known_building_fields = sum(field is not None for field in building_fields)
    return [
        ScoreDriver(
            key="price_vs_market",
            label="Price versus market estimate",
            detail=f"The asking price is {valuation.value_gap:+.1%} versus the comparable-based estimate.",
            value=score_components["value_gap"],
            maximum=SCORE_WEIGHTS["value_gap"],
        ),
        ScoreDriver(
            key="comparable_evidence",
            label="Comparable evidence quality",
            detail=f"The estimate uses {valuation.comp_count} comparable listing{'s' if valuation.comp_count != 1 else ''}.",
            value=score_components["comp_confidence"],
            maximum=SCORE_WEIGHTS["comp_confidence"],
        ),
        ScoreDriver(
            key="rent_evidence",
            label="Rent evidence",
            detail=(
                "Annual rent is stated in the available evidence."
                if rent_known
                else "Annual rent is not stated, so yield cannot yet be verified."
            ),
            value=10.0 if rent_known else 0.0,
            maximum=10.0,
        ),
        ScoreDriver(
            key="building_energy_risk",
            label="Building and energy risk",
            detail=(
                f"{known_building_fields} of 3 building and energy facts are available."
                if known_building_fields
                else "Build year, condition, and energy class need confirmation."
            ),
            value=score_components["condition_energy"],
            maximum=SCORE_WEIGHTS["condition_energy"],
        ),
        ScoreDriver(
            key="data_completeness",
            label="Data completeness",
            detail="Missing facts reduce confidence and should be confirmed before progressing.",
            value=score_components["data_completeness"],
            maximum=SCORE_WEIGHTS["data_completeness"],
        ),
    ]


def analyse_property(
    property_listing: PropertyListing,
    criteria: InvestmentCriteria,
    reasoner: InvestmentReasoner,
    market_basis: MarketBasis | None = None,
) -> InvestmentAnalysis:
    """Estimate market value from comparables and route on the value gap.

    Python owns every number. Renting potential is intentionally deferred to a
    later stage: gross yield is computed only when verified rent exists, and it
    never drives routing. Missing living area or a missing market basis routes
    to research instead of producing an invented valuation.
    """

    price = property_listing.asking_price
    total_cost = Money(
        amount=round(price.amount * (1 + PURCHASE_COST_RATE), 2),
        currency=price.currency,
    )

    missing: list[str] = []
    if not property_listing.living_area_sqm:
        missing.append("living_area_sqm")
    if market_basis is None:
        missing.append("market_basis")
    if missing:
        return InvestmentAnalysis(
            metrics=FinancialMetrics(purchase_price=price, estimated_total_cost=total_cost),
            recommendation=AnalysisRecommendation.RESEARCH,
            thesis=(
                "A comparable-based market value estimate requires the living area "
                "and a local comparable-listing basis."
            ),
            assumptions=["Acquisition costs are estimated at 10% of purchase price."],
            risks=[
                "The market value cannot be estimated from the available evidence."
            ],
            missing_critical_data=missing,
            evidence=property_listing.evidence,
            confidence=_analysis_confidence(property_listing, None, missing),
        )

    bucket = next(
        (
            entry
            for entry in market_basis.by_condition
            if entry.condition == property_listing.condition
            and entry.comp_count >= MIN_CONDITION_COMPS
        ),
        None,
    )
    adjustments: dict[str, float] = {}
    if bucket is not None:
        comp_eur_per_sqm = bucket.eur_per_sqm
        comp_count = bucket.comp_count
    else:
        adjustment_factor = CONDITION_ADJUSTMENTS.get(property_listing.condition, 1.0)
        comp_eur_per_sqm = market_basis.overall_eur_per_sqm * adjustment_factor
        comp_count = market_basis.overall_comp_count
        if adjustment_factor != 1.0:
            adjustments["condition_fallback"] = adjustment_factor

    estimated_value = property_listing.living_area_sqm * comp_eur_per_sqm
    value_gap = (price.amount - estimated_value) / estimated_value
    valuation = MarketValuation(
        estimated_market_value=Money(
            amount=round(estimated_value, 2), currency=price.currency
        ),
        price_per_sqm=Money(
            amount=round(price.amount / property_listing.living_area_sqm, 2),
            currency=price.currency,
        ),
        comp_eur_per_sqm=round(comp_eur_per_sqm, 2),
        value_gap=round(value_gap, 4),
        comp_count=comp_count,
        condition=property_listing.condition,
        basis=(
            f"{market_basis.city}"
            f"{' ' + market_basis.postal_code if market_basis.postal_code else ''}"
            f" · {comp_count} comparable listings"
        ),
        adjustments=adjustments,
    )

    metrics = FinancialMetrics(purchase_price=price, estimated_total_cost=total_cost)
    if (
        property_listing.annual_rent is not None
        and property_listing.annual_rent.currency == price.currency
    ):
        metrics.annual_rent = property_listing.annual_rent
        metrics.gross_yield = property_listing.annual_rent.amount / price.amount

    judgment = reasoner.judge(property_listing, criteria, metrics, valuation)
    score_components = _score_components(valuation, property_listing)
    score = max(0, min(100, round(sum(score_components.values()))))

    if value_gap > REJECT_GAP_THRESHOLD:
        recommendation = AnalysisRecommendation.REJECT
    elif value_gap > SHORTLIST_MAX_GAP:
        recommendation = AnalysisRecommendation.REVIEW
    elif judgment.recommendation == AnalysisRecommendation.REJECT:
        recommendation = AnalysisRecommendation.REJECT
    elif judgment.recommendation == AnalysisRecommendation.RESEARCH:
        recommendation = AnalysisRecommendation.REVIEW
    else:
        recommendation = AnalysisRecommendation.SHORTLIST

    gap_percent = f"{value_gap:+.1%}"
    if value_gap > REJECT_GAP_THRESHOLD:
        value_context = (
            f"The asking price is {gap_percent} above the comparable-based market value."
        )
    elif value_gap > SHORTLIST_MAX_GAP:
        value_context = (
            f"The asking price is {gap_percent} above the comparable-based market "
            "value, which warrants human review."
        )
    else:
        value_context = (
            f"The asking price is {gap_percent} versus the comparable-based market value."
        )

    return InvestmentAnalysis(
        metrics=metrics,
        score=score,
        recommendation=recommendation,
        thesis=f"{value_context} {judgment.thesis}",
        assumptions=[
            "Acquisition costs are estimated at 10% of purchase price.",
            (
                "The estimated market value is the living area multiplied by the median "
                "price per square metre of comparable listings in the same area and "
                "condition bucket."
            ),
        ],
        strengths=judgment.strengths,
        risks=judgment.risks,
        evidence=property_listing.evidence,
        valuation=valuation,
        score_components=score_components,
        confidence=_analysis_confidence(property_listing, valuation, []),
        score_drivers=_score_drivers(property_listing, valuation, score_components),
    )

