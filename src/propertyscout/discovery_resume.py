"""Resume the standalone discovery pipeline from an existing CSV inventory.

The discovery CLI in :mod:`propertyscout.discovery` always starts from an
authenticated search. This module adds the smallest capability needed to
continue an interrupted run: it reads an existing discovery CSV, selects
previously budget-exhausted *individual listing* URLs, re-fetches them with
the keyless Keenable fetch client, revalidates every page against the same
gates as a fresh run, and writes the updated inventory to a NEW output file.
The source CSV is never modified.

Constraints carried over from the discovery pipeline:

- Keyless ``KeenableFetch`` only; no authenticated Keenable search, no
  LangGraph threads, and no outreach are involved.
- A hard fetch budget with no automatic retries; every fetch attempt is
  recorded (complete, incomplete, rejected, quarantined, fetch-failed).
- Candidates with clear below-minimum-area evidence in the URL slug and
  likely syndicated duplicates of already validated listings are excluded
  from the batch; uncertain duplicates are flagged as possible duplicates
  and retained untouched for later review.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from langchain_keenable import KeenableFetch
from pydantic import Field, SecretStr

from propertyscout.discovery import (
    DEFAULT_DETAIL_FETCH_BUDGET,
    DiscoveryRecord,
    DiscoveryStatus,
    FetchClient,
    _fetch_failed_record,
    _property_record,
    _record_stub,
    csv_text,
    extract_source_references,
    trim_main_listing,
)
from propertyscout.market_search import canonical_url, merge_page_listing
from propertyscout.schemas import InvestmentCriteria, Money, StrictModel

# Per-portal priority for the next resume batch: promising Immobilo listings
# first, then Kleinanzeigen, then a small Immoportal probe.
PORTAL_BATCH_LIMITS: dict[str, int] = {
    "immobilo": 12,
    "kleinanzeigen": 5,
    "immoportal.com": 3,
}
DETAIL_FETCH_REASON = "detail-fetch-budget-exhausted"
INDEX_FETCH_REASON = "index-fetch-budget-exhausted"
DEFAULT_MINIMUM_AREA = 50.0

# Clear living-area evidence in a listing URL slug, e.g. "ca-40qm-wfl".
_SLUG_AREA = re.compile(r"(?P<value>\d+(?:[,.]\d+)?)\s*[-\s]?\s*qm", re.IGNORECASE)
# Promising Kleinanzeigen candidates: two-room (or 2.5-room) apartments.
_TWO_ROOMS = re.compile(r"\b2(?:[.,]5)?-zimmer\b")
# Portal object IDs such as -GXP2N8 or -H5RC5T at the end of a slug.
_OBJECT_ID = re.compile(r"-[HG][A-Z0-9]{4,8}$")
_CITY_PREFIX = re.compile(r"^duesseldorf-", re.IGNORECASE)
_PROPERTY_STATUSES = (DiscoveryStatus.COMPLETE, DiscoveryStatus.INCOMPLETE)


class ResumeError(RuntimeError):
    """Raised when the resume run cannot proceed with the given inventory."""


class DuplicateFlag(StrictModel):
    """A cross-portal duplicate relationship between two inventory rows."""

    candidate: str
    validated: str


class ResumeSelection(StrictModel):
    """Deterministic selection report for one resume batch."""

    selected: list[str] = Field(default_factory=list)
    excluded_below_area: list[str] = Field(default_factory=list)
    excluded_likely_duplicates: list[str] = Field(default_factory=list)
    retained_uncertain_duplicates: list[str] = Field(default_factory=list)
    duplicate_flags: list[DuplicateFlag] = Field(default_factory=list)
    budget_exhausted_total: int = 0
    remaining_budget_exhausted: int = 0
    remaining_by_portal: dict[str, int] = Field(default_factory=dict)
    remaining_index_pages: int = 0


class ResumeOutcome(StrictModel):
    """Updated inventory plus fetch diagnostics for one resume batch."""

    records: list[DiscoveryRecord] = Field(default_factory=list)
    selection: ResumeSelection
    fetches: int = 0
    complete: int = 0
    incomplete: int = 0
    rejected: int = 0
    quarantined: int = 0
    fetch_failed: int = 0
    deferred: int = 0


def _decimal(value: str) -> float:
    return float(value.replace(",", "."))


def _split_list(text: str | None) -> list[str]:
    normalized = (text or "").strip()
    if normalized in ("", "[]"):
        return []
    return [item for item in normalized.split(";") if item]


def _optional(text: str | None) -> str | None:
    value = (text or "").strip()
    return value or None


def read_inventory(path: str | Path) -> list[DiscoveryRecord]:
    """Parse a discovery CSV written by any writer back into records.

    List columns use ``;`` separators; an empty list is stored either as an
    empty string or as a literal ``[]`` depending on the writer. Numeric and
    boolean columns stay empty for candidates that were never validated.
    """

    records: list[DiscoveryRecord] = []
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                status = DiscoveryStatus((row.get("status") or "").strip())
            except ValueError as exc:
                raise ResumeError(f"unknown status {row.get('status')!r}") from exc
            price = (row.get("price_eur") or "").strip()
            area = (row.get("area_m2") or "").strip()
            rooms = (row.get("rooms") or "").strip()
            records.append(
                DiscoveryRecord(
                    url=(row.get("url") or "").strip(),
                    portal=(row.get("portal") or "").strip(),
                    portals=_split_list(row.get("portals")),
                    title=(row.get("title") or "").strip(),
                    city=(row.get("city") or "").strip(),
                    postal_code=_optional(row.get("postal_code")),
                    price_eur=_decimal(price) if price else None,
                    area_m2=_decimal(area) if area else None,
                    rooms=_decimal(rooms) if rooms else None,
                    condition=_optional(row.get("condition")),
                    status=status,
                    matches_criteria=(row.get("matches_criteria") or "").strip()
                    == "true",
                    reasons=_split_list(row.get("reasons")),
                    missing=_split_list(row.get("missing")),
                    source_references=_split_list(row.get("source_references")),
                    possible_duplicates=_split_list(row.get("possible_duplicates")),
                    merged_from=_split_list(row.get("merged_from")),
                )
            )
    if not records:
        raise ResumeError(f"no inventory records found in {path}")
    return records


def _path_slug(url: str) -> str:
    """The slug part of a listing URL path, without ad/ID segments."""

    path = urlsplit(url).path
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return ""
    if path.startswith("/s-anzeige/") and len(segments) >= 2:
        return segments[-2]
    return segments[-1]


def _slug_words(url: str) -> str:
    """Slug words with the portal object ID and city prefix stripped."""

    slug = _OBJECT_ID.sub("", _path_slug(url))
    return _CITY_PREFIX.sub("", slug).casefold()


def _validated_slugs(
    records: list[DiscoveryRecord],
) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str]]]:
    """Slug-with-ID and slug-words of already validated property records.

    Returns ``(by_id, by_words)`` mapping each slug to its ``(portal, url)``
    so candidates can be checked for syndicated duplicates of validated
    listings on other portals.
    """

    by_id: dict[str, tuple[str, str]] = {}
    by_words: dict[str, tuple[str, str]] = {}
    for record in records:
        if record.status not in _PROPERTY_STATUSES:
            continue
        url = canonical_url(record.url)
        by_id.setdefault(_path_slug(url).casefold(), (record.portal, url))
        words = _slug_words(url)
        if words:
            by_words.setdefault(words, (record.portal, url))
    return by_id, by_words


def select_resume_candidates(
    records: list[DiscoveryRecord], limits: dict[str, int] | None = None
) -> ResumeSelection:
    """Choose the next batch of previously budget-exhausted listings.

    Only individual listing pages (detail-fetch candidates) of the portals in
    ``limits`` are eligible. Excluded from the batch: candidates whose slug
    shows clear evidence of a living area below the minimum, candidates whose
    full slug (including the portal object ID) already exists as a validated
    listing on another portal (likely syndicated duplicates), and candidates
    whose slug words match a validated listing on another portal (uncertain
    duplicates — flagged and retained untouched for later review). Within
    each portal, candidates are taken in file order; Kleinanzeigen candidates
    with a two-room slug are promoted to the front of their portal bucket.
    All remaining counts are recalculated directly from the inventory.
    """

    limits = dict(PORTAL_BATCH_LIMITS if limits is None else limits)
    by_id, by_words = _validated_slugs(records)
    buckets: dict[str, list[str]] = {portal: [] for portal in limits}
    excluded_below_area: list[str] = []
    excluded_likely_duplicates: list[str] = []
    retained_uncertain_duplicates: list[str] = []
    duplicate_flags: list[DuplicateFlag] = []
    selected_words: set[str] = set()

    budget_exhausted_total = sum(
        1 for record in records if record.status is DiscoveryStatus.BUDGET_EXHAUSTED
    )
    for record in records:
        if record.status is not DiscoveryStatus.BUDGET_EXHAUSTED:
            continue
        if DETAIL_FETCH_REASON not in record.reasons:
            continue  # index pages are not refetched by resume batches
        portal = record.portal
        if portal not in limits or limits[portal] <= 0:
            continue
        url = canonical_url(record.url)
        slug = _path_slug(url).casefold()
        area_match = _SLUG_AREA.search(slug)
        if area_match and _decimal(area_match.group("value")) < DEFAULT_MINIMUM_AREA:
            excluded_below_area.append(url)
            continue
        words = _slug_words(url)
        found = by_id.get(slug)
        if slug and found is not None and found[0] != portal:
            excluded_likely_duplicates.append(url)
            duplicate_flags.append(DuplicateFlag(candidate=url, validated=found[1]))
            continue
        found = by_words.get(words)
        if words and found is not None and found[0] != portal:
            retained_uncertain_duplicates.append(url)
            duplicate_flags.append(DuplicateFlag(candidate=url, validated=found[1]))
            continue
        if words and words in selected_words:
            retained_uncertain_duplicates.append(url)
            continue
        selected_words.add(words)
        buckets[portal].append(url)

    selected: list[str] = []
    for portal, limit in limits.items():
        pool = buckets[portal]
        if portal == "kleinanzeigen":
            promoted = [url for url in pool if _TWO_ROOMS.search(_path_slug(url))]
            pool = promoted + [url for url in pool if url not in promoted]
        selected.extend(pool[: max(0, limit)])

    selected_set = {canonical_url(url) for url in selected}
    remaining_by_portal: dict[str, int] = {}
    remaining_index_pages = 0
    for record in records:
        if record.status is not DiscoveryStatus.BUDGET_EXHAUSTED:
            continue
        if canonical_url(record.url) in selected_set:
            continue
        if INDEX_FETCH_REASON in record.reasons:
            remaining_index_pages += 1
        else:
            remaining_by_portal[record.portal] = (
                remaining_by_portal.get(record.portal, 0) + 1
            )

    return ResumeSelection(
        selected=selected,
        excluded_below_area=excluded_below_area,
        excluded_likely_duplicates=excluded_likely_duplicates,
        retained_uncertain_duplicates=retained_uncertain_duplicates,
        duplicate_flags=duplicate_flags,
        budget_exhausted_total=budget_exhausted_total,
        remaining_budget_exhausted=budget_exhausted_total - len(selected),
        remaining_by_portal=remaining_by_portal,
        remaining_index_pages=remaining_index_pages,
    )


def _fetch_page(fetch_client: FetchClient, url: str) -> tuple[dict | None, str | None]:
    """One keyless fetch attempt; external errors become error messages."""

    try:
        page = fetch_client.invoke({"url": url})
    except Exception as exc:  # noqa: BLE001 - boundary errors are recorded
        return None, type(exc).__name__[:200]
    if isinstance(page, dict):
        return page, None
    return None, (str(page)[:200] if page else "empty-response")


def _resume_detail_record(
    page: dict, url: str, criteria: InvestmentCriteria
) -> DiscoveryRecord:
    """Validate one fetched detail page with the discovery pipeline rules."""

    content = str(page.get("content") or "")
    merged, reasons = merge_page_listing(
        {**page, "content": trim_main_listing(content)}, url, criteria, None
    )
    if merged is None:
        status = (
            DiscoveryStatus.QUARANTINED
            if "multi-listing-page" in reasons
            else DiscoveryStatus.REJECTED
        )
        record = _record_stub(url, status, reasons)
    else:
        missing = [
            field
            for field, value in (
                ("living_area", merged.living_area_sqm),
                ("room_count", merged.room_count),
            )
            if value is None
        ]
        record = _property_record(merged, [], missing, url, criteria)
    record.source_references = extract_source_references(content)
    return record


def resume_inventory(
    records: list[DiscoveryRecord],
    selection: ResumeSelection,
    criteria: InvestmentCriteria,
    fetch_client: FetchClient,
    detail_fetch_budget: int = DEFAULT_DETAIL_FETCH_BUDGET,
) -> ResumeOutcome:
    """Fetch the selected URLs once each and update their inventory rows.

    Rows are updated in place (same order, same URL); all other records are
    preserved untouched. Uncertain cross-portal duplicates are never merged —
    they are flagged via ``possible_duplicates`` and kept for review. The
    budget counts every fetch attempt — including failed ones — and nothing
    is retried.
    """

    updated = list(records)
    index_by_url = {canonical_url(record.url): i for i, record in enumerate(updated)}
    for flag in selection.duplicate_flags:
        index = index_by_url.get(canonical_url(flag.candidate))
        if index is None:
            continue
        row = updated[index]
        if flag.validated not in row.possible_duplicates:
            updated[index] = row.model_copy(
                update={"possible_duplicates": [*row.possible_duplicates, flag.validated]}
            )
    outcome = ResumeOutcome(selection=selection)
    budget = max(0, detail_fetch_budget)
    for url in selection.selected:
        key = canonical_url(url)
        index = index_by_url.get(key)
        if index is None:
            raise ResumeError(f"selected candidate is not in the inventory: {url}")
        if budget <= 0:
            outcome.deferred += 1
            continue
        budget -= 1
        outcome.fetches += 1
        page, error = _fetch_page(fetch_client, key)
        if error is not None:
            updated[index] = _fetch_failed_record(key, error)
            outcome.fetch_failed += 1
            continue
        record = _resume_detail_record(page, key, criteria)
        updated[index] = record
        if record.status is DiscoveryStatus.COMPLETE:
            outcome.complete += 1
        elif record.status is DiscoveryStatus.INCOMPLETE:
            outcome.incomplete += 1
        elif record.status is DiscoveryStatus.REJECTED:
            outcome.rejected += 1
        elif record.status is DiscoveryStatus.QUARANTINED:
            outcome.quarantined += 1
    # Assign the finished inventory only after all in-place updates, so the
    # validated snapshot reflects every replacement.
    outcome.records = list(updated)
    return outcome


def build_criteria(args: argparse.Namespace) -> InvestmentCriteria:
    locations = [args.city, *(loc for loc in args.location if loc != args.city)]
    return InvestmentCriteria(
        locations=locations,
        maximum_purchase_price=Money(amount=args.budget, currency="EUR"),
        property_types=[args.property_type],
        minimum_room_count=args.rooms,
        minimum_living_area_sqm=args.min_area,
        strategy="buy_to_let",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="propertyscout.discovery_resume",
        description=(
            "Resume the discovery pipeline from an existing CSV inventory: "
            "re-fetch budget-exhausted individual listings via the keyless "
            "Keenable fetch endpoint and write an updated CSV copy. The "
            "source CSV is never modified."
        ),
    )
    parser.add_argument("--inventory", required=True, help="Existing discovery CSV")
    parser.add_argument(
        "--output", required=True, help="New CSV file for the updated inventory"
    )
    parser.add_argument("--city", required=True, help="Primary target city, e.g. Düsseldorf")
    parser.add_argument(
        "--location",
        action="append",
        default=[],
        help="Additional accepted target area, e.g. Meerbusch (repeatable)",
    )
    parser.add_argument("--budget", type=float, required=True, help="Maximum EUR price")
    parser.add_argument(
        "--property-type", default="apartment", help="Property type keyword (default: apartment)"
    )
    parser.add_argument("--rooms", type=float, default=None, help="Minimum room count")
    parser.add_argument(
        "--min-area", type=float, default=None, help="Minimum living area (m²)"
    )
    parser.add_argument(
        "--detail-fetch-budget",
        type=int,
        default=DEFAULT_DETAIL_FETCH_BUDGET,
        help="Hard limit of keyless fetch attempts (default: 20)",
    )
    parser.add_argument(
        "--immobilo-limit", type=int, default=PORTAL_BATCH_LIMITS["immobilo"]
    )
    parser.add_argument(
        "--kleinanzeigen-limit", type=int, default=PORTAL_BATCH_LIMITS["kleinanzeigen"]
    )
    parser.add_argument(
        "--immoportal-limit", type=int, default=PORTAL_BATCH_LIMITS["immoportal.com"]
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Select and report candidates without any fetch and without writing output",
    )
    return parser


def _remaining_summary(selection: ResumeSelection) -> str:
    by_portal = ", ".join(
        f"{portal}={count}"
        for portal, count in sorted(selection.remaining_by_portal.items())
    )
    return (
        f"{selection.remaining_budget_exhausted} budget-exhausted candidate(s) "
        f"remain [{by_portal}; index pages={selection.remaining_index_pages}]"
    )


def _summary(outcome: ResumeOutcome) -> str:
    return (
        f"{outcome.fetches} fetch attempt(s): "
        f"complete={outcome.complete}, incomplete={outcome.incomplete}, "
        f"rejected={outcome.rejected}, quarantined={outcome.quarantined}, "
        f"fetch_failed={outcome.fetch_failed}, deferred={outcome.deferred}"
    )


def run_resume_cli(argv: list[str] | None, fetch_client: FetchClient | None = None) -> int:
    """Run the resume CLI; ``fetch_client`` is injectable for offline tests."""

    args = build_parser().parse_args(argv)
    inventory = Path(args.inventory)
    if not inventory.exists():
        print(f"error: inventory not found: {inventory}", file=sys.stderr)
        return 2
    records = read_inventory(inventory)
    limits = {
        "immobilo": args.immobilo_limit,
        "kleinanzeigen": args.kleinanzeigen_limit,
        "immoportal.com": args.immoportal_limit,
    }
    selection = select_resume_candidates(records, limits)
    criteria = build_criteria(args)
    print(f"selected {len(selection.selected)} candidate(s):")
    for url in selection.selected:
        print(f"  {url}")
    if selection.excluded_below_area:
        print(
            f"excluded {len(selection.excluded_below_area)} below-"
            f"{DEFAULT_MINIMUM_AREA:g} m² candidate(s) (slug evidence)",
            file=sys.stderr,
        )
    if selection.excluded_likely_duplicates:
        print(
            f"skipped {len(selection.excluded_likely_duplicates)} likely "
            "syndicated duplicate(s) of validated listings",
            file=sys.stderr,
        )
    if selection.retained_uncertain_duplicates:
        print(
            f"retained {len(selection.retained_uncertain_duplicates)} uncertain "
            "duplicate(s) for later review",
            file=sys.stderr,
        )
    print(_remaining_summary(selection), file=sys.stderr)
    if args.dry_run:
        print("dry-run: no fetches performed, no output written", file=sys.stderr)
        return 0
    if fetch_client is None:
        fetch_client = KeenableFetch(api_key=SecretStr(""), timeout=30)
    outcome = resume_inventory(
        records, selection, criteria, fetch_client, args.detail_fetch_budget
    )
    Path(args.output).write_text(csv_text(outcome.records), encoding="utf-8")
    print(
        f"{args.detail_fetch_budget} fetch budget; {_summary(outcome)}; "
        f"inventory written to {args.output}",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_resume_cli(argv)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())




