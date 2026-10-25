"""Standalone Keenable property discovery pipeline with CSV output.

Runs entirely outside the LangGraph workflow: one authenticated Keenable
search per configured query variant, keyless page fetches for index pages
and individual listings, conservative deduplication, validation against the
same discovery gates as :mod:`propertyscout.market_search`, and a CSV report.

Constraints enforced here:

- Live search requires ``KEENABLE_API_KEY``; keyless search fallback is
  disabled deliberately. Page fetches always use the keyless public endpoint.
- Hard request budgets with no automatic retries and no early stopping of
  the configured search queries.
- Attributes are never combined across properties: index pages are only
  link sources, and per-portal "other listings" page sections are trimmed
  before parsing a detail page.
- Cross-portal records are merged only on verified shared listing
  identifiers (explicit expose/source references); otherwise similar
  records from different portals are merely flagged as possible duplicates.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote, urljoin, urlsplit
from uuid import NAMESPACE_URL, uuid5

from langchain_keenable import KeenableFetch, KeenableSearch
from pydantic import Field, SecretStr

from propertyscout.market_search import (
    _AREA,
    _BUILD_YEAR,
    _ENERGY_CLASS,
    _FEATURE_TERMS,
    _POSTAL_CODE,
    _ROOMS,
    _property_content_only,
    canonical_url,
    city_aliases,
    eur_price_values,
    extract_condition,
    is_complete_listing,
    merge_page_listing,
    normalize_search_result,
    purchase_price_value,
    rejection_reasons,
    search_queries,
)
from propertyscout.schemas import (
    InvestmentCriteria,
    Money,
    PropertyListing,
    SourceEvidence,
    StrictModel,
)

DEFAULT_SEARCH_BUDGET = 10
DEFAULT_INDEX_FETCH_BUDGET = 10
DEFAULT_DETAIL_FETCH_BUDGET = 20

_IMMOWELT_EXPOSE = re.compile(r"immowelt\.de/expose/[0-9a-fA-F][0-9a-fA-F-]{9,}")
_REGIONAL_EXPOSE = re.compile(
    r"regionalimmobilien24\.de/immobilien/expose/\?id=\d+"
)
# Explicit source references: expose URLs of syndication providers. Only
# such verified identifiers justify merging cross-portal records.
_EXPOSE_REFERENCE = re.compile(
    r"https?://[^\s)\]\"']+(?:"
    + _IMMOWELT_EXPOSE.pattern
    + r"|"
    + _REGIONAL_EXPOSE.pattern
    + r")"
)
_KLEINANZEIGEN_LISTING = re.compile(r"^/s-anzeige/.*\d{9,}")
_IMMOBILIEN_LISTING = re.compile(r"^/immobilien/.*-[HG][A-Z0-9]{4,8}$")
_IMMWELT_LISTING = re.compile(r"^/expose/[0-9a-fA-F-]{10,}$")
_IMMOSCOUT_LISTING = re.compile(r"^/expose/\d{6,}")
_LISTING_PATHS = (
    _KLEINANZEIGEN_LISTING,
    _IMMOBILIEN_LISTING,
    _IMMWELT_LISTING,
    _IMMOSCOUT_LISTING,
)
_MARKDOWN_LINK = re.compile(r"\]\(([^)\s]+)\)")
_ROOMS_AFTER = re.compile(
    r"\b(?:Zi\.?|Zimmer)\s*[:\-]?\s*(?P<value>\d+(?:[,.]\d+)?)",
    re.IGNORECASE,
)
# Sections of a detail page that list *other* properties. Everything from
# the earliest marker onward belongs to different properties and must not
# contribute attributes to the parsed listing.
_OTHER_LISTING_MARKERS = (
    "Andere Anzeigen des Anbieters",
    "Das könnte dich auch interessieren",
    "Ähnliche Suchanfragen",
    "Ähnliche Immobilien",
    "Weitere Immobilien",
    "Similar listings",
)
_PORTAL_BY_HOST = {
    "kleinanzeigen.de": "kleinanzeigen",
    "immobilo.de": "immobilo",
    "yourimmo.de": "yourimmo",
    "meinestadt.de": "meinestadt",
    "immowelt.de": "immowelt",
    "regionalimmobilien24.de": "regionalimmobilien24",
    "immobilienscout24.de": "immobilienscout24",
}
_PLAUSIBLE_PRICE = 10_000


class DiscoveryError(RuntimeError):
    """Raised when live discovery cannot start, e.g. without an API key."""


class DiscoveryStatus(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"
    INDEX_PAGE = "index_page"
    FETCH_FAILED = "fetch_failed"
    BUDGET_EXHAUSTED = "budget_exhausted"


class DiscoveryRecord(StrictModel):
    """One row of the discovery report, for any pipeline outcome."""

    url: str
    portal: str
    status: DiscoveryStatus
    title: str = ""
    city: str = ""
    postal_code: str | None = None
    price_eur: float | None = None
    area_m2: float | None = None
    rooms: float | None = None
    condition: str | None = None
    matches_criteria: bool = False
    reasons: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    portals: list[str] = Field(default_factory=list)
    merged_from: list[str] = Field(default_factory=list)
    source_references: list[str] = Field(default_factory=list)
    possible_duplicates: list[str] = Field(default_factory=list)
    child_count: int | None = None
    listing: PropertyListing | None = None


class DiscoveryRun(StrictModel):
    """Diagnostics for one discovery run, in addition to the records."""

    records: list[DiscoveryRecord] = Field(default_factory=list)
    queries_run: list[str] = Field(default_factory=list)
    search_calls: int = 0
    search_errors: list[str] = Field(default_factory=list)
    index_fetches: int = 0
    detail_fetches: int = 0
    cross_query_duplicates: int = 0


class SearchClient(Protocol):
    def invoke(self, tool_input: dict[str, Any]) -> Any: ...


class FetchClient(Protocol):
    """Client returning a fetched page as ``{url, title, content, ...}``."""

    def invoke(self, tool_input: dict[str, Any]) -> Any: ...


def detect_portal(url: str) -> str:
    """Best-effort portal name from the URL host's registrable domain."""

    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    if host in _PORTAL_BY_HOST:
        return _PORTAL_BY_HOST[host]
    labels = host.rsplit(".", 2)
    return ".".join(labels[-2:]) if len(labels) == 3 else host


