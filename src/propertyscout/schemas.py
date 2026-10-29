"""Validated domain objects shared by PropertyScout agents."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_serializer, model_validator


class StrictModel(BaseModel):
    """Base model that rejects undeclared fields in agent output."""

    model_config = ConfigDict(extra="forbid")


class WorkflowStage(StrEnum):
    INITIALIZED = "initialized"
    DISCOVERY = "discovery"
    ANALYSIS = "analysis"
    AWAITING_SHORTLIST_APPROVAL = "awaiting_shortlist_approval"
    CONTACT_RESEARCH = "contact_research"
    AWAITING_CONTACT_RESOLUTION = "awaiting_contact_resolution"
    OUTREACH_DRAFTING = "outreach_drafting"
    AWAITING_OUTREACH_APPROVAL = "awaiting_outreach_approval"
    AWAITING_REPLY = "awaiting_reply"
    SCHEDULING = "scheduling"
    MEETING_PREPARATION = "meeting_preparation"
    COMPLETE = "complete"
    FAILED = "failed"


class AnalysisRecommendation(StrEnum):
    REJECT = "reject"
    RESEARCH = "research"
    REVIEW = "review"
    SHORTLIST = "shortlist"


class WorkflowOutcome(StrEnum):
    SCOUT_REJECTED = "scout_rejected"
    ANALYSIS_REJECTED = "analysis_rejected"
    NEEDS_RESEARCH = "needs_research"
    SHORTLIST_APPROVED = "shortlist_approved"
    SHORTLIST_REJECTED = "shortlist_rejected"
    CONTACT_READY = "contact_ready"
    CONTACT_NOT_FOUND = "contact_not_found"
    CONTACT_METHOD_REQUIRED = "contact_method_required"
    OUTREACH_APPROVED = "outreach_approved"
    OUTREACH_REJECTED = "outreach_rejected"
    OUTREACH_REVISION_REQUESTED = "outreach_revision_requested"
    OUTREACH_SENT = "outreach_sent"
    BROKER_DECLINED = "broker_declined"
    AWAITING_FOLLOWUP = "awaiting_followup"
    SCHEDULE_REJECTED = "schedule_rejected"
    MEETING_SCHEDULED = "meeting_scheduled"
    BRIEF_READY = "brief_ready"


class ApprovalDecision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"


class ContactType(StrEnum):
    BROKER = "broker"
    SELLER = "seller"
    AGENCY = "agency"
    UNKNOWN = "unknown"


class ReplyIntent(StrEnum):
    PROPOSED_TIMES = "proposed_times"
    DECLINED = "declined"
    QUESTION = "question"
    OTHER = "other"


class PropertyCondition(StrEnum):
    RENOVATION_REQUIRED = "renovation_required"
    PARTIALLY_RENOVATED = "partially_renovated"
    RENOVATED = "renovated"
    WELL_MAINTAINED = "well_maintained"
    NEW_CONSTRUCTION = "new_construction"


class Money(StrictModel):
    amount: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3, examples=["EUR"])


class InvestmentCriteria(StrictModel):
    locations: list[str] = Field(min_length=1)
    postal_codes: list[str] = Field(default_factory=list)
    maximum_purchase_price: Money
    property_types: list[str] = Field(min_length=1)
    minimum_gross_yield: float | None = Field(default=None, ge=0, le=1)
    minimum_living_area_sqm: float | None = Field(default=None, gt=0)
    minimum_room_count: float | None = Field(default=None, gt=0)
    strategy: str = Field(min_length=1, examples=["buy_to_let"])
    required_features: list[str] = Field(default_factory=list)
    excluded_features: list[str] = Field(default_factory=list)
    risk_preferences: list[str] = Field(default_factory=list)


class SourceEvidence(StrictModel):
    source_name: str
    url: HttpUrl | None = None
    retrieved_at: datetime
    excerpt: str | None = None

    @field_serializer("url")
    def serialize_url(self, value: HttpUrl | None) -> str | None:
        return str(value) if value is not None else None


class PropertyListing(StrictModel):
    property_id: UUID
    source_listing_id: str
    title: str
    address: str | None = None
    city: str
    postal_code: str | None = None
    country_code: str = Field(min_length=2, max_length=2)
    property_type: str
    asking_price: Money
    living_area_sqm: float | None = Field(default=None, gt=0)
    room_count: float | None = Field(default=None, gt=0)
    annual_rent: Money | None = None
    description: str | None = None
    features: list[str] = Field(default_factory=list)
    build_year: int | None = Field(default=None, ge=1800, le=2100)
    energy_class: str | None = Field(default=None, min_length=1, max_length=4)
    condition: PropertyCondition | None = None
    listing_url: HttpUrl | None = None
    evidence: list[SourceEvidence] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)

    @field_serializer("listing_url")
    def serialize_listing_url(self, value: HttpUrl | None) -> str | None:
        return str(value) if value is not None else None


class DiscoverySelectionContext(StrictModel):
    """Validated discovery evidence retained when a listing becomes a deal.

    The inventory is deliberately stored before comparable selection so later
    agents can reuse the exact validated discovery run without re-querying a
    listing provider. ``confirmed_duplicate_urls`` records only URLs that the
    discovery pipeline merged on verified shared identifiers; possible
    cross-portal matches remain available on the discovery record and are not
    treated as exclusions.
    """

    search_id: str = Field(min_length=1)
    selected_listing_url: str = Field(min_length=8)
    selected_source_listing_id: str = Field(min_length=1)
    validated_listings: list[PropertyListing] = Field(default_factory=list)
    confirmed_duplicate_urls: list[str] = Field(default_factory=list)
    nearby_postcodes_considered: list[str] = Field(default_factory=list)
    nearby_postcodes_searched: list[str] = Field(default_factory=list)
    expanded_discovery_listings: list[PropertyListing] = Field(default_factory=list)


class ComparableSelection(StrictModel):
    """One traceable comparable selected for a deal's market basis."""

    listing: PropertyListing
    source: Literal[
        "validated_discovery_inventory",
        "nearby_postcode_discovery",
        "fallback_comparable_search",
        "pdf_import_comparable_search",
    ]
    rank: int = Field(ge=1)
    postcode_distance_km: float | None = Field(default=None, ge=0)
    selection_reason: str = Field(min_length=1)


