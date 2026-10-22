"""Deterministic sample properties for learning and local tests."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from propertyscout.schemas import (
    Money,
    PropertyCondition,
    PropertyListing,
    SourceEvidence,
)

FIXTURE_SOURCE = SourceEvidence(
    source_name="PropertyScout training fixtures",
    retrieved_at=datetime(2026, 10, 21, tzinfo=UTC),
)


def sample_properties() -> dict[str, PropertyListing]:
    """Return one property for each important MVP route."""

    return {
        "shortlist": PropertyListing(
            property_id=UUID("00000000-0000-0000-0000-000000000001"),
            source_listing_id="fixture-shortlist",
            title="Cologne apartment with verified rent",
            address="Example Street 10",
            city="Cologne",
            postal_code="50667",
            country_code="DE",
            property_type="apartment",
            asking_price=Money(amount=210_000, currency="EUR"),
            living_area_sqm=62,
            room_count=3,
            annual_rent=Money(amount=15_120, currency="EUR"),
            description="A fixture expected to reach shortlist approval.",
            features=["balcony", "lift"],
            evidence=[FIXTURE_SOURCE],
        ),
        "reject": PropertyListing(
            property_id=UUID("00000000-0000-0000-0000-000000000002"),
            source_listing_id="fixture-reject",
            title="Cologne apartment above budget",
            address="Example Avenue 20",
            city="Cologne",
            postal_code="50668",
            country_code="DE",
            property_type="apartment",
            asking_price=Money(amount=420_000, currency="EUR"),
            living_area_sqm=70,
            room_count=3,
            annual_rent=Money(amount=17_640, currency="EUR"),
            description="A fixture expected to be rejected by the scout.",
            features=["balcony"],
            evidence=[FIXTURE_SOURCE],
        ),
        "research": PropertyListing(
            property_id=UUID("00000000-0000-0000-0000-000000000003"),
            source_listing_id="fixture-research",
            title="Cologne apartment with missing rent data",
            address="Example Lane 30",
            city="Cologne",
            postal_code="50670",
            country_code="DE",
            property_type="apartment",
            asking_price=Money(amount=195_000, currency="EUR"),
            living_area_sqm=58,
            room_count=2,
            description="A fixture expected to require more research.",
            features=["lift", "parking"],
            evidence=[FIXTURE_SOURCE],
            missing_fields=["annual_rent"],
        ),
    }


def sample_comparables() -> list[PropertyListing]:
    """Deterministic comparable listings for building a local market basis.

    Nine comps across three conditions in central Cologne give stable medians:
    renovated ~5,100 €/m², renovation-required ~3,400 €/m², well-maintained
    ~4,900 €/m², and one new-construction outlier at 6,500 €/m².
    """

    specs: list[
        tuple[str, str, float, int, PropertyCondition, int | None, str | None]
    ] = [
        ("Renovated Altstadt apartment", "50667", 62, 5_100, PropertyCondition.RENOVATED, 1962, "C"),
        ("Renovated Neustadt apartment", "50667", 58, 5_103, PropertyCondition.RENOVATED, 1958, "D"),
        ("Renovated city apartment", "50667", 70, 5_100, PropertyCondition.RENOVATED, 1972, "D"),
        ("Apartment needing renovation", "50670", 60, 3_400, PropertyCondition.RENOVATION_REQUIRED, 1936, "G"),
        ("Renovation project in Ehrenfeld", "50670", 55, 3_400, PropertyCondition.RENOVATION_REQUIRED, 1930, None),
        ("Distressed apartment", "50670", 68, 3_397, PropertyCondition.RENOVATION_REQUIRED, 1948, "G"),
        ("Well-maintained Belgian quarter flat", "50667", 60, 4_900, PropertyCondition.WELL_MAINTAINED, 1965, "D"),
        ("Pleasantly maintained apartment", "50668", 65, 4_938, PropertyCondition.WELL_MAINTAINED, 1970, "C"),
        ("New-build city apartment", "50667", 60, 6_500, PropertyCondition.NEW_CONSTRUCTION, 2024, "A"),
    ]

    comparables: list[PropertyListing] = []
    for index, (title, postal_code, area, per_sqm, condition, build_year, energy) in enumerate(
        specs, start=1
    ):
        url = f"https://fixtures.propertyscout.local/comp/{index}"
        comparables.append(
            PropertyListing(
                property_id=uuid5(NAMESPACE_URL, url),
                source_listing_id=f"fixture-comp-{index}",
                title=title,
                city="Cologne",
                postal_code=postal_code,
                country_code="DE",
                property_type="apartment",
                asking_price=Money(amount=area * per_sqm, currency="EUR"),
                living_area_sqm=area,
                room_count=3,
                build_year=build_year,
                energy_class=energy,
                condition=condition,
                features=["balcony", "lift"],
                listing_url=url,
                evidence=[FIXTURE_SOURCE],
                missing_fields=["annual_rent"],
            )
        )
    return comparables
