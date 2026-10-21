"""Local HTTP API for starting, inspecting, and resuming durable deals."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from langgraph.types import Command
from pydantic import BaseModel, Field

from propertyscout.analyst import create_nebius_reasoner
from propertyscout.bootstrap import initial_state, initial_state_for_listing
from propertyscout.config import llm_enabled_from_env
from propertyscout.market_search import (
    KeenableListingSearchService,
    ListingSearchError,
    ListingSearchService,
)
from propertyscout.meeting_intelligence import create_nebius_meeting_brief_service
from propertyscout.persistence import list_sqlite_thread_ids, open_sqlite_graph
from propertyscout.schemas import InvestmentCriteria, Money


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


class SearchView(BaseModel):
    search_id: str
    deals: list[DealView]


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _deal_view(graph, thread_id: str) -> DealView:
    snapshot = graph.get_state(_config(thread_id))
    if not snapshot.values:
        raise HTTPException(status_code=404, detail="Deal thread not found")
    interrupts = [
        interrupt.value
        for task in snapshot.tasks
        for interrupt in task.interrupts
    ]
    return DealView(
        thread_id=thread_id,
        state=jsonable_encoder(snapshot.values),
        next_nodes=list(snapshot.next),
        interrupts=jsonable_encoder(interrupts),
    )


def create_app(
    database_path: str | Path = "data/propertyscout.sqlite",
    listing_search_service: ListingSearchService | None = None,
    use_llm: bool | None = None,
) -> FastAPI:
    database_path = Path(database_path)
    selected_listing_search = listing_search_service or KeenableListingSearchService()
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
        deal_views: list[DealView] = []
        try:
            listings = selected_listing_search.search(criteria)
        except (ListingSearchError, TimeoutError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        with open_sqlite_graph(database_path, **graph_options) as graph:
            for index, property_listing in enumerate(listings, start=1):
                thread_id = f"{search_id}-{index}"
                graph.invoke(
                    initial_state_for_listing(property_listing, criteria),
                    _config(thread_id),
                )
                deal_views.append(_deal_view(graph, thread_id))
        return SearchView(search_id=search_id, deals=deal_views)

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

    return application


app = create_app(os.getenv("PROPERTYSCOUT_DB_PATH", "data/propertyscout.sqlite"))
