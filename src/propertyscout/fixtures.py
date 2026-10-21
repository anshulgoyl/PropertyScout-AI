"""Deterministic sample properties for learning and local tests."""

from datetime import UTC, datetime
from uuid import UUID

from propertyscout.schemas import Money, PropertyListing, SourceEvidence

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
