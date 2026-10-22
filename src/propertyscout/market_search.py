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

_PRICE_NUMBER = r"\d{1,3}(?:(?:[.,]|[^\S\n])\d{3})+(?:[.,]\d{1,2})?|\d{4,7}(?:[.,]\d{1,2})?"
# A price and its currency symbol must share one line so an amount followed on
# the next line by a different currency (for example "$556,200\n€515,000") is
# never paired with the wrong symbol.
_PRICE_GAP = r"[^\S\n]*"
_PRICE_AFTER = re.compile(
    r"(?P<value>" + _PRICE_NUMBER + r")" + _PRICE_GAP + r"(?:€|EUR)",
    re.IGNORECASE,
)
_PRICE_BEFORE = re.compile(
    r"(?:€|EUR)" + _PRICE_GAP + r"(?P<value>" + _PRICE_NUMBER + r")",
    re.IGNORECASE,
)
_ROOMS = re.compile(
    r"(?P<value>\d+(?:[,.]\d+)?)\s*[-\s]?\s*(?:Zi\.?|Zimmer|bedrooms?|rooms?)\b",
    re.IGNORECASE,
)
_AREA = re.compile(
    r"(?P<value>\d+(?:[,.]\d+)?)\s*[-\s]?\s*"
    r"(?:m²|m2|qm|sqm|square\s+metres?|square\s+meters?)\b",
    re.IGNORECASE,
)
_POSTAL_CODE = re.compile(r"\b(?P<value>\d{5})\b")

# Phrases that unambiguously describe buying rather than renting.
_SALE_MARKERS = (
    "kaufpreis",
    "zum kauf",
    "wohnung kaufen",
    "haus kaufen",
    "for sale",
    "purchase price",
    "buy an apartment",
    "buy a house",
    "zum verkauf",
)
# A purchase page may mention rental income ("vermietete Eigentumswohnung",
# "Kaltmiete"), so rental wording alone must not defeat a strong sale marker.
# The property word itself only signals sale intent when no rental intent is
# present, so rental ads do not pass through a bare "Eigentumswohnung".
_APARTMENT_SALE_MARKER = "eigentumswohnung"
_RENTAL_MARKERS = (
    "wohnung mieten",
    "haus mieten",
    "wohnung zur miete",
    "haus zur miete",
    "zur miete",
    "zur vermietung",
    "mietpreis",
    "kaltmiete",
    "warmmiete",
    "for rent",
    "apartment rent",
)
_CITY_ALIASES = {
    "cologne": ("cologne", "köln", "koeln"),
    "munich": ("munich", "münchen", "muenchen"),
}
_ASCII_FOLD_TABLE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
_ASCII_STRIP_TABLE = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "s"})
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


def city_aliases(city: str) -> tuple[str, ...]:
    """Casefolded spelling variants of a city.

    Covers the umlaut form, the umlaut transliteration (Duesseldorf), and the
    simple ASCII replacement (Dusseldorf) that mirrors and portals use, so a
    snippet is not rejected over spelling alone.
    """

    normalized = city.casefold()
    aliases = list(_CITY_ALIASES.get(normalized, (normalized,)))
    for variant in (
        normalized,
        normalized.translate(_ASCII_FOLD_TABLE),
        normalized.translate(_ASCII_STRIP_TABLE),
    ):
        if variant not in aliases:
            aliases.append(variant)
    return tuple(aliases)


def _has_rental_intent(normalized: str) -> bool:
    return any(marker in normalized for marker in _RENTAL_MARKERS)


def _has_sale_intent(normalized: str) -> bool:
    """Purchase intent with rental-context awareness.

    A strong sale marker always signals a purchase page, even when it mentions
    rental income. The bare property word ("Eigentumswohnung") only signals
    sale intent when the snippet shows no rental intent, so rental ads do not
    pass through it.
    """

    if any(marker in normalized for marker in _SALE_MARKERS):
        return True
    if _APARTMENT_SALE_MARKER not in normalized:
        return False
    return not _has_rental_intent(normalized)


_DOLLAR_PREFIXES = ("$", "us$", "usd")


def _is_foreign_currency_value(text: str, start: int) -> bool:
    """True when the number is preceded by a non-EUR currency marker."""

    prefix = text[:start].rstrip().casefold()
    return prefix.endswith(_DOLLAR_PREFIXES)


def eur_price_values(text: str) -> list[float]:
    """Every EUR price candidate in text order, number-before-symbol first.

    Values preceded by another currency marker such as "$556,200" are skipped,
    and a currency symbol must share a line with its amount, so a USD figure
    is never recorded as the EUR asking price.
    """

    values: list[float] = []
    for pattern in (_PRICE_AFTER, _PRICE_BEFORE):
        for match in pattern.finditer(text):
            if _is_foreign_currency_value(text, match.start("value")):
                continue
            values.append(_german_number(match.group("value")))
    return values