def is_listing_detail_url(url: str) -> bool:
    """True when the URL path identifies one individual listing page."""

    path = urlsplit(url).path.rstrip("/")
    return any(pattern.match(path) for pattern in _LISTING_PATHS)


def extract_listing_links(content: str, base_url: str) -> list[str]:
    """Extract individual listing URLs from a fetched index page.

    Only known listing URL shapes are considered (kleinanzeigen ads,
    immobilo/yourimmo object pages, immowelt and immobilienscout24 exposes);
    images, category pages, and navigation links are ignored. Order follows
    first appearance on the page, deduplicated by canonical URL.
    """

    links: list[str] = []
    seen: set[str] = set()
    for raw in _MARKDOWN_LINK.findall(content):
        candidate = raw.rstrip(".,;")
        if candidate.startswith("/") and not candidate.startswith("//"):
            candidate = urljoin(base_url, candidate)
        if not candidate.lower().startswith(("http://", "https://")):
            continue
        path = urlsplit(candidate).path
        matched = any(pattern.match(path.rstrip("/")) for pattern in _LISTING_PATHS)
        matched = matched or bool(
            _IMMOWELT_EXPOSE.search(candidate) or _REGIONAL_EXPOSE.search(candidate)
        )
        if not matched:
            continue
        key = canonical_url(candidate)
        if key in seen:
            continue
        seen.add(key)
        links.append(candidate)
    return links


def extract_source_references(content: str) -> list[str]:
    """Explicit expose/source references found on a detail page."""

    references: list[str] = []
    seen: set[str] = set()
    for match in _EXPOSE_REFERENCE.finditer(content):
        reference = canonical_url(match.group(0))
        if reference in seen:
            continue
        seen.add(reference)
        references.append(reference)
    return references


