"""Broker-call briefing services for Meeting Intelligence."""

from __future__ import annotations

import json
from typing import Protocol

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from propertyscout.config import ModelSettings
from propertyscout.schemas import (
    InboundReply,
    InvestmentAnalysis,
    MeetingBrief,
    MeetingDetails,
    PropertyListing,
)


class MeetingBriefService(Protocol):
    """Provider-neutral boundary for producing a validated call brief."""

    def prepare(
        self,
        property_listing: PropertyListing,
        analysis: InvestmentAnalysis,
        meeting: MeetingDetails,
        reply: InboundReply,
        priorities: list[str],
    ) -> MeetingBrief: ...


class TemplateMeetingBriefService:
    """Deterministic default for local development and tests."""

    def prepare(
        self,
        property_listing: PropertyListing,
        analysis: InvestmentAnalysis,
        meeting: MeetingDetails,
        reply: InboundReply,
        priorities: list[str],
    ) -> MeetingBrief:
        metrics = analysis.metrics
        yield_summary = (
            f" Gross yield is {metrics.gross_yield:.2%}."
            if metrics.gross_yield is not None
            else " Gross yield is not yet available."
        )
        open_questions = list(priorities)
        if metrics.net_yield is None:
            open_questions.append(
                "What are the recurring service charges and non-recoverable operating costs?"
            )
        if metrics.monthly_cash_flow is None:
            open_questions.append(
                "What tenancy, vacancy, and financing facts are needed for cash-flow analysis?"
            )
        open_questions.extend(
            f"Can you clarify the missing field: {field}?"
            for field in analysis.missing_critical_data
        )

        return MeetingBrief(
            investment_summary=(
                f"{property_listing.title} in {property_listing.city} is listed at "
                f"{metrics.purchase_price.amount:,.0f} {metrics.purchase_price.currency}."
                f"{yield_summary} Analyst view: {analysis.thesis}"
            ),
            open_questions=list(dict.fromkeys(open_questions)),
            risks=analysis.risks,
            negotiation_points=[
                "Confirm the condition of the property and any deferred maintenance.",
                "Ask which documents and due-diligence records are immediately available.",
                "Clarify the seller's preferred timing and decision process.",
            ],
            evidence=analysis.evidence or property_listing.evidence,
        )


class LLMMeetingBriefService:
    """Structured briefing service backed by a compatible LangChain chat model."""

    def __init__(self, model: BaseChatModel) -> None:
        self._structured_model = model.with_structured_output(
            MeetingBrief,
            method="json_schema",
        )

    def prepare(
        self,
        property_listing: PropertyListing,
        analysis: InvestmentAnalysis,
        meeting: MeetingDetails,
        reply: InboundReply,
        priorities: list[str],
    ) -> MeetingBrief:
        facts = {
            "property": property_listing.model_dump(mode="json"),
            "validated_analysis": analysis.model_dump(mode="json"),
            "meeting": meeting.model_dump(mode="json"),
            "broker_reply": reply.model_dump(mode="json"),
            "investor_priorities": priorities,
        }
        result = self._structured_model.invoke(
            [
                SystemMessage(
                    content=(
                        "Prepare a concise broker-call brief using only the supplied facts. "
                        "Preserve calculated metrics exactly. Separate confirmed facts from open "
                        "questions, surface investment risks, and suggest non-binding negotiation "
                        "angles. Do not provide legal, tax, or financial advice."
                    )
                ),
                HumanMessage(content=json.dumps(facts, indent=2)),
            ]
        )
        if not isinstance(result, MeetingBrief):
            return MeetingBrief.model_validate(result)
        return result


def create_nebius_meeting_brief_service(
    settings: ModelSettings | None = None,
) -> LLMMeetingBriefService:
    settings = settings or ModelSettings.from_env()
    if settings.provider != "nebius":
        raise ValueError("Nebius meeting intelligence requires provider='nebius'")
    model = ChatOpenAI(
        model=settings.model,
        api_key=settings.api_key,
        base_url=settings.base_url,
        temperature=settings.temperature,
        max_retries=2,
    )
    return LLMMeetingBriefService(model)
