"""Live and fixture-backed listing discovery for the Market Scout."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from langchain_keenable import KeenableSearch

from propertyscout.fixtures import sample_properties
from propertyscout.schemas import (
    InvestmentCriteria,
    Money,
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
    "garden",
    "garten",
)


class ListingSearchService(Protocol):
    def search(self, criteria: InvestmentCriteria) -> list[PropertyListing]: ...


class ListingSearchError(RuntimeError):
    """Raised when the external listing discovery provider cannot return results."""


class FixtureListingSearchService:
    """Deterministic listing source retained for tests and offline demos."""

    def search(self, criteria: InvestmentCriteria) -> list[PropertyListing]:
        return list(sample_properties().values())


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