def trim_main_listing(content: str) -> str:
    """Drop sections that describe properties other than the page's own."""

    cut = len(content)
    for marker in _OTHER_LISTING_MARKERS:
        index = content.find(marker)
        if 0 <= index < cut:
            cut = index
    return content[:cut] if cut < len(content) else content



def page_signals(text: str) -> tuple[bool, list[float], list[str]]:
    """Multi-listing signal plus distinct prices and postal codes."""

    property_text = _property_content_only(text)

    postal_codes = sorted(set(_POSTAL_CODE.findall(property_text)))
    prices = sorted(
        {
            value
            for value in eur_price_values(property_text)
            if value > _PLAUSIBLE_PRICE
        }
    )

    return len(postal_codes) > 1 or len(prices) > 1, prices, postal_codes



def _default_fetch_client() -> KeenableFetch:
    """Keyless page fetch: the public endpoint is used regardless of env key."""

    return KeenableFetch(api_key=SecretStr(""), timeout=30)


def _default_search_client() -> KeenableSearch:
    """Authenticated search is mandatory; never fall back to keyless."""

    if not os.getenv("KEENABLE_API_KEY", "").strip():
        raise DiscoveryError(
            "KEENABLE_API_KEY is required for live Keenable search; "
            "keyless search fallback is disabled"
        )
    return KeenableSearch(timeout=30)


def result_title(result: dict[str, Any]) -> str:
    return str(result.get("title") or "").strip()


def _matches_criteria(listing: PropertyListing, criteria: InvestmentCriteria) -> bool:
    """Deterministic hard-criteria check; only complete listings can match."""

    if not is_complete_listing(listing):
        return False
    if listing.asking_price.amount > criteria.maximum_purchase_price.amount:
        return False
    if (
        criteria.minimum_room_count is not None
        and listing.room_count + 1e-9 < criteria.minimum_room_count
    ):
        return False
    if (
        criteria.minimum_living_area_sqm is not None
        and listing.living_area_sqm + 1e-9 < criteria.minimum_living_area_sqm
    ):
        return False
    if criteria.postal_codes and listing.postal_code not in criteria.postal_codes:
        return False
    features = {feature.casefold() for feature in listing.features}
    required = {feature.casefold() for feature in criteria.required_features}
    excluded = {feature.casefold() for feature in criteria.excluded_features}
    if required and not required <= features:
        return False
    return not (excluded and excluded & features)


def _parse_child_page(
    page: dict[str, Any],
    url: str,
    criteria: InvestmentCriteria,
    parent_title: str,
) -> tuple[PropertyListing | None, list[str], list[str]]:
    """Parse an individual listing page fetched from an index page.

    The parent index page supplies the purchase-intent and city context, so
    pages without their own wording (for example kleinanzeigen ads) are not
    rejected for missing markers. Only the trimmed main section contributes
    attributes, so listings from "other ads" page sections are never mixed in.
    """

    content = str(page.get("content") or "")
    main = trim_main_listing(content)
    page_title = str(page.get("title") or "").strip()
    context_title = (
        f"{parent_title}\n{page_title}".strip() if parent_title else page_title
    )
    pseudo = {"title": context_title, "url": url, "snippet": main}
    reasons = rejection_reasons(pseudo, criteria)
    if reasons:
        return None, reasons, []
    multi, _, postals = page_signals(main)
    if multi:
        return None, ["multi-listing-page"], []
    normalized = main.casefold()
    rooms_match = _ROOMS.search(main) or _ROOMS_AFTER.search(main)
    area_match = _AREA.search(main)
    build_year_match = _BUILD_YEAR.search(main)
    energy_match = _ENERGY_CLASS.search(main)
    features = sorted({term for term in _FEATURE_TERMS if term in normalized})
    evidence = SourceEvidence(
        source_name="Keenable keyless page fetch",
        url=url,
        retrieved_at=datetime.now(UTC),
        # Keep enough of the selected listing page for Agent 3 to extract its
        # public contact details later without fetching another source.
        excerpt=content[:12_000],
    )
    asking_price = purchase_price_value(main)
    if asking_price is None:
        # Keep a nearby service charge, commission, or rent from becoming the
        # asking price if a page structure changes after initial validation.
        return None, ["ambiguous-price"], []
    listing = PropertyListing(
        property_id=uuid5(NAMESPACE_URL, url),
        source_listing_id=f"keenable-{uuid5(NAMESPACE_URL, url).hex}",
        title=(page_title or context_title or url)[:500],
        city=criteria.locations[0],
        postal_code=postals[0] if postals else None,
        country_code="DE",
        property_type=criteria.property_types[0],
        asking_price=Money(amount=asking_price, currency="EUR"),
        living_area_sqm=_decimal(area_match.group("value")) if area_match else None,
        room_count=_decimal(rooms_match.group("value")) if rooms_match else None,
        build_year=int(build_year_match.group("value")) if build_year_match else None,
        energy_class=energy_match.group("value").upper() if energy_match else None,
        condition=extract_condition(main),
        description=main[:2_000],
        features=features,
        listing_url=url,
        evidence=[evidence],
        missing_fields=["annual_rent"],
    )
    missing = []
    if listing.living_area_sqm is None:
        missing.append("living_area")
    if listing.room_count is None:
        missing.append("room_count")
    return listing, [], missing