class ScoutAssessment(StrictModel):
    matches_hard_criteria: bool
    reasons: list[str] = Field(default_factory=list)


class FinancialMetrics(StrictModel):
    purchase_price: Money
    estimated_total_cost: Money | None = None
    annual_rent: Money | None = None
    gross_yield: float | None = Field(default=None, ge=0, le=1)
    net_yield: float | None = Field(default=None, ge=-1, le=1)
    monthly_cash_flow: Money | None = None


class MarketValuation(StrictModel):
    """Deterministic value estimate derived from comparable listings.

    ``estimated_market_value`` is the living area multiplied by the adjusted
    comparable price per square metre. ``value_gap`` is the relative difference
    between the asking price and the estimate. Python owns every number; the
    LLM reasoner only receives these validated facts.
    """

    estimated_market_value: Money
    price_per_sqm: Money | None = None
    comp_eur_per_sqm: float = Field(gt=0)
    value_gap: float
    comp_count: int = Field(ge=1)
    condition: PropertyCondition | None = None
    basis: str
    adjustments: dict[str, float] = Field(default_factory=dict)


class ConditionAverage(StrictModel):
    """Median price per square metre for one condition bucket of comps."""

    condition: PropertyCondition
    eur_per_sqm: float = Field(gt=0)
    comp_count: int = Field(ge=0)
    source_urls: list[str] = Field(default_factory=list)


