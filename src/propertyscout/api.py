"""Local HTTP API for starting, inspecting, and resuming durable deals."""

from __future__ import annotations

import json
import os
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid4, uuid5
from xml.etree import ElementTree

from fastapi import FastAPI, File, HTTPException, Response, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from langchain_keenable import KeenableFetch, KeenableSearch
from langgraph.types import Command
from pydantic import BaseModel, Field, SecretStr
from pypdf import PdfReader

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
from propertyscout.contact_research import ListingPageContactResearchService, enrich_listing_features
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
    SourceEvidence,
)


MAX_PDF_IMPORT_KEENABLE_CREDITS = 10


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
    keenable_credits_used: int | None = None
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


def _document_text(path: Path) -> str:
    """Extract locally available text without sending a broker document elsewhere."""

    suffix = path.suffix.casefold()
    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        reader = PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix == ".docx":
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
        paragraphs = ["".join(paragraph.itertext()).strip() for paragraph in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p")]
        return "\n".join(paragraph for paragraph in paragraphs if paragraph)
    return ""


_PURCHASE_PRICE_LABEL = re.compile(
    r"(?:kaufpreis|kaufprice|purchase\s*price|asking\s*price)",
    re.IGNORECASE,
)
_PDF_MONEY_AMOUNT = re.compile(r"\b(?:\d{1,3}(?:[.\s]\d{3})+|\d{5,7})(?:,\d{2})?\b")


def _pdf_purchase_price(text: str) -> float | None:
    """Return the first plausible amount immediately following a price label.

    PDF text often places the total price beside a lower €/m² figure. Searching
    for a currency symbol across the complete document can therefore select the
    latter. Keep the match local to the explicit purchase-price label instead.
    """

    for label in _PURCHASE_PRICE_LABEL.finditer(text):
        window = text[label.end():label.end() + 180]
        for amount in _PDF_MONEY_AMOUNT.finditer(window):
            raw = amount.group(0).replace(" ", "")
            if "," in raw:
                raw = raw.replace(".", "").replace(",", ".")
            else:
                raw = raw.replace(".", "")
            value = float(raw)
            if 10_000 <= value <= 50_000_000:
                return value
    return None


def _document_facts(text: str) -> dict[str, Any]:
    """Read only plainly stated facts; uncertain matches remain absent."""

    compact = " ".join(text.split())
    facts: dict[str, Any] = {}
    price = _pdf_purchase_price(text)
    if price is not None:
        facts["price_eur"] = price
    area = re.search(r"(?:wohn(?:fläche)?|fläche|wohnraum)\D{0,20}([0-9]{1,4}(?:,[0-9]{1,2})?)\s*(?:m²|qm|m2)", compact, re.IGNORECASE)
    if area:
        facts["area_sqm"] = float(area.group(1).replace(",", "."))
    energy = re.search(r"(?:energie(?:ausweis|effizienzklasse|klasse)?)\D{0,24}\b([A-G])\b", compact, re.IGNORECASE)
    if energy:
        facts["energy_class"] = energy.group(1).upper()
    rent = re.search(r"(?:kaltmiete|nettokaltmiete)\D{0,24}([0-9][0-9. ]{1,}(?:,[0-9]{2})?)\s*(?:€|eur)", compact, re.IGNORECASE)
    if rent:
        facts["monthly_rent_eur"] = float(rent.group(1).replace(".", "").replace(" ", "").replace(",", "."))
    return facts


def _pdf_import_listing(text: str, filename: str) -> PropertyListing:
    """Build a cautious analysis candidate from plainly stated PDF facts."""

    compact = " ".join(text.split())
    facts = _document_facts(text)
    if "price_eur" not in facts:
        raise HTTPException(
            status_code=422,
            detail="The PDF needs a clearly stated purchase price before it can enter Analyze.",
        )
    rooms = re.search(r"\b(\d+(?:[,.]\d+)?)\s*(?:zimmer|rooms?)\b", compact, re.IGNORECASE)
    area = re.search(r"\b(\d+(?:[,.]\d+)?)\s*(?:m²|m2|qm)\b", compact, re.IGNORECASE)
    postcode = re.search(r"\b(\d{5})\b", compact)
    city = re.search(r"\b(Köln|Koeln|Cologne|Düsseldorf|Duesseldorf|Dusseldorf|Essen|München|Muenchen|Munich)\b", compact, re.IGNORECASE)
    url = re.search(r"https?://[^\s<>()]+", text)
    first_line = next((line.strip() for line in text.splitlines() if len(line.strip()) > 12), "")
    title = first_line[:160] or Path(filename).stem.replace("_", " ")
    property_type = "house" if re.search(r"\bhaus\b|\bhouse\b", compact, re.IGNORECASE) else "apartment"
    return PropertyListing(
        property_id=uuid4(),
        source_listing_id=f"pdf-import-{uuid4().hex}",
        title=title,
        city=city.group(1) if city else "Location to confirm",
        postal_code=postcode.group(1) if postcode else None,
        country_code="DE",
        property_type=property_type,
        asking_price=Money(amount=facts["price_eur"], currency="EUR"),
        living_area_sqm=float(area.group(1).replace(",", ".")) if area else None,
        room_count=float(rooms.group(1).replace(",", ".")) if rooms else None,
        annual_rent=Money(amount=facts["monthly_rent_eur"] * 12, currency="EUR") if "monthly_rent_eur" in facts else None,
        energy_class=facts.get("energy_class"),
        description=compact[:4_000],
        listing_url=url.group(0).rstrip(".,;") if url else None,
        evidence=[
            SourceEvidence(
                source_name="uploaded property PDF",
                retrieved_at=datetime.now(UTC),
                excerpt=compact[:30_000],
            )
        ],
        missing_fields=[field for field, value in (("living area", area), ("rooms", rooms), ("location", city)) if not value],
    )


def _contract_checklist(text: str) -> list[dict[str, str]]:
    topics = [
        ("Property and fixtures", "Ensure the unit, parking/storage rights, and included fixtures are described precisely.", r"(?:wohnung|grundbuch|inventar|stellplatz)"),
        ("Known defects", "Ask that known defects, repairs, and agreed remedies are written down.", r"(?:mangel|gewährleistung|sachmangel)"),
        ("Payment and handover", "Confirm payment prerequisites, keys, handover date, and risk transfer.", r"(?:kaufpreis|übergabe|besitzübergang)"),
        ("Land register and encumbrances", "Clarify which liens, easements, or rights must be removed or remain.", r"(?:grundbuch|lastenfreistellung|dienstbarkeit)"),
        ("Owners' association", "Check Hausgeld, reserves, planned works, special assessments, and recent minutes.", r"(?:hausgeld|sonderumlage|eigentümerversammlung|instandhaltungsrücklage)"),
        ("Letting and tenancy", "If occupied, confirm the lease, deposit, rent, and termination constraints.", r"(?:mietvertrag|kaltmiete|mieter|kaution)"),
        ("Financing condition", "If required, have a financing condition or clear exit arrangement reviewed before signing.", r"(?:finanzierung|darlehen)"),
    ]
    return [
        {"topic": topic, "guidance": guidance, "status": "mentioned" if re.search(pattern, text, re.IGNORECASE) else "check"}
        for topic, guidance, pattern in topics
    ]


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
        # Each Keenable search or fetch consumes one request credit. Keep the
        # total with the run so the user can audit it after a restart.
        credits_used = (
            diagnostics["search_calls"]
            + diagnostics["index_fetches"]
            + diagnostics["detail_fetches"]
        ) if entry.get("usage_recorded") else None
        return DiscoveryRunSummary(
            search_id=search_id,
            created_at=entry["created_at"],
            counts=_status_counts(entry["records"]),
            search_calls=diagnostics["search_calls"],
            index_fetches=diagnostics["index_fetches"],
            detail_fetches=diagnostics["detail_fetches"],
            keenable_credits_used=credits_used,
            cross_query_duplicates=diagnostics["cross_query_duplicates"],
            search_errors=list(diagnostics["search_errors"]),
            csv_path=str(entry["csv_path"]) if entry.get("csv_path") else "",
        )

    def _persist_run(search_id: str, entry: dict[str, Any]) -> Path:
        discovery_dir.mkdir(parents=True, exist_ok=True)
        path = discovery_dir / f"discovery_{search_id}.csv"
        write_csv(entry["records"], path)
        entry["csv_path"] = path
        path.with_suffix(".meta.json").write_text(
            json.dumps(
                {
                    "created_at": entry["created_at"],
                    "diagnostics": entry["diagnostics"],
                    "usage_recorded": True,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return path

    def _hydrated_entry(path: Path) -> dict[str, Any]:
        diagnostics = {
            "search_calls": 0,
            "index_fetches": 0,
            "detail_fetches": 0,
            "cross_query_duplicates": 0,
            "search_errors": [],
        }
        created_at = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
        usage_recorded = False
        try:
            metadata = json.loads(
                path.with_suffix(".meta.json").read_text(encoding="utf-8")
            )
            stored_diagnostics = metadata.get("diagnostics", {})
            diagnostics.update(
                {
                    key: stored_diagnostics.get(key, default)
                    for key, default in diagnostics.items()
                }
            )
            created_at = metadata.get("created_at", created_at)
            usage_recorded = bool(metadata.get("usage_recorded", False))
        except (OSError, TypeError, ValueError):
            # Older inventories do not have usage metadata, so avoid guessing.
            pass
        return {
            "records": read_inventory(path),
            "criteria": None,
            "diagnostics": diagnostics,
            "usage_recorded": usage_recorded,
            "created_at": created_at,
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
        "/deals/import-pdf",
        response_model=DealView,
        status_code=status.HTTP_201_CREATED,
    )
    async def import_property_pdf(file: UploadFile = File(...)) -> DealView:
        """Add a PDF exposé to Analyze and enrich it with tightly bounded web evidence."""

        filename = Path(file.filename or "property.pdf").name
        if Path(filename).suffix.casefold() != ".pdf":
            raise HTTPException(status_code=415, detail="Upload a PDF property exposé.")
        payload = await file.read()
        if not payload or len(payload) > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="The PDF must be between 1 byte and 20 MB.")

        import_path = database_path.parent / "pdf-imports" / f"{uuid4()}-{filename}"
        import_path.parent.mkdir(parents=True, exist_ok=True)
        import_path.write_bytes(payload)
        try:
            text = _document_text(import_path)
        except Exception as exc:  # noqa: BLE001 - malformed PDFs are user-facing input errors
            raise HTTPException(status_code=422, detail=f"Could not read this PDF: {exc}") from exc
        if not text.strip():
            raise HTTPException(status_code=422, detail="No readable text was found in this PDF.")

        property_listing = _pdf_import_listing(text, filename)
        online_evidence: list[SourceEvidence] = []
        online_text = ""
        calls = 0
        try:
            listing_url = str(property_listing.listing_url or "")
            if listing_url:
                calls += 1
                fetched = KeenableFetch(api_key=SecretStr(""), timeout=30).invoke({"url": listing_url})
                online_text = str(fetched.get("content") or "") if isinstance(fetched, dict) else str(fetched)
                if online_text:
                    online_evidence.append(SourceEvidence(source_name="Keenable PDF-import listing fetch", url=listing_url, retrieved_at=datetime.now(UTC), excerpt=online_text[:30_000]))
            else:
                calls += 1
                query = f"{property_listing.title} {property_listing.city} kaufen immobilie"
                results = KeenableSearch(timeout=30).invoke({"query": query})
                candidate = next((item for item in results if isinstance(item, dict)), None) if isinstance(results, list) else None
                if candidate:
                    snippet = str(candidate.get("snippet") or candidate.get("description") or "")
                    candidate_url = str(candidate.get("url") or "")
                    online_text = snippet
                    if snippet:
                        online_evidence.append(SourceEvidence(source_name="Keenable PDF-import search", url=candidate_url or None, retrieved_at=datetime.now(UTC), excerpt=snippet[:10_000]))
                    if candidate_url and calls < MAX_PDF_IMPORT_KEENABLE_CREDITS:
                        calls += 1
                        fetched = KeenableFetch(api_key=SecretStr(""), timeout=30).invoke({"url": candidate_url})
                        detail = str(fetched.get("content") or "") if isinstance(fetched, dict) else str(fetched)
                        if detail:
                            online_text = f"{online_text}\n{detail}"
                            online_evidence.append(SourceEvidence(source_name="Keenable PDF-import listing fetch", url=candidate_url, retrieved_at=datetime.now(UTC), excerpt=detail[:30_000]))
        except Exception:
            # Online research is helpful but must never prevent a local PDF from entering Analyze.
            pass

        if online_text:
            property_listing = enrich_listing_features(property_listing, online_text)
        property_listing = property_listing.model_copy(update={"evidence": [*property_listing.evidence, *online_evidence]})
        criteria = InvestmentCriteria(
            locations=[property_listing.city],
            postal_codes=[property_listing.postal_code] if property_listing.postal_code else [],
            maximum_purchase_price=Money(amount=property_listing.asking_price.amount * 1.2, currency="EUR"),
            property_types=[property_listing.property_type],
            strategy="buy_to_let",
        )
        # A PDF-imported property has no discovery inventory to reuse. Build a
        # comparable pool with a dedicated, hard-capped service: at most three
        # search calls and four detail fetches. Together with the two-call PDF
        # research above, this stays below the ten-credit import budget.
        comparable_selections: list[ComparableSelection] = []
        market_basis = None
        can_search_comparables = (
            property_listing.city != "Location to confirm"
            and property_listing.living_area_sqm is not None
            and property_listing.room_count is not None
        )
        if can_search_comparables:
            try:
                pdf_comparable_search = KeenableListingSearchService(
                    detail_fetch_limit=4,
                    search_query_limit=3,
                )
                comparables = pdf_comparable_search.search_comps(
                    criteria, MIN_COMP_COUNT, MAX_COMP_QUERIES
                )
                market_basis = build_market_basis(
                    comparables,
                    criteria,
                    exclude_urls={str(property_listing.listing_url)} if property_listing.listing_url else set(),
                )
                comparable_selections = [
                    ComparableSelection(
                        listing=comparable,
                        source="pdf_import_comparable_search",
                        rank=rank,
                        selection_reason="Comparable found for PDF-imported property",
                    )
                    for rank, comparable in enumerate(comparables, start=1)
                ]
            except Exception:
                # The document is still useful even when a market search is not.
                comparable_selections = []
                market_basis = None
        thread_id = str(uuid4())
        document_target = database_path.parent / "documents" / thread_id
        document_target.mkdir(parents=True, exist_ok=True)
        (document_target / filename).write_bytes(payload)
        with open_sqlite_graph(database_path, **graph_options) as graph:
            graph.invoke(
                initial_state_for_listing(
                    property_listing,
                    criteria,
                    market_basis=market_basis,
                    comparable_selections=comparable_selections,
                ),
                _config(thread_id),
            )
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
            "usage_recorded": True,
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

    @application.post("/deals/{thread_id}/enrich-contact", response_model=DealView)
    def enrich_contact_listing(thread_id: str) -> DealView:
        """Fetch one selected listing page for richer contact and feature evidence.

        This endpoint is deliberately user-triggered and records its completion,
        so refreshes cannot spend additional Keyless credits. One detail fetch is
        used (well below the five-credit per-listing limit).
        """

        with open_sqlite_graph(database_path, **graph_options) as graph:
            snapshot = graph.get_state(_config(thread_id))
            if not snapshot.values:
                raise HTTPException(status_code=404, detail="Deal thread not found")
            property_listing: PropertyListing = snapshot.values["property"]
            saved_enrichment = [
                item for item in property_listing.evidence
                if item.source_name == "keyless_contact_enrichment" and item.excerpt
            ]
            if saved_enrichment:
                # Older one-time refreshes already have the page text. Normalize
                # those facts locally rather than spending another provider credit.
                normalized = enrich_listing_features(
                    property_listing,
                    "\n".join(str(item.excerpt) for item in saved_enrichment),
                )
                if normalized != property_listing:
                    graph.update_state(_config(thread_id), {"property": normalized})
                return _deal_view(graph, thread_id)
            if not property_listing.listing_url:
                raise HTTPException(status_code=422, detail="This listing has no source URL to enrich")
            try:
                result = KeenableFetch(api_key=SecretStr(""), timeout=30).invoke({"url": str(property_listing.listing_url)})
            except Exception as exc:  # noqa: BLE001 - provider error is reported to the user
                raise HTTPException(status_code=502, detail=f"Listing enrichment failed: {exc}") from exc
            content = result.get("content") if isinstance(result, dict) else str(result)
            if not content:
                raise HTTPException(status_code=502, detail="Listing enrichment returned no readable content")
            evidence = SourceEvidence(
                source_name="keyless_contact_enrichment",
                url=property_listing.listing_url,
                retrieved_at=datetime.now(UTC),
                excerpt=str(content)[:30000],
            )
            enriched_property = enrich_listing_features(property_listing, str(content)).model_copy(
                update={"evidence": [*property_listing.evidence, evidence]}
            )
            updates: dict[str, Any] = {"property": enriched_property}
            candidates = ListingPageContactResearchService().search(enriched_property)
            if candidates:
                updates["contact_candidates"] = candidates
                updates["selected_contact"] = candidates[0]
            graph.update_state(_config(thread_id), updates)
            return _deal_view(graph, thread_id)

    @application.post("/deals/{thread_id}/contact-pdf", response_model=DealView)
    async def enrich_contact_from_pdf(thread_id: str, file: UploadFile = File(...)) -> DealView:
        """Use a broker/exposé PDF as local evidence for one Contact-stage deal."""

        filename = Path(file.filename or "contact-document.pdf").name
        if Path(filename).suffix.casefold() != ".pdf":
            raise HTTPException(status_code=415, detail="Upload a PDF document.")
        payload = await file.read()
        if not payload or len(payload) > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="The PDF must be between 1 byte and 20 MB.")
        with open_sqlite_graph(database_path, **graph_options) as graph:
            snapshot = graph.get_state(_config(thread_id))
            if not snapshot.values:
                raise HTTPException(status_code=404, detail="Deal thread not found")
            property_listing: PropertyListing = snapshot.values["property"]
            target = database_path.parent / "documents" / thread_id
            target.mkdir(parents=True, exist_ok=True)
            path = target / filename
            path.write_bytes(payload)
            try:
                text = _document_text(path)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=422, detail=f"Could not read this PDF: {exc}") from exc
            if not text.strip():
                raise HTTPException(status_code=422, detail="No readable text was found in this PDF.")
            evidence = SourceEvidence(
                source_name="uploaded contact PDF",
                url=property_listing.listing_url,
                retrieved_at=datetime.now(UTC),
                excerpt=text[:30_000],
            )
            enriched = enrich_listing_features(property_listing, text).model_copy(
                update={"evidence": [*property_listing.evidence, evidence]}
            )
            updates: dict[str, Any] = {"property": enriched}
            candidates = ListingPageContactResearchService().search(enriched)
            if candidates:
                updates["contact_candidates"] = candidates
                updates["selected_contact"] = candidates[0]
            graph.update_state(_config(thread_id), updates)
            return _deal_view(graph, thread_id)

    @application.delete("/deals/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_deal(thread_id: str) -> Response:
        """Permanently remove one local deal from the pipeline."""

        if not delete_sqlite_thread(database_path, thread_id):
            raise HTTPException(status_code=404, detail="Deal thread not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.post("/deals/{thread_id}/documents")
    async def upload_deal_documents(
        thread_id: str, files: list[UploadFile] = File(...),
    ) -> dict[str, list[dict[str, str | int]]]:
        """Store broker documents locally for a single deal; analysis is separate."""

        if not list_sqlite_thread_ids(database_path) or thread_id not in list_sqlite_thread_ids(database_path):
            raise HTTPException(status_code=404, detail="Deal not found")
        allowed = {".pdf", ".doc", ".docx", ".txt", ".jpg", ".jpeg", ".png"}
        target = database_path.parent / "documents" / thread_id
        target.mkdir(parents=True, exist_ok=True)
        saved: list[dict[str, str | int]] = []
        for upload in files[:10]:
            name = Path(upload.filename or "document").name
            if Path(name).suffix.casefold() not in allowed:
                raise HTTPException(status_code=415, detail=f"Unsupported file: {name}")
            content = await upload.read()
            if len(content) > 20 * 1024 * 1024:
                raise HTTPException(status_code=413, detail=f"File is larger than 20 MB: {name}")
            (target / name).write_bytes(content)
            saved.append({"name": name, "bytes": len(content)})
        return {"files": saved}

    @application.get("/deals/{thread_id}/documents")
    def list_deal_documents(thread_id: str) -> dict[str, list[dict[str, str | int]]]:
        target = database_path.parent / "documents" / thread_id
        if not target.exists():
            return {"files": []}
        return {"files": [{"name": path.name, "bytes": path.stat().st_size} for path in sorted(target.iterdir()) if path.is_file()]}

    @application.get("/deals/{thread_id}/documents/{name}/text")
    def document_text(thread_id: str, name: str) -> dict[str, str]:
        path = database_path.parent / "documents" / thread_id / Path(name).name
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Document not found")
        text = _document_text(path)
        if text:
            return {"text": text}
        return {"text": "No embedded text was found. This appears to be a scan or image; local OCR can be enabled on this machine."}

    @application.get("/deals/{thread_id}/documents/review")
    def review_deal_documents(thread_id: str) -> dict[str, Any]:
        """Compare plainly stated local document facts with the saved listing."""

        target = database_path.parent / "documents" / thread_id
        if not target.exists():
            raise HTTPException(status_code=404, detail="No documents uploaded for this deal")
        with open_sqlite_graph(database_path, **graph_options) as graph:
            deal = _deal_view(graph, thread_id)
        listing = deal.state.get("property") or {}
        expected = {
            "price_eur": listing.get("asking_price", {}).get("amount") if isinstance(listing.get("asking_price"), dict) else listing.get("asking_price"),
            "area_sqm": listing.get("living_area_sqm"),
            "energy_class": listing.get("energy_class"),
        }
        extracted: list[dict[str, Any]] = []
        for path in sorted(candidate for candidate in target.iterdir() if candidate.is_file()):
            text = _document_text(path)
            extracted.append({"name": path.name, "facts": _document_facts(text), "has_text": bool(text)})

        discrepancies: list[dict[str, str]] = []
        for document in extracted:
            for field, document_value in document["facts"].items():
                listing_value = expected.get(field)
                if listing_value in (None, "", "not stated"):
                    continue
                if field in {"price_eur", "area_sqm"}:
                    if abs(float(document_value) - float(listing_value)) > (1 if field == "area_sqm" else 100):
                        discrepancies.append({"document": document["name"], "field": field.replace("_", " "), "listing": str(listing_value), "document_value": str(document_value)})
                elif str(document_value).upper() != str(listing_value).upper():
                    discrepancies.append({"document": document["name"], "field": field.replace("_", " "), "listing": str(listing_value), "document_value": str(document_value)})
        joined_text = "\n".join(_document_text(path) for path in target.iterdir() if path.is_file())
        return {
            "documents": extracted,
            "discrepancies": discrepancies,
            "contract_checklist": _contract_checklist(joined_text),
            "notice": "This is a practical review aid, not legal advice. Have the notarial contract reviewed by a qualified professional before signing.",
        }

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
                csv_path.with_suffix(".meta.json").unlink(missing_ok=True)
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