def _decimal(value: str) -> float:
    return float(value.replace(",", "."))


def _child_listing_priority(url: str, criteria: InvestmentCriteria) -> int:
    """Rank likely matching detail URLs ahead of generic broad-search links.

    This is only a fetch-order heuristic: each fetched page still passes the
    normal content and criteria checks before it can be validated.
    """

    text = unquote(url).casefold().replace("_", "-")
    score = 0
    if any(alias in text for alias in city_aliases(criteria.locations[0])):
        score += 5
    if criteria.property_types[0] == "apartment" and any(
        term in text for term in ("wohnung", "apartment", "penthouse")
    ):
        score += 4
    if criteria.minimum_room_count is not None:
        rooms = criteria.minimum_room_count
        room_markers = (
            f"{rooms:g}-zimmer",
            f"{rooms:g}-zi",
            f"{rooms:g}zimmer",
        )
        if any(marker in text for marker in room_markers):
            score += 6
    if any(term in text for term in ("kaufen", "eigentumswohnung", "provisionsfrei")):
        score += 2
    return score


class DiscoveryService:
    """Search portal index pages and fetch individual listings into a report.

    Every candidate URL — from search results or extracted from index pages —
    is fetched at most once, counted against a hard budget, and never retried.
    All configured search query variants run even after earlier queries
    returned results. Search failures skip the query; fetch failures become
    fetch-failed records. External errors never raise.
    """

    def __init__(
        self,
        search_client: SearchClient | None = None,
        fetch_client: FetchClient | None = None,
        search_budget: int = DEFAULT_SEARCH_BUDGET,
        index_fetch_budget: int = DEFAULT_INDEX_FETCH_BUDGET,
        detail_fetch_budget: int = DEFAULT_DETAIL_FETCH_BUDGET,
    ) -> None:
        self._search_client = (
            search_client if search_client is not None else _default_search_client()
        )
        self._fetch_client = (
            fetch_client if fetch_client is not None else _default_fetch_client()
        )
        self._search_budget = max(0, search_budget)
        self._index_fetch_budget = max(0, index_fetch_budget)
        self._detail_fetch_budget = max(0, detail_fetch_budget)
        self.last_run: DiscoveryRun | None = None

    def run(self, criteria: InvestmentCriteria) -> DiscoveryRun:
        run = DiscoveryRun()
        records: list[DiscoveryRecord] = []
        seen_urls: set[str] = set()
        fetched_urls: set[str] = set()
        child_seen: set[str] = set()
        children: list[tuple[str, str]] = []

        # Stage 1: authenticated search; every configured query runs.
        for query in search_queries(criteria)[: self._search_budget]:
            run.queries_run.append(query)
            run.search_calls += 1
            try:
                raw = self._search_client.invoke({"query": query})
            except Exception as exc:  # noqa: BLE001 - boundary errors are recorded
                run.search_errors.append(f"{query}: {type(exc).__name__}")
                continue
            if not isinstance(raw, list):
                run.search_errors.append(f"{query}: unexpected response type")
                continue
            for result in raw:
                if not (
                    isinstance(result, dict) and str(result.get("url") or "").strip()
                ):
                    continue
                url = canonical_url(str(result["url"]))
                if url in seen_urls:
                    run.cross_query_duplicates += 1
                    continue
                seen_urls.add(url)
                records.extend(
                    self._handle_search_result(
                        result, url, criteria, children, child_seen, fetched_urls, run
                    )
                )

        # Stage 2: keyless fetches of individual listings from index pages.
        # Broad city searches can produce hundreds of child URLs. Prioritise
        # the ones whose URL slug most clearly matches the brief before the
        # finite detail-fetch budget is exhausted.
        for child_url, parent_title in sorted(
            children,
            key=lambda item: _child_listing_priority(item[0], criteria),
            reverse=True,
        ):
            records.extend(
                self._fetch_detail(
                    parent_title, child_url, criteria, None, run, fetched_urls
                )
            )

        run.records = deduplicate_and_merge(records)
        self.last_run = run
        return run

    def _handle_search_result(
        self,
        result: dict[str, Any],
        url: str,
        criteria: InvestmentCriteria,
        children: list[tuple[str, str]],
        child_seen: set[str],
        fetched_urls: set[str],
        run: DiscoveryRun,
    ) -> list[DiscoveryRecord]:
        """Gate a snippet, then route it to an index or detail fetch."""

        # Snippets often lack a postal code or a single price, and index
        # candidates only serve as link sources, so candidates are fetched
        # unless the snippet is clearly not a purchase page. Children are
        # validated individually on their own pages anyway.
        reasons = rejection_reasons(result, criteria)
        if reasons and set(reasons) - {
            "multi-listing-page",
            "no-price",
            "postal-code-outside-area",
        }:
            return [_rejection_record(result_title(result), url, reasons)]
        listing = normalize_search_result(result, criteria) if not reasons else None
        if is_listing_detail_url(url):
            return self._fetch_detail("", url, criteria, listing, run, fetched_urls)
        if self._index_fetch_budget <= 0:
            return [_budget_exhausted_record(url, "index")]
        self._index_fetch_budget -= 1
        run.index_fetches += 1
        fetched_urls.add(url)
        page, error = self._fetch(url)
        if error is not None:
            return [_fetch_failed_record(url, error)]
        return _process_index_page(page, url, criteria, children, child_seen)

    def _fetch(self, url: str) -> tuple[dict[str, Any] | None, str | None]:
        """Invoke the keyless fetch client; return ``(page, error_message)``."""

        try:
            page = self._fetch_client.invoke({"url": url})
        except Exception as exc:  # noqa: BLE001 - boundary errors are recorded
            return None, type(exc).__name__[:200]
        if isinstance(page, dict):
            return page, None
        return None, (str(page)[:200] if page else "empty-response")

    def _fetch_detail(
        self,
        parent_title: str,
        url: str,
        criteria: InvestmentCriteria,
        existing: PropertyListing | None,
        run: DiscoveryRun,
        fetched_urls: set[str],
    ) -> list[DiscoveryRecord]:
        """Fetch one listing page against the detail budget; never retried."""

        key = canonical_url(url)
        if key in fetched_urls:
            return []
        if self._detail_fetch_budget <= 0:
            return [_budget_exhausted_record(key, "detail")]
        fetched_urls.add(key)
        self._detail_fetch_budget -= 1
        run.detail_fetches += 1
        page, error = self._fetch(key)
        if error is not None:
            return [_fetch_failed_record(key, error)]
        content = str(page.get("content") or "")
        if parent_title:
            listing, reasons, missing = _parse_child_page(
                page, key, criteria, parent_title
            )
            record = _property_record(listing, reasons, missing, key, criteria)
            if listing is not None:
                record.source_references = extract_source_references(content)
            return [record]
        merged, reasons = merge_page_listing(
            {**page, "content": trim_main_listing(content)}, key, criteria, existing
        )
        if merged is None:
            status = (
                DiscoveryStatus.QUARANTINED
                if "multi-listing-page" in reasons
                else DiscoveryStatus.REJECTED
            )
            record = _record_stub(key, status, reasons)
        else:
            missing = [
                field
                for field, value in (
                    ("living_area", merged.living_area_sqm),
                    ("room_count", merged.room_count),
                )
                if value is None
            ]
            record = _property_record(merged, [], missing, key, criteria)
        record.source_references = extract_source_references(content)
        return [record]