class MarketBasis(StrictModel):
    """Comparable-listing basis collected for one search area.

    Built once per user search from the discovery provider and attached to every
    deal thread of that search. Overall and per-condition medians give the
    Investment Analyst a local market reference with traceable sources.
    """

    city: str
    postal_code: str | None = None
    property_type: str
    overall_eur_per_sqm: float = Field(gt=0)
    overall_comp_count: int = Field(ge=0)
    by_condition: list[ConditionAverage] = Field(default_factory=list)
    retrieved_at: datetime
    source: str = "Keenable comparable-listing search"


class InvestmentJudgment(StrictModel):
    """Qualitative judgment produced by an analyst reasoner or LLM."""

    recommendation: AnalysisRecommendation
    thesis: str = Field(min_length=1)
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class InvestmentAnalysis(StrictModel):
    metrics: FinancialMetrics
    score: int | None = Field(default=None, ge=0, le=100)
    recommendation: AnalysisRecommendation
    thesis: str
    assumptions: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    missing_critical_data: list[str] = Field(default_factory=list)
    evidence: list[SourceEvidence] = Field(default_factory=list)
    valuation: MarketValuation | None = None
    score_components: dict[str, float] | None = None

    @model_validator(mode="after")
    def prevent_confident_result_with_missing_critical_data(self) -> InvestmentAnalysis:
        if self.missing_critical_data and self.recommendation == AnalysisRecommendation.SHORTLIST:
            raise ValueError("A property with missing critical data cannot be shortlisted")
        return self


class ContactCandidate(StrictModel):
    contact_id: UUID
    name: str
    organization: str | None = None
    contact_type: ContactType = ContactType.UNKNOWN
    email: str | None = None
    phone: str | None = None
    confidence: float = Field(ge=0, le=1)
    evidence: list[SourceEvidence] = Field(default_factory=list)


class OutreachDraft(StrictModel):
    recipient_contact_id: UUID
    recipient_email: str = Field(min_length=3)
    subject: str
    body: str
    requested_information: list[str] = Field(default_factory=list)


class EmailSendReceipt(StrictModel):
    provider_message_id: str
    idempotency_key: str
    recipient_email: str
    sent_at: datetime


class InboundReply(StrictModel):
    message_id: str
    sender_email: str
    received_at: datetime
    body: str = Field(min_length=1)
    proposed_times: list[datetime] = Field(default_factory=list)


class SchedulingPreferences(StrictModel):
    timezone: str = "Europe/Berlin"
    available_weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    available_start_hour: int = Field(default=9, ge=0, le=23)
    available_end_hour: int = Field(default=17, ge=1, le=24)
    meeting_duration_minutes: int = Field(default=30, gt=0, le=240)

    @model_validator(mode="after")
    def end_hour_must_follow_start_hour(self) -> SchedulingPreferences:
        if self.available_end_hour <= self.available_start_hour:
            raise ValueError("available_end_hour must be later than available_start_hour")
        return self


class ApprovalRecord(StrictModel):
    approval_type: str
    decision: ApprovalDecision = ApprovalDecision.PENDING
    decided_by: str | None = None
    decided_at: datetime | None = None
    feedback: str | None = None


class MeetingDetails(StrictModel):
    starts_at: datetime
    ends_at: datetime
    timezone: str
    attendee_emails: list[str] = Field(min_length=1)
    external_event_id: str | None = None

    @model_validator(mode="after")
    def end_must_follow_start(self) -> MeetingDetails:
        if self.ends_at <= self.starts_at:
            raise ValueError("Meeting end must be later than start")
        return self


class MeetingBrief(StrictModel):
    investment_summary: str
    open_questions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    negotiation_points: list[str] = Field(default_factory=list)
    evidence: list[SourceEvidence] = Field(default_factory=list)


class WorkflowError(StrictModel):
    node: str
    error_type: str
    message: str
    retryable: bool
    occurred_at: datetime
    details: dict[str, Any] = Field(default_factory=dict)


class AuditEvent(StrictModel):
    event_id: UUID
    occurred_at: datetime
    actor: str
    action: str
    details: dict[str, Any] = Field(default_factory=dict)