def _is_multi_listing_page(combined: str, price_values: list[float]) -> bool:
    """Detect aggregator pages that mix several properties in one snippet.

    A trustworthy snippet describes exactly one identifiable property: one
    distinct purchase price and at most one postal code. Two or more of either
    mean the extracted attributes could come from different units, so the page
    is quarantined instead of fabricating a composite listing.
    """

    postal_codes = set(_POSTAL_CODE.findall(combined))
    purchase_prices = {value for value in price_values if value > 10_000}
    return len(postal_codes) > 1 or len(purchase_prices) > 1


def rejection_reasons(
    result: Any, criteria: InvestmentCriteria
) -> list[str]:
    """Every discovery gate a Keenable search result fails, in pipeline order."""

    if not isinstance(result, dict):
        return ["missing-field"]
    title = str(result.get("title") or "").strip()
    url = str(result.get("url") or "").strip()
    snippet = str(result.get("snippet") or result.get("description") or "").strip()
    if not (title and url and snippet):
        return ["missing-field"]
    combined = f"{title}\n{snippet}"
    normalized = combined.casefold()
    reasons: list[str] = []
    if not _has_sale_intent(normalized):
        reasons.append(
            "rental-intent" if _has_rental_intent(normalized) else "no-purchase-marker"
        )
    aliases = city_aliases(criteria.locations[0])
    if not any(alias in normalized for alias in aliases):
        reasons.append("no-city-match")
    if criteria.postal_codes and not any(
        code in criteria.postal_codes for code in _POSTAL_CODE.findall(combined)
    ):
        reasons.append("postal-code-outside-area")
    price_values = eur_price_values(combined)
    if not price_values:
        reasons.append("no-price")
        return reasons
    if price_values[0] <= 10_000:
        reasons.append("implausible-price")
    if _is_multi_listing_page(combined, price_values):
        reasons.append("multi-listing-page")
    return reasons


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
    """Discover public purchase listings through Keenable and normalize snippets.

    Rejected candidates and their rejection reasons are preserved on
    ``last_rejections`` after every ``search`` or ``search_comps`` call so the
    discovery funnel can be diagnosed without live API calls.
    """

    def __init__(self, client: WebSearchClient | None = None) -> None:
        self._client = client or KeenableSearch(timeout=30)
        self.last_rejections: list[dict[str, Any]] = []

    def search(self, criteria: InvestmentCriteria) -> list[PropertyListing]:
        self.last_rejections = []
        query = build_property_query(criteria)
        raw_results = self._client.invoke({"query": query})
        if not isinstance(raw_results, list):
            raise ListingSearchError(f"Keenable search failed: {raw_results}")

        listings: list[PropertyListing] = []
        seen_urls: set[str] = set()
        for result in raw_results:
            listing = normalize_search_result(result, criteria)
            if listing is None:
                self._record_rejection(result, criteria)
                continue
            if str(listing.listing_url) in seen_urls:
                self._record_rejection(result, criteria, ["duplicate-url"])
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

        self.last_rejections = []
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
                if listing is None:
                    self._record_rejection(result, comp_criteria)
                    continue
                if str(listing.listing_url) in seen_urls:
                    self._record_rejection(result, comp_criteria, ["duplicate-url"])
                    continue
                seen_urls.add(str(listing.listing_url))
                pool.append(listing)
            if len(pool) >= minimum_comps:
                break
        return pool

    def _record_rejection(
        self,
        result: Any,
        criteria: InvestmentCriteria,
        reasons: list[str] | None = None,
    ) -> None:
        """Preserve a rejected candidate with its reasons for diagnostics."""

        if not isinstance(result, dict):
            self.last_rejections.append(
                {"title": "", "url": str(result)[:200], "reasons": ["missing-field"]}
            )
            return
        self.last_rejections.append(
            {
                "title": str(result.get("title") or "")[:200],
                "url": str(result.get("url") or ""),
                "reasons": (
                    reasons if reasons is not None else rejection_reasons(result, criteria)
                ),
            }
        )


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
    if rejection_reasons(result, criteria):
        return None
    title = str(result.get("title") or "").strip()
    url = str(result.get("url") or "").strip()
    snippet = str(result.get("snippet") or result.get("description") or "").strip()
    combined = f"{title}\n{snippet}"
    normalized = combined.casefold()
    asking_price = eur_price_values(combined)[0]

    rooms_match = _ROOMS.search(combined)
    area_match = _AREA.search(combined)
    build_year_match = _BUILD_YEAR.search(combined)
    energy_match = _ENERGY_CLASS.search(combined)
    features = [term for term in _FEATURE_TERMS if term in normalized]
    postal_codes = _POSTAL_CODE.findall(combined)
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
        city=criteria.locations[0],
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