def has_single_property_evidence(text: str) -> bool:
    """Recognize an explicitly labelled individual property record."""

    normalized = text.casefold()

    price_label = any(
        label in normalized
        for label in ("purchase price", "kaufpreis")
    )
    area_label = any(
        label in normalized
        for label in ("living space", "wohnfläche", "wohnflaeche")
    )
    room_label = any(
        label in normalized
        for label in ("rooms", "zimmer")
    )

    return price_label and area_label and room_label


def _process_index_page(
    page: dict[str, Any],
    url: str,
    criteria: InvestmentCriteria,
    children: list[tuple[str, str]],
    child_seen: set[str],
) -> list[DiscoveryRecord]:
    """Classify a fetched search-result page and queue its listing links.

    A page is an index page when it shows more than one price or postal code,
    or when it links to two or more individual listings. Otherwise it is
    parsed as a property page. Index pages only contribute child URLs; their
    attributes never enter a listing.
    """

    title = str(page.get("title") or "").strip()
    content = str(page.get("content") or "")
    links = extract_listing_links(content, str(page.get("url") or url))
    multi, _, _ = page_signals(f"{title}\n{content}")
    single_property = has_single_property_evidence(f"{title}\n{content}")
    if len(links) >= 2 or (multi and not single_property):
        parent_title = title or detect_portal(url)
        for link in links:
            key = canonical_url(link)
            if key not in child_seen:
                child_seen.add(key)
                children.append((link, parent_title))
        reasons = ["multi-listing-page"] if multi else []
        reasons.append("index-page")
        record = _record_stub(canonical_url(url), DiscoveryStatus.INDEX_PAGE, reasons)
        record.title = title[:200]
        record.child_count = len(links)
        return [record]
    merged, reasons = merge_page_listing(
        {**page, "content": trim_main_listing(content)}, url, criteria, None
    )
    if merged is None:
        status = (
            DiscoveryStatus.QUARANTINED
            if "multi-listing-page" in reasons
            else DiscoveryStatus.REJECTED
        )
        return [_record_stub(canonical_url(url), status, reasons)]
    missing = [
        field
        for field, value in (
            ("living_area", merged.living_area_sqm),
            ("room_count", merged.room_count),
        )
        if value is None
    ]
    record = _property_record(merged, [], missing, canonical_url(url), criteria)
    record.source_references = extract_source_references(content)
    return [record]


