"""Live and fixture-backed listing discovery for the Market Scout."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from langchain_keenable import KeenableSearch

from propertyscout.fixtures import sample_comparables, sample_properties
from propertyscout.schemas import (
    InvestmentCriteria,
    Money,
    PropertyCondition,
    PropertyListing,
    SourceEvidence,
)

_PRICE_NUMBER = r"\d{1,3}(?:[.,\s]\d{3})+(?:[.,]\d{1,2})?|\d{4,7}(?:[.,]\d{1,2})?"
_PRICE_AFTER = re.compile(
    rf"(?P<value>{_PRICE_NUMBER})\s*(?:€|EUR)",
    re.IGNORECASE,
)
_PRICE_BEFORE = re.compile(
    rf"(?:€|EUR)\s*(?P<value>{_PRICE_NUMBER})",
    re.IGNORECASE,
)
_ROOMS = re.compile(
    r"(?P<value>\d+(?:[,.]\d+)?)\s*(?:Zi\.?|Zimmer|rooms?)\b", re.IGNORECASE
)
_AREA = re.compile(r"(?P<value>\d+(?:[,.]\d+)?)\s*(?:m²|m2|qm)\b", re.IGNORECASE)
_POSTAL_CODE = re.compile(r"\b(?P<value>\d{5})\b")
_PURCHASE_MARKERS = (
    "kaufpreis",
    "zum kauf",
    "wohnung kaufen",
    "haus kaufen",
    "for sale",
    "purchase price",
    "buy an apartment",
    "buy a house",
)
_CITY_ALIASES = {
    "cologne": ("cologne", "köln", "koeln"),
    "munich": ("munich", "münchen", "muenchen"),
}
_PROPERTY_TERMS = {
    "apartment": "Eigentumswohnung",
    "house": "Haus",
    "multifamily": "Mehrfamilienhaus",
}
_FEATURE_TERMS = (
    "balcony",
    "balkon",
    "lift",
    "aufzug",
    "elevator",
    "parking",
    "stellplatz",
    "garage",
    "terrace",
    "terrasse",
    "garten",
    "garden",
)
_BUILD_YEAR = re.compile(
    r"(?:Baujahr|erbaut|gebaut(?:\s+im\s+Jahr)?|built(?:\s+in)?)\s*[:\-]?\s*"
    r"(?P<value>(?:19|20)\d{2})",
    re.IGNORECASE,
)
_ENERGY_CLASS = re.compile(
    r"Energie(?:effizienz)?klasse\s*[:\-]?\s*(?:Klasse\s*)?"
    r"(?P<value>[A-G](?:\+\+)?)",
    re.IGNORECASE,
)
_CONDITION_MARKERS: tuple[tuple[PropertyCondition, tuple[str, ...]], ...] = (
    (
        PropertyCondition.RENOVATION_REQUIRED,
        (
            "renovierungsbedürftig",
            "sanierungsbedürftig",
            "renovation needed",
            "needs renovation",
        ),
    ),
    (
        PropertyCondition.PARTIALLY_RENOVATED,
        ("teilsaniert", "teilweise saniert", "teilrenoviert", "partially renovated"),
    ),
    (
        PropertyCondition.RENOVATED,
        ("saniert", "renoviert", "modernisiert", "renovated", "modernized"),
    ),
    (
        PropertyCondition.NEW_CONSTRUCTION,
        ("neubau", "neugebaut", "neu gebaut", "erstbezug", "new build", "newly built"),
    ),
    (
        PropertyCondition.WELL_MAINTAINED,
        ("neuwertig", "gepflegt", "well maintained", "well-kept"),
    ),
)


def extract_condition(text: str) -> PropertyCondition | None:
    """Map the worst condition marker found in the text to a condition enum.

    Markers are evaluated in priority order so that partial-renovation wording
    is not shadowed by the general ``saniert`` substring it contains.
    """

    normalized = text.casefold()
    for condition, markers in _CONDITION_MARKERS:
        if any(marker in normalized for marker in markers):
            return condition
    return None


class ListingSearchService(Protocol):
    def search(self, criteria: InvestmentCriteria) -> list[PropertyListing]: ...

    def search_comps(
        self,
        criteria: InvestmentCriteria,
        minimum_comps: int,
        maximum_queries: int,
    ) -> list[PropertyListing]: ...


class ListingSearchError(RuntimeError):
    """Raised when the external listing discovery provider cannot return results."""


class FixtureListingSearchService:
    """Deterministic listing source retained for tests and offline demos."""

    def search(self, criteria: InvestmentCriteria) -> list[PropertyListing]:
        return list(sample_properties().values())

    def search_comps(
        self,
        criteria: InvestmentCriteria,
        minimum_comps: int,
        maximum_queries: int,
    ) -> list[PropertyListing]:
        return sample_comparables()


class WebSearchClient(Protocol):
    def invoke(self, tool_input: dict[str, Any]) -> Any: ...


class KeenableListingSearchService:
    """Discover public purchase listings through Keenable and normalize snippets."""

    def __init__(self, client: WebSearchClient | None = None) -> None:
        self._client = client or KeenableSearch(timeout=30)

    def search(self, criteria: InvestmentCriteria) -> list[PropertyListing]:
        query = build_property_query(criteria)
        raw_results = self._client.invoke({"query": query})
        if not isinstance(raw_results, list):
            raise ListingSearchError(f"Keenable search failed: {raw_results}")

        listings: list[PropertyListing] = []
        seen_urls: set[str] = set()
        for result in raw_results:
            listing = normalize_search_result(result, criteria)
            if listing is None or str(listing.listing_url) in seen_urls:
                continue
            seen_urls.add(str(listing.listing_url))
            listings.append(listing)
        return listings

    def search_comps(
        self,
        criteria: InvestmentCriteria,
        minimum_comps: int = 8,
        maximum_queries: int = 3,
    ) -> list[PropertyListing]:
        """Collect comparable listings until the pool reaches ``minimum_comps``.

        Comp gathering is best effort: a failed query is skipped so a partial
        pool from later query variants still forms a basis. The pool is
        deduplicated by listing URL across all query variants.
        """

        pool: list[PropertyListing] = []
        seen_urls: set[str] = set()
        queries = comparable_queries(criteria)[:maximum_queries]
        for index, query in enumerate(queries):
            raw_results = self._client.invoke({"query": query})
            if not isinstance(raw_results, list):
                continue
            include_postcode = bool(criteria.postal_codes) and index == 0
            comp_criteria = _comps_criteria(criteria, include_postcode)
            for result in raw_results:
                listing = normalize_search_result(result, comp_criteria)
                if listing is None or str(listing.listing_url) in seen_urls:
                    continue
                seen_urls.add(str(listing.listing_url))
                pool.append(listing)
            if len(pool) >= minimum_comps:
                break
        return pool


def _comps_criteria(
    criteria: InvestmentCriteria, include_postcode: bool
) -> InvestmentCriteria:
    """Criteria used only for comp normalization and location checks."""

    return criteria.model_copy(
        update={"postal_codes": criteria.postal_codes if include_postcode else []}
    )


def comparable_queries(criteria: InvestmentCriteria) -> list[str]:
    """Build comp query variants: postcode-scoped first, then city-wide."""

    property_type = criteria.property_types[0]
    location = criteria.locations[0]
    search_type = _PROPERTY_TERMS.get(property_type, property_type)
    base = f"{search_type} kaufen {location}"
    if criteria.postal_codes:
        return [
            f"{base} {criteria.postal_codes[0]}",
            base,
        ]
    return [base]


def build_property_query(criteria: InvestmentCriteria) -> str:
    property_type = criteria.property_types[0]
    location = criteria.locations[0]
    search_type = _PROPERTY_TERMS.get(property_type.casefold(), property_type)
    aliases = _CITY_ALIASES.get(location.casefold(), (location,))
    parts = [
        search_type,
        " ".join(aliases),
        "kaufen",
        f"bis {criteria.maximum_purchase_price.amount:g} EUR",
    ]
    if criteria.postal_codes:
        parts.append(criteria.postal_codes[0])
    if criteria.minimum_room_count is not None:
        parts.append(f"{criteria.minimum_room_count:g} Zimmer")
    if criteria.minimum_living_area_sqm is not None:
        parts.append(f"{criteria.minimum_living_area_sqm:g} m²")
    return " ".join(parts)


def normalize_search_result(
    result: dict[str, Any], criteria: InvestmentCriteria
) -> PropertyListing | None:
    title = str(result.get("title") or "").strip()
    url = str(result.get("url") or "").strip()
    snippet = str(result.get("snippet") or result.get("description") or "").strip()
    combined = f"{title}\n{snippet}"
    normalized = combined.casefold()
    if not title or not url or not snippet:
        return None
    if not any(marker in normalized for marker in _PURCHASE_MARKERS):
        return None

    city = criteria.locations[0]
    aliases = _CITY_ALIASES.get(city.casefold(), (city.casefold(),))
    if not any(alias in normalized for alias in aliases):
        return None

    postal_codes = _POSTAL_CODE.findall(combined)
    if criteria.postal_codes and not any(code in criteria.postal_codes for code in postal_codes):
        return None

    price_match = _PRICE_AFTER.search(combined) or _PRICE_BEFORE.search(combined)
    if price_match is None:
        return None
    asking_price = _german_number(price_match.group("value"))
    if asking_price <= 10_000:
        return None

    rooms_match = _ROOMS.search(combined)
    area_match = _AREA.search(combined)
    build_year_match = _BUILD_YEAR.search(combined)
    energy_match = _ENERGY_CLASS.search(combined)
    features = [term for term in _FEATURE_TERMS if term in normalized]
    source = SourceEvidence(
        source_name="Keenable web search",
        url=url,
        retrieved_at=datetime.now(UTC),
        excerpt=snippet[:1_000],
    )
    return PropertyListing(
        property_id=uuid5(NAMESPACE_URL, url),
        source_listing_id=f"keenable-{uuid5(NAMESPACE_URL, url).hex}",
        title=title,
        city=city,
        postal_code=postal_codes[0] if postal_codes else None,
        country_code="DE",
        property_type=criteria.property_types[0],
        asking_price=Money(amount=asking_price, currency="EUR"),
        living_area_sqm=(
            _decimal_number(area_match.group("value")) if area_match else None
        ),
        room_count=(
            _decimal_number(rooms_match.group("value")) if rooms_match else None
        ),
        build_year=(
            int(build_year_match.group("value")) if build_year_match else None
        ),
        energy_class=(
            energy_match.group("value").upper() if energy_match else None
        ),
        condition=extract_condition(combined),
        description=snippet[:2_000],
        features=sorted(set(features)),
        listing_url=url,
        evidence=[source],
        missing_fields=["annual_rent"],
    )


def _german_number(value: str) -> float:
    normalized = value.replace(" ", "")
    if "." in normalized and "," in normalized:
        decimal_separator = "." if normalized.rfind(".") > normalized.rfind(",") else ","
        thousands_separator = "," if decimal_separator == "." else "."
        normalized = normalized.replace(thousands_separator, "").replace(
            decimal_separator, "."
        )
    elif "." in normalized or "," in normalized:
        separator = "." if "." in normalized else ","
        trailing_digits = len(normalized.rsplit(separator, 1)[1])
        normalized = (
            normalized.replace(separator, "")
            if trailing_digits == 3
            else normalized.replace(separator, ".")
        )
    return float(normalized)


def _decimal_number(value: str) -> float:
    return float(value.replace(",", "."))
