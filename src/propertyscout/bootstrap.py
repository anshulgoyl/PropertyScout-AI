"""Default fixture inputs used by the learning demo and local API."""

from __future__ import annotations

from uuid import uuid4

from propertyscout.fixtures import sample_properties
from propertyscout.schemas import (
    InvestmentCriteria,
    Money,
    PropertyListing,
    SchedulingPreferences,
    WorkflowStage,
)
from propertyscout.state import DealState


def default_criteria() -> InvestmentCriteria:
    return InvestmentCriteria(
        locations=["Cologne"],
        maximum_purchase_price=Money(amount=300_000, currency="EUR"),
        property_types=["apartment"],
        minimum_gross_yield=0.06,
        minimum_living_area_sqm=50,
        strategy="buy_to_let",
    )


def initial_state(
    property_key: str,
    criteria: InvestmentCriteria | None = None,
    scheduling_preferences: SchedulingPreferences | None = None,
    briefing_priorities: list[str] | None = None,
) -> DealState:
    return {
        "run_id": uuid4(),
        "criteria": criteria or default_criteria(),
        "property": sample_properties()[property_key],
        "current_stage": WorkflowStage.INITIALIZED,
        "audit_events": [],
        "errors": [],
        "scheduling_preferences": scheduling_preferences or SchedulingPreferences(),
        "briefing_priorities": briefing_priorities
        if briefing_priorities is not None
        else [
            "Confirm the current tenancy and lease terms.",
            "Ask whether major building works are planned.",
        ],
    }


def initial_state_for_listing(
    property_listing: PropertyListing,
    criteria: InvestmentCriteria,
) -> DealState:
    state = initial_state("shortlist", criteria=criteria)
    state["property"] = property_listing
    return state