def _record_stub(
    url: str, status: DiscoveryStatus, reasons: list[str]
) -> DiscoveryRecord:
    return DiscoveryRecord(
        url=url, portal=detect_portal(url), status=status, reasons=list(reasons)
    )


def _rejection_record(title: str, url: str, reasons: list[str]) -> DiscoveryRecord:
    record = _record_stub(url, DiscoveryStatus.REJECTED, reasons)
    record.title = title[:200]
    return record


def _fetch_failed_record(url: str, error: str = "") -> DiscoveryRecord:
    record = _record_stub(url, DiscoveryStatus.FETCH_FAILED, ["fetch-error"])
    if error:
        record.reasons.append(error)
    return record


def _budget_exhausted_record(url: str, stage: str) -> DiscoveryRecord:
    return _record_stub(
        url, DiscoveryStatus.BUDGET_EXHAUSTED, [f"{stage}-fetch-budget-exhausted"]
    )


def _property_record(
    listing: PropertyListing | None,
    reasons: list[str],
    missing: list[str],
    url: str,
    criteria: InvestmentCriteria,
) -> DiscoveryRecord:
    if listing is None:
        status = (
            DiscoveryStatus.QUARANTINED
            if "multi-listing-page" in reasons
            else DiscoveryStatus.REJECTED
        )
        return _record_stub(url, status, list(reasons))
    status = DiscoveryStatus.COMPLETE if not missing else DiscoveryStatus.INCOMPLETE
    return DiscoveryRecord(
        url=canonical_url(str(listing.listing_url)),
        portal=detect_portal(url),
        status=status,
        title=listing.title[:200],
        city=listing.city,
        postal_code=listing.postal_code,
        price_eur=listing.asking_price.amount,
        area_m2=listing.living_area_sqm,
        rooms=listing.room_count,
        condition=listing.condition.value if listing.condition else None,
        matches_criteria=_matches_criteria(listing, criteria),
        reasons=list(reasons),
        missing=list(missing),
        listing=listing,
    )


