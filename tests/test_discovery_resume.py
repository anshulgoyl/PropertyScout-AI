"""Offline tests for the discovery CSV resume capability."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from propertyscout.discovery import CSV_COLUMNS, DiscoveryStatus
from propertyscout.discovery_resume import (
    PORTAL_BATCH_LIMITS,
    DuplicateFlag,
    read_inventory,
    resume_inventory,
    run_resume_cli,
    select_resume_candidates,
)
from propertyscout.schemas import InvestmentCriteria, Money

FIXTURES = Path(__file__).parent / "fixtures"
INVENTORY = Path(__file__).parent.parent / "discovery_duesseldorf.csv"

YR_GXVYGF = (
    "https://www.yourimmo.de/immobilien/"
    "genehmigter-dg-rohling-in-duesseldorf-rath-50-5-m2-nur-69-000-eu-GXVYGF"
)
YR_H5RC5T = (
    "https://www.yourimmo.de/immobilien/"
    "2-zimmer-wohnung-in-duesseldorf-ihre-immobilienchance-ohne-maklerprovision-H5RC5T"
)
IM_GXVYGF = (
    "https://www.immobilo.de/immobilien/"
    "genehmigter-dg-rohling-in-duesseldorf-rath-50-5-m2-nur-69-000-eu-GXVYGF"
)
IM_H5NPW4 = (
    "https://www.immobilo.de/immobilien/"
    "2-zimmer-wohnung-in-duesseldorf-ihre-immobilienchance-ohne-maklerprovision-H5NPW4"
)
IM_GXP2N8 = (
    "https://www.immobilo.de/immobilien/"
    "duesseldorf-d-zoo-moebl-2-zi-etw-ruhig-und-zentral-in-einkaufsstrasse-"
    "ca-40qm-wfl-8qm-keller-GXP2N8"
)
IM_GXP2M3 = (
    "https://www.immobilo.de/immobilien/"
    "duesseldorf-d-zoo-moebl-2-zi-etw-ruhig-und-zentral-in-einkaufsstrasse-"
    "ca-40qm-wfl-8qm-keller-GXP2M3"
)
IMMOBILO_SELECTED = [
    f"https://www.immobilo.de/immobilien/wohnung-in-duesseldorf-{token}"
    for token in (
        "eigentumswohnung-52-qm-in-der-uhlandstrasse-H4L8B3",
        "gemuetliche-2-zimmer-wohnung-mit-aufzug-H4VFJW",
        "preisreduzierung-jetzt-gepflegte-2-zimmer-wohnung-H4QS9J",
        "provisionsfrei-sanierte-2-zimmer-wohnung-H5N8Z7",
        "2-zimmer-wohnung-duesseldorf-provisionsfrei-H5NY2T",
        "ideal-aufgeteilte-2-zimmer-wohnung-mit-aufzug-GZGG9N",
        "helle-gut-geschnittene-2-zimmer-wohnung-H3S6XF",
        "ideal-fuer-kapitalanleger-gepflegte-2-zimmer-H6DC42",
        "open-house-after-work-grunerstrasse-H44NJ6",
        "vermietungssichere-zwei-zimmer-wohnung-H359VX",
        "idealer-grundriss-renovierte-2-zi-etw-GZ665Z",
        "perfekt-fuer-singles-paare-rueckzug-GSCY3F",
    )
]
KA_SELECTED = [
    (
        "https://www.kleinanzeigen.de/s-anzeige/"
        "besonderes-wohnerlebnis-in-rheinnaehe-2-zimmer-wohnung-mit-terrasse-und-garten/"
        "3510797090-196-29985"
    ),
    (
        "https://www.kleinanzeigen.de/s-anzeige/"
        "wohnen-im-gruenen-grosszuegige-2-zimmer-wohnung-mit-balkon-und-aufzug/"
        "3535791443-196-29967"
    ),
    (
        "https://www.kleinanzeigen.de/s-anzeige/"
        "attraktive-city-wohnung-an-der-kunsthalle-beste-infrastruktur/"
        "3487617970-196-2089"
    ),
    (
        "https://www.kleinanzeigen.de/s-anzeige/"
        "helles-penthouse-mit-zwei-terrassen-in-duesseldorf-derendorf/"
        "3529083046-196-29943"
    ),
    (
        "https://www.kleinanzeigen.de/s-anzeige/"
        "urbane-oase-in-unterbilk-modernes-wohnen-direkt-am-medienhafen/"
        "3542479138-196-29963"
    ),
]
KA_AREA = (
    "https://www.kleinanzeigen.de/s-anzeige/"
    "d-zoo-moebl-2-zi-etw-ruhig-und-zentral-in-einkaufsstrasse-ca-40qm-wfl-8qm-keller/"
    "3431582416-196-2099"
)
KA_IN_BATCH_TWIN = (
    "https://www.kleinanzeigen.de/s-anzeige/"
    "besonderes-wohnerlebnis-in-rheinnaehe-2-zimmer-wohnung-mit-terrasse-und-garten/"
    "3510797999-196-29985"
)
IMMO_SELECTED = [
    f"https://www.immoportal.com/expose/{identifier}"
    for identifier in ("111152", "153989", "119928")
]
IMMO_EXTRA = "https://www.immoportal.com/expose/149297"
KA_INDEX = "https://www.kleinanzeigen.de/s-wohnung-kaufen/duesseldorf/bilk/k0c196l2068"
DETAIL_REASON = "detail-fetch-budget-exhausted"
INDEX_REASON = "index-fetch-budget-exhausted"


def duesseldorf_criteria() -> InvestmentCriteria:
    return InvestmentCriteria(
        locations=["Düsseldorf", "Meerbusch"],
        maximum_purchase_price=Money(amount=551_001, currency="EUR"),
        property_types=["apartment"],
        minimum_room_count=2,
        minimum_living_area_sqm=50,
        strategy="buy_to_let",
    )


def row(
    url: str, portal: str, status: str, reasons: tuple[str, ...] = (), **extra: str
) -> dict[str, str]:
    base = {
        "url": url,
        "portal": portal,
        "portals": "[]",
        "title": "",
        "city": "",
        "postal_code": "",
        "price_eur": "",
        "area_m2": "",
        "rooms": "",
        "condition": "",
        "status": status,
        "matches_criteria": "false",
        "reasons": ";".join(reasons),
        "missing": "",
        "source_references": "",
        "possible_duplicates": "",
        "merged_from": "",
    }
    base.update({key: str(value) for key, value in extra.items()})
    return base


def synthetic_inventory() -> list[dict[str, str]]:
    rows = [
        row(YR_GXVYGF, "yourimmo", "complete", title="DG-Rohling"),
        row(YR_H5RC5T, "yourimmo", "complete", title="2-Zimmer-Wohnung"),
        row(IM_GXVYGF, "immobilo", "budget_exhausted", (DETAIL_REASON,)),
        row(IM_H5NPW4, "immobilo", "budget_exhausted", (DETAIL_REASON,)),
        row(IM_GXP2N8, "immobilo", "budget_exhausted", (DETAIL_REASON,)),
        row(IM_GXP2M3, "immobilo", "budget_exhausted", (DETAIL_REASON,)),
    ]
    rows.extend(
        row(url, "immobilo", "budget_exhausted", (DETAIL_REASON,))
        for url in IMMOBILO_SELECTED
    )
    rows.extend(
        row(url, "kleinanzeigen", "budget_exhausted", (DETAIL_REASON,))
        for url in (*KA_SELECTED, KA_AREA, KA_IN_BATCH_TWIN)
    )
    rows.extend(
        row(url, "immoportal.com", "budget_exhausted", (DETAIL_REASON,))
        for url in (*IMMO_SELECTED, IMMO_EXTRA)
    )
    rows.append(row(KA_INDEX, "kleinanzeigen", "budget_exhausted", (INDEX_REASON,)))
    return rows


def write_inventory(path: Path, rows: list[dict[str, str]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CSV_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


class FakeFetchClient:
    """Replays captured pages; unmapped or failing URLs never retry."""

    def __init__(self, pages: dict[str, object]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def invoke(self, tool_input: dict):
        url = tool_input["url"]
        self.calls.append(url)
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        return page


def md_page(url: str, title: str, content: str) -> dict:
    return {"url": url, "title": title, "content": content}


def test_read_inventory_round_trips_discovery_columns(tmp_path: Path) -> None:
    path = tmp_path / "inventory.csv"
    write_inventory(
        path,
        [
            row(
                YR_GXVYGF,
                "yourimmo",
                "complete",
                title="DG-Rohling",
                city="Düsseldorf",
                postal_code="40472",
                price_eur="69000",
                area_m2="50.5",
                rooms="2",
                matches_criteria="true",
            )
        ],
    )
    records = read_inventory(path)
    assert len(records) == 1
    record = records[0]
    assert record.status is DiscoveryStatus.COMPLETE
    assert record.price_eur == 69000
    assert record.area_m2 == 50.5
    assert record.rooms == 2
    assert record.postal_code == "40472"
    assert record.matches_criteria is True
    assert record.portals == []


@pytest.mark.skipif(not INVENTORY.exists(), reason="inventory CSV not present")
def test_read_inventory_parses_existing_duesseldorf_inventory() -> None:
    records = read_inventory(INVENTORY)
    assert len(records) == 91
    exhausted = [r for r in records if r.status is DiscoveryStatus.BUDGET_EXHAUSTED]
    assert len(exhausted) == 56
    assert sum(1 for r in exhausted if DETAIL_REASON in r.reasons) == 51
    assert sum(1 for r in exhausted if INDEX_REASON in r.reasons) == 5
    untera = next(record for record in records if "untera.io" in record.url)
    assert untera.price_eur == 515000
    assert untera.rooms == 3
    assert untera.area_m2 == 126
    assert untera.matches_criteria is True


def test_selection_applies_limits_and_exclusions(tmp_path: Path) -> None:
    path = tmp_path / "inventory.csv"
    rows = synthetic_inventory()
    write_inventory(path, rows)
    records = read_inventory(path)
    selection = select_resume_candidates(records)

    assert len(selection.selected) == 20
    assert selection.selected == [*IMMOBILO_SELECTED, *KA_SELECTED, *IMMO_SELECTED]
    assert selection.excluded_likely_duplicates == [IM_GXVYGF]
    assert selection.retained_uncertain_duplicates == [IM_H5NPW4, KA_IN_BATCH_TWIN]
    assert selection.excluded_below_area == [IM_GXP2N8, IM_GXP2M3, KA_AREA]
    assert selection.budget_exhausted_total == 28
    assert selection.remaining_budget_exhausted == 8
    assert selection.remaining_by_portal == {
        "immobilo": 4,
        "kleinanzeigen": 2,
        "immoportal.com": 1,
    }
    assert selection.remaining_index_pages == 1
    assert selection.duplicate_flags == [
        DuplicateFlag(candidate=IM_GXVYGF, validated=YR_GXVYGF),
        DuplicateFlag(candidate=IM_H5NPW4, validated=YR_H5RC5T),
    ]


def test_selection_never_picks_index_pages(tmp_path: Path) -> None:
    path = tmp_path / "inventory.csv"
    rows = [
        row(KA_INDEX, "kleinanzeigen", "budget_exhausted", (INDEX_REASON,)),
        row(IMMO_SELECTED[0], "immoportal.com", "budget_exhausted", (DETAIL_REASON,)),
    ]
    write_inventory(path, rows)
    selection = select_resume_candidates(read_inventory(path))
    assert selection.selected == [IMMO_SELECTED[0]]
    assert selection.remaining_index_pages == 1


COMPLETE_PAGE = md_page(
    IMMOBILO_SELECTED[0],
    "Gemütliche 2-Zimmer-Wohnung mit Aufzug und zwei Loggien in Düsseldorf-Pempelfort",
    "Nordstr. 20, 40211 Düsseldorf\n\n 249.000,00 €\nKaufpreis\n\n 2\nZimmer\n"
    " 54 m2\nFläche\n\nBalkon und Aufzug\n",
)
INCOMPLETE_PAGE = md_page(
    IMMOBILO_SELECTED[1],
    "2-Zimmer-Eigentumswohnung in Düsseldorf-Derendorf",
    "Kaufpreis: 199.000 €\n2 Zimmer\n40470 Düsseldorf\n",
)
RENTAL_PAGE = md_page(
    IMMOBILO_SELECTED[2],
    "2-Zimmer-Wohnung in Düsseldorf",
    "Wohnung zur Miete\nKaltmiete 900 €\n40233 Düsseldorf\n2 Zimmer\n50 m2\n",
)
MULTI_PAGE = md_page(
    KA_SELECTED[0],
    "Wohnungen kaufen in Düsseldorf",
    "Wohnung A: Kaufpreis 149.000 € in 40210 Düsseldorf\n"
    "Wohnung B: Kaufpreis 259.000 € in 40235 Düsseldorf\n",
)


def pages_for_candidates() -> dict[str, object]:
    return {
        IMMOBILO_SELECTED[0]: COMPLETE_PAGE,
        IMMOBILO_SELECTED[1]: INCOMPLETE_PAGE,
        IMMOBILO_SELECTED[2]: RENTAL_PAGE,
        KA_SELECTED[0]: MULTI_PAGE,
        IMMO_SELECTED[0]: RuntimeError("blocked"),
    }


def test_resume_updates_statuses_with_same_validation_rules(tmp_path: Path) -> None:
    path = tmp_path / "inventory.csv"
    rows = synthetic_inventory()
    write_inventory(path, rows)
    records = read_inventory(path)
    selection = select_resume_candidates(
        records,
        {"immobilo": 3, "kleinanzeigen": 1, "immoportal.com": 1},
    )
    fetch = FakeFetchClient(pages_for_candidates())
    outcome = resume_inventory(records, selection, duesseldorf_criteria(), fetch)

    assert outcome.fetches == 5
    assert outcome.complete == 1
    assert outcome.incomplete == 1
    assert outcome.rejected == 1
    assert outcome.quarantined == 1
    assert outcome.fetch_failed == 1
    assert fetch.calls == selection.selected  # one attempt per URL, in order

    by_url = {record.url: record for record in outcome.records}
    complete = by_url[IMMOBILO_SELECTED[0]]
    assert complete.status is DiscoveryStatus.COMPLETE
    assert complete.price_eur == 249000
    assert complete.area_m2 == 54
    assert complete.rooms == 2
    assert complete.city == "Düsseldorf"
    assert complete.postal_code == "40211"
    assert complete.matches_criteria is True
    assert complete.portal == "immobilo"
    assert by_url[IMMOBILO_SELECTED[1]].status is DiscoveryStatus.INCOMPLETE
    assert by_url[IMMOBILO_SELECTED[1]].missing == ["living_area"]
    assert by_url[IMMOBILO_SELECTED[1]].matches_criteria is False
    rejected = by_url[IMMOBILO_SELECTED[2]]
    assert rejected.status is DiscoveryStatus.REJECTED
    assert "rental-intent" in rejected.reasons
    assert by_url[KA_SELECTED[0]].status is DiscoveryStatus.QUARANTINED
    failed = by_url[IMMO_SELECTED[0]]
    assert failed.status is DiscoveryStatus.FETCH_FAILED
    assert failed.reasons == ["fetch-error", "RuntimeError"]

    # All non-fetched records are preserved untouched.
    assert by_url[YR_GXVYGF].status is DiscoveryStatus.COMPLETE
    assert by_url[KA_INDEX].status is DiscoveryStatus.BUDGET_EXHAUSTED


def test_resume_flags_duplicates_without_merging(tmp_path: Path) -> None:
    path = tmp_path / "inventory.csv"
    rows = synthetic_inventory()
    write_inventory(path, rows)
    records = read_inventory(path)
    selection = select_resume_candidates(
        records, {"immobilo": 1, "kleinanzeigen": 0, "immoportal.com": 0}
    )
    fetch = FakeFetchClient({IMMOBILO_SELECTED[0]: COMPLETE_PAGE})
    outcome = resume_inventory(records, selection, duesseldorf_criteria(), fetch)

    by_url = {record.url: record for record in outcome.records}
    # Uncertain duplicates are flagged, never merged, and kept for review.
    assert by_url[IM_GXVYGF].status is DiscoveryStatus.BUDGET_EXHAUSTED
    assert by_url[IM_GXVYGF].possible_duplicates == [YR_GXVYGF]
    assert by_url[IM_H5NPW4].possible_duplicates == [YR_H5RC5T]
    assert by_url[YR_GXVYGF].possible_duplicates == []
    assert by_url[YR_GXVYGF].merged_from == []


def test_resume_enforces_budget_without_retries(tmp_path: Path) -> None:
    path = tmp_path / "inventory.csv"
    rows = synthetic_inventory()
    write_inventory(path, rows)
    records = read_inventory(path)
    selection = select_resume_candidates(
        records,
        {"immobilo": 3, "kleinanzeigen": 1, "immoportal.com": 1},
    )
    fetch = FakeFetchClient(pages_for_candidates())
    outcome = resume_inventory(
        records, selection, duesseldorf_criteria(), fetch, detail_fetch_budget=3
    )

    assert outcome.fetches == 3
    assert outcome.deferred == 2
    assert fetch.calls == selection.selected[:3]
    by_url = {record.url: record for record in outcome.records}
    assert by_url[IMMO_SELECTED[0]].status is DiscoveryStatus.BUDGET_EXHAUSTED
    assert by_url[IMMO_SELECTED[0]].reasons == [DETAIL_REASON]


def test_resume_parses_captured_immobilo_fixture_page(tmp_path: Path) -> None:
    path = tmp_path / "inventory.csv"
    rows = synthetic_inventory()
    write_inventory(path, rows)
    records = read_inventory(path)
    selection = select_resume_candidates(
        records, {"immobilo": 1, "kleinanzeigen": 0, "immoportal.com": 0}
    )
    fixture = FIXTURES / "detail_immobilo_kapitalanlage.md"
    content = fixture.read_text(encoding="utf-8")
    fetch = FakeFetchClient(
        {IMMOBILO_SELECTED[0]: md_page(IMMOBILO_SELECTED[0], fixture.stem, content)}
    )
    outcome = resume_inventory(records, selection, duesseldorf_criteria(), fetch)

    record = next(r for r in outcome.records if r.url == IMMOBILO_SELECTED[0])
    assert record.status is DiscoveryStatus.COMPLETE
    assert record.price_eur == 144500
    assert record.rooms == 1
    assert record.area_m2 == 44.86
    assert record.postal_code == "40597"
    assert record.matches_criteria is False  # 1 room, 44.86 m² below criteria
    assert record.source_references  # regionalimmobilien24 expose reference


def test_resume_cli_writes_output_and_preserves_source(tmp_path: Path, capsys) -> None:
    source = tmp_path / "inventory.csv"
    write_inventory(source, synthetic_inventory())
    before = source.read_bytes()
    output = tmp_path / "inventory_resume1.csv"
    fetch = FakeFetchClient(pages_for_candidates())
    exit_code = run_resume_cli(
        [
            "--inventory", str(source),
            "--output", str(output),
            "--city", "Düsseldorf", "--location", "Meerbusch",
            "--budget", "551001", "--rooms", "2", "--min-area", "50",
            "--immobilo-limit", "3", "--kleinanzeigen-limit", "1",
            "--immoportal-limit", "1",
        ],
        fetch_client=fetch,
    )
    assert exit_code == 0
    assert source.read_bytes() == before  # original CSV untouched
    assert len(fetch.calls) == 5
    updated = list(csv.DictReader(output.read_text(encoding="utf-8").splitlines()))
    assert len(updated) == 30  # all records preserved
    by_url = {r["url"]: r for r in updated}
    assert by_url[IMMOBILO_SELECTED[0]]["status"] == "complete"
    assert by_url[IMMOBILO_SELECTED[0]]["matches_criteria"] == "true"
    assert by_url[IM_GXVYGF]["status"] == "budget_exhausted"
    assert by_url[IM_GXVYGF]["possible_duplicates"] == YR_GXVYGF
    assert by_url[IMMO_SELECTED[0]]["status"] == "fetch_failed"
    assert "fetch attempt(s)" in capsys.readouterr().err


def test_resume_cli_dry_run_makes_no_requests(tmp_path: Path, capsys) -> None:
    source = tmp_path / "inventory.csv"
    write_inventory(source, synthetic_inventory())
    output = tmp_path / "unused.csv"
    fetch = FakeFetchClient({})
    exit_code = run_resume_cli(
        [
            "--inventory", str(source),
            "--output", str(output),
            "--city", "Düsseldorf", "--location", "Meerbusch",
            "--budget", "551001", "--rooms", "2", "--min-area", "50",
            "--dry-run",
        ],
        fetch_client=fetch,
    )
    assert exit_code == 0
    assert fetch.calls == []
    assert not output.exists()
    stdout = capsys.readouterr().out
    assert "selected 20 candidate(s):" in stdout
    assert IMMOBILO_SELECTED[0] in stdout
    assert KA_SELECTED[0] in stdout
    assert IMMO_SELECTED[0] in stdout


def test_resume_cli_reports_missing_inventory(tmp_path: Path, capsys) -> None:
    exit_code = run_resume_cli(
        [
            "--inventory", str(tmp_path / "missing.csv"),
            "--output", str(tmp_path / "unused.csv"),
            "--city", "Düsseldorf", "--budget", "551001",
        ],
        fetch_client=FakeFetchClient({}),
    )
    assert exit_code == 2
    assert "inventory not found" in capsys.readouterr().err


def test_build_parser_defaults_match_portal_batch_limits() -> None:
    from propertyscout.discovery_resume import build_criteria, build_parser

    args = build_parser().parse_args(
        [
            "--inventory", "in.csv",
            "--output", "out.csv",
            "--city", "Düsseldorf",
            "--budget", "551001",
        ]
    )
    assert args.detail_fetch_budget == 20
    assert args.immobilo_limit == PORTAL_BATCH_LIMITS["immobilo"] == 12
    assert args.kleinanzeigen_limit == PORTAL_BATCH_LIMITS["kleinanzeigen"] == 5
    assert args.immoportal_limit == PORTAL_BATCH_LIMITS["immoportal.com"] == 3
    criteria = build_criteria(args)
    assert criteria.locations == ["Düsseldorf"]
    assert criteria.maximum_purchase_price.amount == 551001






