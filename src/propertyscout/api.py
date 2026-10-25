"""Local HTTP API for starting, inspecting, and resuming durable deals."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from langchain_keenable import KeenableFetch, KeenableSearch
from langgraph.types import Command
from pydantic import BaseModel, Field, SecretStr

from propertyscout.analyst import (
    build_market_basis,
    create_nebius_reasoner,
    select_comparable_listings,
)
from propertyscout.bootstrap import initial_state, initial_state_for_listing
from propertyscout.config import (
    detail_fetch_limit_from_env,
    discovery_detail_fetch_budget_from_env,
    discovery_index_fetch_budget_from_env,
    discovery_search_budget_from_env,
    llm_enabled_from_env,
    search_query_limit_from_env,
)
from propertyscout.discovery import (
    DiscoveryRecord,
    DiscoveryService,
    write_csv,
)
from propertyscout.discovery_resume import ResumeError, read_inventory
from propertyscout.market_search import (
    KeenableListingSearchService,
    ListingSearchError,
    ListingSearchService,
    canonical_url,
)
from propertyscout.meeting_intelligence import create_nebius_meeting_brief_service
from propertyscout.persistence import (
    delete_sqlite_thread,
    list_sqlite_thread_ids,
    open_sqlite_graph,
)
from propertyscout.postcode_proximity import PostcodeCoordinateIndex
from propertyscout.schemas import (
    ComparableSelection,
    DiscoverySelectionContext,
    InvestmentCriteria,
    Money,
    PropertyCondition,
    PropertyListing,
)


class StartDealRequest(BaseModel):
    property_key: Literal["shortlist", "reject", "research"] = "shortlist"


class ResumeDealRequest(BaseModel):
    response: dict[str, Any] = Field(min_length=1)


class SearchRequest(BaseModel):
    city: str = Field(min_length=2)
    postal_code: str | None = Field(default=None, min_length=3, max_length=10)
    minimum_rooms: float | None = Field(default=None, gt=0)
    minimum_size_sqm: float | None = Field(default=None, gt=0)
    maximum_price: float = Field(gt=0)
    property_type: str = Field(min_length=2)
    currency: Literal["EUR"] = "EUR"
    minimum_gross_yield_percent: float | None = Field(default=None, ge=0, le=100)
    strategy: str = "buy_to_let"
    required_features: list[str] = Field(default_factory=list)
    excluded_features: list[str] = Field(default_factory=list)

    def criteria(self) -> InvestmentCriteria:
        return InvestmentCriteria(
            locations=[self.city.strip()],
            postal_codes=[self.postal_code.strip()] if self.postal_code else [],
            maximum_purchase_price=Money(
                amount=self.maximum_price,
                currency=self.currency,
            ),
            property_types=[self.property_type.strip()],
            minimum_gross_yield=(
                self.minimum_gross_yield_percent / 100
                if self.minimum_gross_yield_percent is not None
                else None
            ),
            minimum_living_area_sqm=self.minimum_size_sqm,
            minimum_room_count=self.minimum_rooms,
            strategy=self.strategy,
            required_features=self.required_features,
            excluded_features=self.excluded_features,
        )

class DealView(BaseModel):
    thread_id: str
    state: dict[str, Any]
    next_nodes: list[str]
    interrupts: list[Any]
    status: str
    pending_approval_type: str | None = None
    diagnostic: dict[str, Any] | None = None


class DiscoveryRecordView(BaseModel):
    """One discovered property row, mirroring the discovery CSV columns."""

    url: str
    portal: str
    portals: list[str] = Field(default_factory=list)
    title: str = ""
    city: str = ""
    postal_code: str | None = None
    price_eur: float | None = None
    area_m2: float | None = None
    rooms: float | None = None
    condition: str | None = None
    status: str
    matches_criteria: bool = False
    reasons: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    source_references: list[str] = Field(default_factory=list)
    possible_duplicates: list[str] = Field(default_factory=list)
    merged_from: list[str] = Field(default_factory=list)


class DiscoveryRunSummary(BaseModel):
    """Search diagnostics and per-status counts for one discovery run."""

    search_id: str
    created_at: str
    counts: dict[str, int] = Field(default_factory=dict)
    search_calls: int = 0
    index_fetches: int = 0
    detail_fetches: int = 0
    cross_query_duplicates: int = 0
    search_errors: list[str] = Field(default_factory=list)
    csv_path: str = ""


class DiscoveryRunView(DiscoveryRunSummary):
    """Full discovery run: diagnostics, counts, and every discovered record."""

    records: list[DiscoveryRecordView] = Field(default_factory=list)


class SearchView(BaseModel):
    search_id: str
    deals: list[DealView]
    discovery: DiscoveryRunSummary | None = None


class StartDiscoveryDealRequest(BaseModel):
    """Start an investment-analysis workflow for one selected discovery."""

    url: str = Field(min_length=8)
    criteria: SearchRequest | None = None


MIN_COMP_COUNT = 8
MAX_COMP_QUERIES = 3
NEARBY_POSTCODE_LIMIT = 5
NEARBY_POSTCODE_RADIUS_KM = 25.0


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


TERMINAL_OUTCOME_STATUS: dict[str, str] = {
    "brief_ready": "completed",
    "scout_rejected": "rejected",
    "analysis_rejected": "rejected",
    "shortlist_rejected": "rejected",
    "outreach_rejected": "rejected",
    # Contact research may fail without changing the investment decision.
    # Keep the deal actionable in the Contact tab rather than rejecting it.
    "contact_not_found": "needs_research",
    "contact_method_required": "needs_research",
    "broker_declined": "rejected",
    "schedule_rejected": "rejected",
    "outreach_revision_requested": "rejected",
    "needs_research": "needs_research",
    "awaiting_followup": "awaiting_followup",
}


def derive_workflow_status(
    state: dict[str, Any],
    interrupts: list[Any],
    next_nodes: list[str],
) -> tuple[str, str | None, dict[str, Any] | None]:
    """Classify one persisted deal snapshot for dashboard display.

    Returns ``(status, pending_approval_type, diagnostic)``. A pending interrupt
    always wins: a paused deal is waiting for a human even when its state
    contains historical error records. The ``failed`` stage is reserved for
    unrecoverable paths and is never derived from the append-only error
    history. Unknown terminal outcomes produce ``unknown`` plus a diagnostic
    payload so the dashboard can explain what it cannot classify.
    """

    if interrupts:
        first = interrupts[0] if isinstance(interrupts[0], dict) else {}
        pending_type = first.get("approval_type") or first.get("input_type")
        return "waiting_human", pending_type, None

    if state.get("current_stage") == "failed":
        return "failed", None, None

    if next_nodes:
        return "running", None, None

    outcome = state.get("outcome")
    if outcome is None:
        return (
            "failed",
            None,
            {
                "reason": "graph ended without an outcome",
                "current_stage": state.get("current_stage"),
                "next_nodes": list(next_nodes),
            },
        )

    mapped = TERMINAL_OUTCOME_STATUS.get(outcome)
    if mapped is not None:
        return mapped, None, None

    return (
        "unknown",
        None,
        {
            "reason": "outcome is not in the terminal-outcome map",
            "outcome": outcome,
            "current_stage": state.get("current_stage"),
            "next_nodes": list(next_nodes),
        },
    )


def _deal_view(graph, thread_id: str) -> DealView:
    snapshot = graph.get_state(_config(thread_id))
    if not snapshot.values:
        raise HTTPException(status_code=404, detail="Deal thread not found")
    interrupts = [
        interrupt.value
        for task in snapshot.tasks
        for interrupt in task.interrupts
    ]
    state = jsonable_encoder(snapshot.values)
    next_nodes = list(snapshot.next)
    encoded_interrupts = jsonable_encoder(interrupts)
    deal_status, pending_approval_type, diagnostic = derive_workflow_status(
        state,
        encoded_interrupts,
        next_nodes,
    )
    return DealView(
        thread_id=thread_id,
        state=state,
        next_nodes=next_nodes,
        interrupts=encoded_interrupts,
        status=deal_status,
        pending_approval_type=pending_approval_type,
        diagnostic=diagnostic,
    )


def create_app(
    database_path: str | Path = "data/propertyscout.sqlite",
    listing_search_service: ListingSearchService | None = None,
    discovery_service: DiscoveryService | None = None,
    comp_search_service: ListingSearchService | None = None,
    discovery_dir: str | Path = "data/discoveries",
    postcode_index: PostcodeCoordinateIndex | None = None,
    use_llm: bool | None = None,
) -> FastAPI:
    database_path = Path(database_path)
    discovery_dir = Path(discovery_dir)
    selected_listing_search = listing_search_service
    selected_comp_search = comp_search_service or KeenableListingSearchService(
        detail_fetch_limit=detail_fetch_limit_from_env(),
        search_query_limit=search_query_limit_from_env(),
    )
    if postcode_index is not None:
        resolved_postcode_index = postcode_index
    else:
        coordinate_path = (
            Path(__file__).resolve().parents[2] / "data" / "postcode_coordinates.csv"
        )
        resolved_postcode_index = (
            PostcodeCoordinateIndex.from_csv(coordinate_path)
            if coordinate_path.exists()
            else PostcodeCoordinateIndex.empty()
        )
    discovery_runs: dict[str, dict[str, Any]] = {}

    def _default_discovery_service() -> DiscoveryService:
        """Build the live discovery engine with the configured budgets.

        Constructed per search so a missing ``KEENABLE_API_KEY`` surfaces as a
        search error on the request instead of failing at application startup.
        """

        return DiscoveryService(
            search_client=KeenableSearch(timeout=30),
            fetch_client=KeenableFetch(api_key=SecretStr(""), timeout=30),
            search_budget=discovery_search_budget_from_env(),
            index_fetch_budget=discovery_index_fetch_budget_from_env(),
            detail_fetch_budget=discovery_detail_fetch_budget_from_env(),
        )

    def _status_counts(records: list[DiscoveryRecord]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in records:
            counts[record.status.value] = counts.get(record.status.value, 0) + 1
        return counts

    def _record_view(record: DiscoveryRecord) -> DiscoveryRecordView:
        return DiscoveryRecordView(
            url=record.url,
            portal=record.portal,
            portals=list(record.portals),
            title=record.title,
            city=record.city,
            postal_code=record.postal_code,
            price_eur=record.price_eur,
            area_m2=record.area_m2,
            rooms=record.rooms,
            condition=record.condition,
            status=record.status.value,
            matches_criteria=record.matches_criteria,
            reasons=list(record.reasons),
            missing=list(record.missing),
            source_references=list(record.source_references),
            possible_duplicates=list(record.possible_duplicates),
            merged_from=list(record.merged_from),
        )

    def _rehydrate_listing(
        record: DiscoveryRecord, criteria: InvestmentCriteria
    ) -> DiscoveryRecord:
        """Rebuild a complete listing from a persisted discovery CSV row.

        CSV history intentionally stores flat, reviewable columns rather than
        the nested domain object. A complete row has every field required to
        reconstruct the original listing using the search criteria that
        produced it.
        """

        if record.listing is not None or record.status.value != "complete":
            return record
        if not all(
            [
                record.url,
                record.title,
                record.city,
                record.price_eur is not None,
                record.area_m2 is not None,
                record.rooms is not None,
            ]
        ):
            return record
        try:
            condition = (
                PropertyCondition(record.condition) if record.condition else None
            )
            listing = PropertyListing(
                property_id=uuid5(NAMESPACE_URL, canonical_url(record.url)),
                source_listing_id=(
                    f"keenable-{uuid5(NAMESPACE_URL, canonical_url(record.url)).hex}"
                ),
                title=record.title,
                city=record.city,
                postal_code=record.postal_code,
                country_code="DE",
                property_type=criteria.property_types[0],
                asking_price=Money(amount=record.price_eur, currency="EUR"),
                living_area_sqm=record.area_m2,
                room_count=record.rooms,
                condition=condition,
                listing_url=record.url,
                missing_fields=record.missing,
            )
        except (TypeError, ValueError):
            return record
        return record.model_copy(update={"listing": listing})

    def _run_summary(search_id: str, entry: dict[str, Any]) -> DiscoveryRunSummary:
        diagnostics = entry["diagnostics"]
        return DiscoveryRunSummary(
            search_id=search_id,
            created_at=entry["created_at"],
            counts=_status_counts(entry["records"]),
            search_calls=diagnostics["search_calls"],
            index_fetches=diagnostics["index_fetches"],
            detail_fetches=diagnostics["detail_fetches"],
            cross_query_duplicates=diagnostics["cross_query_duplicates"],
            search_errors=list(diagnostics["search_errors"]),
            csv_path=str(entry["csv_path"]) if entry.get("csv_path") else "",
        )

    def _persist_run(search_id: str, entry: dict[str, Any]) -> Path:
        discovery_dir.mkdir(parents=True, exist_ok=True)
        path = discovery_dir / f"discovery_{search_id}.csv"
        write_csv(entry["records"], path)
        entry["csv_path"] = path
        return path

    def _hydrated_entry(path: Path) -> dict[str, Any]:
        return {
            "records": read_inventory(path),
            "criteria": None,
            "diagnostics": {
                "search_calls": 0,
                "index_fetches": 0,
                "detail_fetches": 0,
                "cross_query_duplicates": 0,
                "search_errors": [],
            },
            "created_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
            "csv_path": path,
        }

    def _load_run(search_id: str) -> dict[str, Any]:
        entry = discovery_runs.get(search_id)
        if entry is not None:
            return entry
        path = discovery_dir / f"discovery_{search_id}.csv"
        if not path.exists():
            raise HTTPException(status_code=404, detail="Discovery search not found")
        entry = _hydrated_entry(path)
        discovery_runs[search_id] = entry
        return entry

    def _safe_hydrate(path: Path) -> dict[str, Any] | None:
        """Parse a persisted discovery CSV; ``None`` for unreadable files."""

        try:
            return _hydrated_entry(path)
        except (ResumeError, OSError, ValueError):
            return None

    def _history() -> list[DiscoveryRunSummary]:
        summaries: list[DiscoveryRunSummary] = []
        seen: set[str] = set()
        for search_id, entry in discovery_runs.items():
            summaries.append(_run_summary(search_id, entry))
            seen.add(search_id)
        if discovery_dir.exists():
            persisted = sorted(
                discovery_dir.glob("discovery_*.csv"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            for path in persisted:
                search_id = path.stem.removeprefix("discovery_")
                if search_id in seen:
                    continue
                entry = _safe_hydrate(path)
                if entry is None:
                    continue
                discovery_runs[search_id] = entry
                summaries.append(_run_summary(search_id, entry))
        return summaries
    selected_use_llm = llm_enabled_from_env() if use_llm is None else use_llm
    graph_options = (
        {
            "reasoner": create_nebius_reasoner(),
            "meeting_brief_service": create_nebius_meeting_brief_service(),
        }
        if selected_use_llm
        else {}
    )
    application = FastAPI(
        title="PropertyScout AI",
        version="0.1.0",
        description="Local API for the durable six-agent acquisition workflow.",
    )
    ui_directory = Path(__file__).resolve().parents[2] / "sites" / "propertyscout-ui" / "dist"
    if ui_directory.exists():
        application.mount("/app", StaticFiles(directory=ui_directory, html=True), name="app")

        @application.get("/", include_in_schema=False)
        def ui_redirect() -> RedirectResponse:
            return RedirectResponse(url="/app/")

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post(
        "/deals",
        response_model=DealView,
        status_code=status.HTTP_201_CREATED,
    )
    def start_deal(request: StartDealRequest) -> DealView:
        thread_id = str(uuid4())
        with open_sqlite_graph(database_path, **graph_options) as graph:
            graph.invoke(initial_state(request.property_key), _config(thread_id))
            return _deal_view(graph, thread_id)

    @application.post(
        "/searches",
        response_model=SearchView,
        status_code=status.HTTP_201_CREATED,
    )
    def start_search(request: SearchRequest) -> SearchView:
        search_id = str(uuid4())
        criteria = request.criteria()
        if selected_listing_search is not None:
            return _legacy_search(search_id, criteria)
        return _discovery_search(search_id, criteria)

    def _legacy_search(search_id: str, criteria: InvestmentCriteria) -> SearchView:
        deal_views: list[DealView] = []
        try:
            listings = selected_listing_search.search(criteria)
        except (ListingSearchError, TimeoutError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        # One comparable basis serves every deal of this search. A failed comps
        # query is not fatal: deals then start without a basis and the analyst
        # routes them to research instead of inventing market numbers.
        try:
            comps = selected_listing_search.search_comps(
                criteria, MIN_COMP_COUNT, MAX_COMP_QUERIES
            )
        except (ListingSearchError, TimeoutError):
            comps = []
        subject_urls = {str(listing.listing_url) for listing in listings}
        market_basis = build_market_basis(comps, criteria, exclude_urls=subject_urls)

        with open_sqlite_graph(database_path, **graph_options) as graph:
            for index, property_listing in enumerate(listings, start=1):
                thread_id = f"{search_id}-{index}"
                graph.invoke(
                    initial_state_for_listing(property_listing, criteria, market_basis),
                    _config(thread_id),
                )
                deal_views.append(_deal_view(graph, thread_id))
        return SearchView(search_id=search_id, deals=deal_views)

    def _discovery_search(search_id: str, criteria: InvestmentCriteria) -> SearchView:
        service = discovery_service or _default_discovery_service()
        run = service.run(criteria)
        diagnostics = {
            "search_calls": run.search_calls,
            "index_fetches": run.index_fetches,
            "detail_fetches": run.detail_fetches,
            "cross_query_duplicates": run.cross_query_duplicates,
            "search_errors": list(run.search_errors),
        }
        if (
            run.search_calls
            and len(run.search_errors) == run.search_calls
            and not run.records
        ):
            raise HTTPException(
                status_code=502,
                detail="; ".join(run.search_errors) or "Keenable search failed",
            )
        entry: dict[str, Any] = {
            "records": run.records,
            "criteria": criteria,
            "diagnostics": diagnostics,
            "created_at": datetime.now(UTC).isoformat(),
            "csv_path": None,
        }
        entry["csv_path"] = _persist_run(search_id, entry)
        discovery_runs[search_id] = entry
        summary = _run_summary(search_id, entry)
        return SearchView(search_id=search_id, deals=[], discovery=summary)

    @application.get("/deals", response_model=list[DealView])
    def list_deals() -> list[DealView]:
        thread_ids = list_sqlite_thread_ids(database_path)
        if not thread_ids:
            return []
        with open_sqlite_graph(database_path, **graph_options) as graph:
            return [_deal_view(graph, thread_id) for thread_id in thread_ids]

    @application.get("/deals/{thread_id}", response_model=DealView)
    def get_deal(thread_id: str) -> DealView:
        with open_sqlite_graph(database_path, **graph_options) as graph:
            return _deal_view(graph, thread_id)

    @application.delete("/deals/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_deal(thread_id: str) -> Response:
        """Permanently remove one local deal from the pipeline."""

        if not delete_sqlite_thread(database_path, thread_id):
            raise HTTPException(status_code=404, detail="Deal thread not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.post("/deals/{thread_id}/resume", response_model=DealView)
    def resume_deal(thread_id: str, request: ResumeDealRequest) -> DealView:
        with open_sqlite_graph(database_path, **graph_options) as graph:
            current = _deal_view(graph, thread_id)
            if not current.interrupts:
                raise HTTPException(
                    status_code=409,
                    detail="Deal is not waiting for external input",
                )
            try:
                graph.invoke(Command(resume=request.response), _config(thread_id))
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            return _deal_view(graph, thread_id)

    @application.get("/discoveries", response_model=list[DiscoveryRunSummary])
    def list_discoveries() -> list[DiscoveryRunSummary]:
        return _history()

    @application.get("/discoveries/{search_id}", response_model=DiscoveryRunView)
    def get_discovery(search_id: str) -> DiscoveryRunView:
        entry = _load_run(search_id)
        summary = _run_summary(search_id, entry)
        return DiscoveryRunView(
            **summary.model_dump(),
            records=[_record_view(record) for record in entry["records"]],
        )

    @application.delete("/discoveries/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
    def clear_discovery(search_id: str) -> Response:
        """Remove one saved discovery inventory without changing any deals."""

        entry = _load_run(search_id)
        path = entry.get("csv_path")
        if path:
            csv_path = Path(path).resolve()
            if csv_path.parent != discovery_dir.resolve():
                raise HTTPException(status_code=400, detail="Invalid discovery inventory path")
            try:
                csv_path.unlink(missing_ok=True)
            except OSError as exc:
                raise HTTPException(
                    status_code=500, detail="Could not clear discovery inventory"
                ) from exc
        discovery_runs.pop(search_id, None)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.post(
        "/discoveries/{search_id}/deals",
        response_model=DealView,
        status_code=status.HTTP_201_CREATED,
    )
    def start_discovery_deal(
        search_id: str, request: StartDiscoveryDealRequest
    ) -> DealView:
        entry = _load_run(search_id)
        criteria = entry.get("criteria")
        if criteria is None and request.criteria is not None:
            criteria = request.criteria.criteria()
        if criteria is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "This discovery search predates criteria persistence; "
                    "pass the original search criteria to start analysis"
                ),
            )
        entry["records"] = [
            _rehydrate_listing(candidate, criteria) for candidate in entry["records"]
        ]
        target = canonical_url(request.url.strip())
        record = next(
            (
                candidate
                for candidate in entry["records"]
                if canonical_url(candidate.url) == target
            ),
            None,
        )
        if record is None:
            raise HTTPException(
                status_code=404,
                detail="Discovery record not found in this search",
            )
        if record.status.value != "complete" or record.listing is None:
            raise HTTPException(
                status_code=409,
                detail="Only complete listings can be selected for analysis",
            )

        validated_records = [
            candidate
            for candidate in entry["records"]
            if candidate.status.value == "complete" and candidate.listing is not None
        ]
        discovery_context = DiscoverySelectionContext(
            search_id=search_id,
            selected_listing_url=canonical_url(str(record.listing.listing_url)),
            selected_source_listing_id=record.listing.source_listing_id,
            validated_listings=[candidate.listing for candidate in validated_records],
            confirmed_duplicate_urls=sorted(
                {
                    merged_url
                    for candidate in validated_records
                    for merged_url in candidate.merged_from
                }
            ),
        )

        # The validated discovery run is the first comparable source. Its
        # records have already passed the provider-detail validation gates and
        # the selected subject plus confirmed duplicates are excluded here.
        # Existing comparable search remains a bounded fallback only when the
        # retained inventory cannot supply the target pool.
        comps = select_comparable_listings(
            record.listing,
            discovery_context.validated_listings,
            confirmed_duplicate_urls=set(discovery_context.confirmed_duplicate_urls),
        )
        nearby_postcodes = resolved_postcode_index.nearby_postcodes(
            record.listing.postal_code,
            maximum_distance_km=NEARBY_POSTCODE_RADIUS_KM,
            limit=NEARBY_POSTCODE_LIMIT,
        )
        expanded_listings = []
        searched_postcodes = []
        if len(comps) < MIN_COMP_COUNT:
            for nearby_postcode in nearby_postcodes:
                expansion_criteria = criteria.model_copy(
                    update={"postal_codes": [nearby_postcode]}
                )
                expansion_service = discovery_service or _default_discovery_service()
                try:
                    expansion_run = expansion_service.run(expansion_criteria)
                except Exception:  # noqa: BLE001 - external discovery is best effort
                    continue
                searched_postcodes.append(nearby_postcode)
                expanded_listings.extend(
                    candidate.listing
                    for candidate in expansion_run.records
                    if candidate.status.value == "complete" and candidate.listing is not None
                )
                comps = select_comparable_listings(
                    record.listing,
                    [*comps, *expanded_listings],
                    confirmed_duplicate_urls=set(
                        discovery_context.confirmed_duplicate_urls
                    ),
                    nearby_postcodes=nearby_postcodes,
                )
                if len(comps) >= MIN_COMP_COUNT:
                    break
        discovery_context = discovery_context.model_copy(
            update={
                "nearby_postcodes_considered": nearby_postcodes,
                "nearby_postcodes_searched": searched_postcodes,
                "expanded_discovery_listings": expanded_listings,
            }
        )
        if len(comps) < MIN_COMP_COUNT:
            try:
                fallback_comps = selected_comp_search.search_comps(
                    criteria, MIN_COMP_COUNT, MAX_COMP_QUERIES
                )
            except Exception:  # noqa: BLE001 - external search must not fail a deal
                fallback_comps = []
            comps = select_comparable_listings(
                record.listing,
                [*comps, *fallback_comps],
                confirmed_duplicate_urls=set(discovery_context.confirmed_duplicate_urls),
            )
        initial_urls = {
            str(listing.listing_url).rstrip("/")
            for listing in discovery_context.validated_listings
        }
        expanded_urls = {
            str(listing.listing_url).rstrip("/") for listing in expanded_listings
        }
        comparable_selections: list[ComparableSelection] = []
        for rank, comparable in enumerate(comps, start=1):
            comparable_url = str(comparable.listing_url).rstrip("/")
            if comparable_url in initial_urls:
                source = "validated_discovery_inventory"
            elif comparable_url in expanded_urls:
                source = "nearby_postcode_discovery"
            else:
                source = "fallback_comparable_search"
            distance_km = resolved_postcode_index.distance_between_postcodes(
                record.listing.postal_code, comparable.postal_code
            )
            if comparable.postal_code == record.listing.postal_code:
                location_reason = "same postcode"
            elif distance_km is not None:
                location_reason = f"{distance_km:.1f} km from subject postcode"
            else:
                location_reason = "postcode distance unavailable"
            comparable_selections.append(
                ComparableSelection(
                    listing=comparable,
                    source=source,
                    rank=rank,
                    postcode_distance_km=distance_km,
                    selection_reason=f"{source.replace('_', ' ')}; {location_reason}",
                )
            )
        market_basis = build_market_basis(
            comps,
            criteria,
            exclude_urls={str(record.listing.listing_url)},
        )
        thread_id = str(uuid4())
        with open_sqlite_graph(database_path, **graph_options) as graph:
            graph.invoke(
                initial_state_for_listing(
                    record.listing,
                    criteria,
                    market_basis,
                    discovery_context,
                    comparable_selections,
                ),
                _config(thread_id),
            )
            return _deal_view(graph, thread_id)

    return application


app = create_app(os.getenv("PROPERTYSCOUT_DB_PATH", "data/propertyscout.sqlite"))