_PROPERTY_STATUSES = {DiscoveryStatus.COMPLETE, DiscoveryStatus.INCOMPLETE}


def deduplicate_and_merge(records: list[DiscoveryRecord]) -> list[DiscoveryRecord]:
    """Drop same-URL duplicates, merge verified cross-portal records, flag rest.

    Merging happens only on shared explicit expose/source references. Records
    with identical defining attributes (postal code, price, rooms, area) on
    different portals without a shared reference are merely flagged as
    possible duplicates; nothing is merged on attribute equality alone.
    """

    unique: list[DiscoveryRecord] = []
    seen: set[str] = set()
    for record in records:
        if record.url in seen:
            continue
        seen.add(record.url)
        unique.append(record)

    by_reference: dict[str, list[int]] = {}
    for index, record in enumerate(unique):
        if record.status not in _PROPERTY_STATUSES:
            continue
        for reference in record.source_references:
            by_reference.setdefault(reference, []).append(index)

    merged_away: set[int] = set()
    for indexes in by_reference.values():
        group = [
            i
            for i in indexes
            if i not in merged_away and unique[i].status in _PROPERTY_STATUSES
        ]
        if len(group) < 2:
            continue
        primary = unique[group[0]]
        for index in group[1:]:
            other = unique[index]
            if other.portal not in primary.portals:
                primary.portals.append(other.portal)
            for url in (other.url, *other.merged_from):
                if url not in primary.merged_from:
                    primary.merged_from.append(url)
            merged_away.add(index)

    kept = [r for i, r in enumerate(unique) if i not in merged_away]
    by_attributes: dict[tuple[Any, ...], list[DiscoveryRecord]] = {}
    for record in kept:
        if record.status not in _PROPERTY_STATUSES:
            continue
        if None in (record.postal_code, record.price_eur, record.rooms, record.area_m2):
            continue
        key = (record.postal_code, record.price_eur, record.rooms, record.area_m2)
        by_attributes.setdefault(key, []).append(record)
    for group in by_attributes.values():
        portals = {record.portal for record in group}
        if len(group) < 2 or len(portals) < 2:
            continue
        for record in group:
            for other in group:
                if other is record:
                    continue
                if other.url not in record.possible_duplicates:
                    record.possible_duplicates.append(other.url)
    return kept


def _format_number(value: float | None) -> str:
    if value is None:
        return ""
    return format(value, "g")


CSV_COLUMNS = (
    "url",
    "portal",
    "portals",
    "title",
    "city",
    "postal_code",
    "price_eur",
    "area_m2",
    "rooms",
    "condition",
    "status",
    "matches_criteria",
    "reasons",
    "missing",
    "source_references",
    "possible_duplicates",
    "merged_from",
)
_LIST_COLUMNS = frozenset(
    {"reasons", "missing", "source_references", "possible_duplicates", "merged_from"}
)


def csv_text(records: list[DiscoveryRecord]) -> str:
    """Render discovery records as CSV text with a header row."""

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for record in records:
        row = []
        for column in CSV_COLUMNS:
            value = getattr(record, column)
            if value is True:
                value = "true"
            elif value is False:
                value = "false"
            elif column in ("price_eur", "area_m2", "rooms"):
                value = _format_number(value)
            elif column in _LIST_COLUMNS:
                value = ";".join(str(item) for item in value)
            elif value is None:
                value = ""
            row.append(value)
        writer.writerow(row)
    return buffer.getvalue()


def write_csv(
    records: list[DiscoveryRecord], output: str | Path | None = None
) -> str | None:
    """Return the CSV text, or write it to ``output`` when given."""

    text = csv_text(records)
    if output is None:
        return text
    Path(output).write_text(text, encoding="utf-8")
    return None


def build_criteria(args: argparse.Namespace) -> InvestmentCriteria:
    return InvestmentCriteria(
        locations=[args.city],
        postal_codes=list(args.postcode),
        maximum_purchase_price=Money(amount=args.budget, currency="EUR"),
        property_types=[args.property_type],
        minimum_room_count=args.rooms,
        minimum_living_area_sqm=args.min_area,
        strategy="buy_to_let",
        required_features=list(args.required_feature),
        excluded_features=list(args.excluded_feature),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="propertyscout.discovery",
        description=(
            "Standalone Keenable property discovery: authenticated search, "
            "keyless index and listing fetches, deduplication, validation, "
            "and CSV output."
        ),
    )
    parser.add_argument("--city", required=True, help="Target city, e.g. Düsseldorf")
    parser.add_argument("--budget", type=float, required=True, help="Maximum EUR price")
    parser.add_argument(
        "--property-type", default="apartment", help="Property type keyword (default: apartment)"
    )
    parser.add_argument(
        "--postcode", action="append", default=[], help="Restrict to a postal code (repeatable)"
    )
    parser.add_argument("--rooms", type=float, default=None, help="Minimum room count")
    parser.add_argument("--min-area", type=float, default=None, help="Minimum living area (m²)")
    parser.add_argument(
        "--required-feature", action="append", default=[], help="Required feature (repeatable)"
    )
    parser.add_argument(
        "--excluded-feature", action="append", default=[], help="Excluded feature (repeatable)"
    )
    parser.add_argument(
        "--search-budget", type=int, default=DEFAULT_SEARCH_BUDGET,
        help="Authenticated search calls (default: 10)",
    )
    parser.add_argument(
        "--index-fetch-budget", type=int, default=DEFAULT_INDEX_FETCH_BUDGET,
        help="Keyless index-page fetches (default: 10)",
    )
    parser.add_argument(
        "--detail-fetch-budget", type=int, default=DEFAULT_DETAIL_FETCH_BUDGET,
        help="Keyless individual-listing fetches (default: 20)",
    )
    parser.add_argument(
        "--output", default=None, help="Write the CSV to this path instead of stdout"
    )
    return parser


def run_cli(argv: list[str] | None, service: DiscoveryService | None = None) -> int:
    """Run the CLI; ``service`` is injectable for offline tests."""

    args = build_parser().parse_args(argv)
    criteria = build_criteria(args)
    if service is None:
        try:
            service = DiscoveryService(
                search_budget=args.search_budget,
                index_fetch_budget=args.index_fetch_budget,
                detail_fetch_budget=args.detail_fetch_budget,
            )
        except DiscoveryError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    run = service.run(criteria)
    text = csv_text(run.records)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    counts: dict[str, int] = {}
    for record in run.records:
        counts[record.status.value] = counts.get(record.status.value, 0) + 1
    summary = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    print(
        f"{run.search_calls} search call(s), {run.index_fetches} index fetch(es), "
        f"{run.detail_fetches} detail fetch(es); {len(run.records)} record(s): {summary}",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(argv)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
