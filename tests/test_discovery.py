"""Offline tests for the standalone Keenable property discovery pipeline."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from propertyscout.discovery import (
    CSV_COLUMNS,
    DEFAULT_DETAIL_FETCH_BUDGET,
    DEFAULT_INDEX_FETCH_BUDGET,
    DEFAULT_SEARCH_BUDGET,
    DiscoveryError,
    DiscoveryService,
    DiscoveryStatus,
    _process_index_page,
    build_criteria,
    build_parser,
    csv_text,
    extract_listing_links,
    run_cli,
    trim_main_listing,
)
from propertyscout.market_search import search_queries
from propertyscout.schemas import InvestmentCriteria, Money

FIXTURES = Path(__file__).parent / "fixtures"

def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def benrath_criteria() -> InvestmentCriteria:
    return InvestmentCriteria(
        locations=["Düsseldorf"],
        postal_codes=["40597"],
        maximum_purchase_price=Money(amount=300_000, currency="EUR"),
        property_types=["apartment"],
        strategy="buy_to_let",
    )


INDEX_PAGES = {
    "https://www.kleinanzeigen.de/s-wohnung-kaufen/benrath/2-zimmer-wohnung/k0c196l16753": (
        "index_kleinanzeigen_benrath.md",
        "2 Zimmer Wohnung, Eigentumswohnung kaufen in Benrath Düsseldorf | kleinanzeigen.de",
    ),
    "https://www.immobilo.de/kaufen/wohnung/duesseldorf/2-zimmer": (
        "index_immobilo_benrath.md",
        "Wohnung kaufen in Düsseldorf-Benrath - immobilo",
    ),
    "https://www.yourimmo.de/immobilien/wohnung-kaufen-duesseldorf-benrath": (
        "index_yourimmo_benrath.md",
        "Wohnung kaufen in Düsseldorf-Benrath - yourimmo.de",
    ),
    "https://www.meinestadt.de/duesseldorf-benrath/immobilien": (
        "index_meinestadt_benrath.md",
        "Wohnung kaufen Düsseldorf-Benrath | meinestadt.de",
    ),
}

DETAIL_PAGES = {
    "toplage-benrath-2-zimmer-wohnung-mit-stellplatz": "detail_kleinanzeigen_toplage.md",
    "kapitalanlage-duesseldorf-benrath-eg-mit-garten-0-eu-eigenkapital": (
        "detail_immobilo_kapitalanlage.md"
    ),
    "barrierefreie-eigentumswohnung-im-2-og-mit-balkon-zum-innenhof": (
        "detail_immobilo_barrierefrei.md"
    ),
    "solide-kapitalanlage-in-duesseldorf-benrath-H4SKQ7": (
        "detail_yourimmo_solide_kapitalanlage.md"
    ),
    "frei-ab-01-01-2027-sonnige-3-raum-erdgeschosswohnung-zentral-in-d-benrath-provisionsfrei-H4SJHG": (
        "detail_yourimmo_frei_ab_2027.md"
    ),
}


class FakeSearchClient:
    """Returns the same captured results for every configured query."""

    def __init__(self, results: list[dict] | None = None, fail: bool = False) -> None:
        self.calls = 0
        self.queries: list[str] = []
        self._results = results or []
        self._fail = fail

    def invoke(self, tool_input: dict):
        self.calls += 1
        self.queries.append(tool_input["query"])
        if self._fail:
            raise RuntimeError("search down")
        return self._results


class FakeFetchClient:
    """Replays captured index and detail pages; unmapped URLs fail once."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def invoke(self, tool_input: dict):
        url = tool_input["url"]
        self.calls.append(url)
        if url in INDEX_PAGES:
            name, _ = INDEX_PAGES[url]
            return page(FIXTURES / name, url)
        for fragment, name in DETAIL_PAGES.items():
            if fragment in url:
                return page(FIXTURES / name, url)
        return None

    @property
    def call_count(self) -> int:
        return len(self.calls)


def page(path: Path, url: str) -> dict:
    content = path.read_text(encoding="utf-8")
    title = content.splitlines()[0].removeprefix("# ").strip()
    return {"url": url, "title": title, "content": content}


def index_result(url: str, title: str) -> dict:
    _, index_title = INDEX_PAGES[url]
    return {
        "title": title or index_title,
        "url": url,
        "snippet": "Eigentumswohnung kaufen in Düsseldorf-Benrath",
    }


def replay_service(**kwargs) -> tuple[DiscoveryService, FakeFetchClient]:
    fetch = FakeFetchClient()
    search = FakeSearchClient(
        results=[index_result(url, "") for url in INDEX_PAGES],
    )
    service = DiscoveryService(search_client=search, fetch_client=fetch, **kwargs)
    return service, fetch


def record_by_fragment(run, fragment: str):
    matches = [r for r in run.records if fragment in r.url]
    assert len(matches) == 1, f"expected one record for {fragment!r}"
    return matches[0]


def test_index_pages_extract_expected_children() -> None:
    counts = {
        "index_kleinanzeigen_benrath.md": 15,
        "index_immobilo_benrath.md": 11,
        "index_yourimmo_benrath.md": 20,
        "index_meinestadt_benrath.md": 20,
    }
    for name, expected in counts.items():
        url = next(u for u, (n, _) in INDEX_PAGES.items() if n == name)
        links = extract_listing_links(fixture(name), url)
        assert len(links) == expected, name
    kleinanzeigen = extract_listing_links(
        fixture("index_kleinanzeigen_benrath.md"),
        "https://www.kleinanzeigen.de/s-wohnung-kaufen/benrath/2-zimmer-wohnung/k0c196l16753",
    )
    assert all("/s-anzeige/" in link for link in kleinanzeigen)
    assert all(link.startswith("https://www.kleinanzeigen.de") for link in kleinanzeigen)
    meinestadt = extract_listing_links(
        fixture("index_meinestadt_benrath.md"),
        "https://www.meinestadt.de/duesseldorf-benrath/immobilien",
    )
    assert all("expose/" in link for link in meinestadt)
    # 66 unique child listing URLs across the four captured index pages.
    total = {
        link
        for name in counts
        for link in extract_listing_links(
            fixture(name), next(u for u, (n, _) in INDEX_PAGES.items() if n == name)
        )
    }
    assert len(total) == 66


def test_detail_fixtures_parse_into_complete_records() -> None:
    service, _ = replay_service(detail_fetch_budget=70)
    run = service.run(benrath_criteria())
    complete = [r for r in run.records if r.status is DiscoveryStatus.COMPLETE]
    assert len(complete) == 5
    expected = {
        "toplage-benrath-2-zimmer-wohnung-mit-stellplatz": (
            200000.0, 49.0, 2.0, "kleinanzeigen",
        ),
        "kapitalanlage-duesseldorf-benrath-eg-mit-garten-0-eu-eigenkapital": (
            144500.0, 44.86, 1.0, "immobilo",
        ),
        "barrierefreie-eigentumswohnung-im-2-og-mit-balkon-zum-innenhof-H2X829": (
            639900.0, 103.85, 4.0, "immobilo",
        ),
        "solide-kapitalanlage-in-duesseldorf-benrath-H4SKQ7": (
            265000.0, 68.0, 3.0, "yourimmo",
        ),
        "frei-ab-01-01-2027-sonnige-3-raum-erdgeschosswohnung-zentral-in-d-benrath-provisionsfrei-H4SJHG": (
            259400.0, 68.07, 3.5, "yourimmo",
        ),
    }
    for fragment, (price, area, rooms, portal) in expected.items():
        record = record_by_fragment(run, fragment)
        assert record.status is DiscoveryStatus.COMPLETE, fragment
        assert record.price_eur == price, fragment
        assert record.area_m2 == area, fragment
        assert record.rooms == rooms, fragment
        assert record.postal_code == "40597", fragment
        assert record.city == "Düsseldorf", fragment
        assert record.portal == portal, fragment


def test_replay_runs_all_stages_within_budgets() -> None:
    service, fetch = replay_service(detail_fetch_budget=70)
    run = service.run(benrath_criteria())
    assert run.search_calls == min(service._search_budget, len(search_queries(benrath_criteria())))
    assert run.queries_run[0].startswith("Eigentumswohnung Düsseldorf kaufen")
    assert run.index_fetches == 4  # one per captured index page
    assert run.detail_fetches == 66  # every unique child URL fetched once
    assert fetch.call_count == 66 + 4
    statuses: dict = {}
    for record in run.records:
        statuses[record.status] = statuses.get(record.status, 0) + 1
    assert statuses == {
        DiscoveryStatus.COMPLETE: 5,
        DiscoveryStatus.INDEX_PAGE: 4,
        DiscoveryStatus.FETCH_FAILED: 61,
    }
    assert not run.search_errors
    index_records = [r for r in run.records if r.status is DiscoveryStatus.INDEX_PAGE]
    assert sorted(r.child_count for r in index_records) == [11, 15, 20, 20]


def test_matches_criteria_flags_budget_and_criteria() -> None:
    service, _ = replay_service(detail_fetch_budget=70)
    run = service.run(benrath_criteria())
    toplage = record_by_fragment(run, "toplage-benrath-2-zimmer-wohnung")
    assert toplage.matches_criteria is True  # 200000 <= 300000
    barrierefrei = record_by_fragment(run, "H2X829")
    assert barrierefrei.matches_criteria is False  # 639900 > 300000
    failed = [r for r in run.records if r.status is DiscoveryStatus.FETCH_FAILED]
    assert all(not r.matches_criteria for r in failed)


def test_trim_main_listing_never_mixes_other_properties() -> None:
    main = trim_main_listing(fixture("detail_kleinanzeigen_toplage.md"))
    assert "Das könnte dich auch interessieren" not in main
    assert "Andere Anzeigen des Anbieters" not in main
    assert "200.000 € VB" in main
    assert "220.000 €" not in main  # a similar listing's price stays out
    assert "40591" not in main  # the vendor's other ad in Holthausen stays out


def test_source_references_are_extracted_from_detail_pages() -> None:
    service, _ = replay_service(detail_fetch_budget=70)
    run = service.run(benrath_criteria())
    frei = record_by_fragment(run, "H4SJHG")
    assert frei.source_references == [
        "https://www.immowelt.de/expose/14b14aac-2c76-4e34-a3ba-212a5eeee739"
    ]
    toplage = record_by_fragment(run, "toplage-benrath-2-zimmer-wohnung")
    assert toplage.source_references == []  # kleinanzeigen ads carry no expose ref


def test_incomplete_records_are_preserved() -> None:
    search = FakeSearchClient(
        results=[
            {
                "title": "Wohnung kaufen in Düsseldorf-Benrath | example.de",
                "url": "https://www.example.de/immobilien/eigentumswohnung-benrath-HABC12",
                "snippet": "Eigentumswohnung kaufen in Düsseldorf-Benrath",
            }
        ]
    )

    class OneShotFetch(FakeFetchClient):
        def invoke(self, tool_input):
            url = tool_input["url"]
            self.calls.append(url)
            if "HABC12" in url:
                return {
                    "url": url,
                    "title": "Eigentumswohnung Benrath",
                    "content": (
                        "# Eigentumswohnung Benrath\n\n 40597 Düsseldorf\n\n"
                        " 189.000 €\nKaufpreis\n\n 55 m2\nFläche\n"
                    ),
                }
            return None

    service = DiscoveryService(search_client=search, fetch_client=OneShotFetch())
    run = service.run(benrath_criteria())
    record = record_by_fragment(run, "HABC12")
    assert record.status is DiscoveryStatus.INCOMPLETE
    assert record.missing == ["room_count"]
    assert record.matches_criteria is False


def test_search_budget_is_enforced_without_early_stopping() -> None:
    search = FakeSearchClient(results=[])
    fetch = FakeFetchClient()
    service = DiscoveryService(
        search_client=search, fetch_client=fetch, search_budget=2
    )
    service.run(benrath_criteria())
    assert search.calls == 2  # budget, not the 3 configured variants
    service = DiscoveryService(
        search_client=search, fetch_client=fetch, search_budget=10
    )
    service.run(benrath_criteria())
    #assert search.calls == 2 + 3  # all configured variants run despite earlier results
    assert search.calls == 2 + min(10, len(search_queries(benrath_criteria())))


def test_search_errors_are_recorded_not_retried() -> None:
    search = FakeSearchClient(fail=True)
    fetch = FakeFetchClient()
    service = DiscoveryService(search_client=search, fetch_client=fetch)
    run = service.run(benrath_criteria())
    # assert search.calls == 3  # one attempt per query, no retries
    assert search.calls == min(service._search_budget, len(search_queries(benrath_criteria())))
    # assert len(run.search_errors) == 3
    assert len(run.search_errors) == search.calls
    assert run.records == []


def test_fetch_budgets_are_hard_limits() -> None:
    service, fetch = replay_service(index_fetch_budget=2, detail_fetch_budget=3)
    run = service.run(benrath_criteria())
    assert run.index_fetches == 2
    assert run.detail_fetches == 3
    exhausted = [
        r for r in run.records if r.status is DiscoveryStatus.BUDGET_EXHAUSTED
    ]
    # 2 unfetched index pages + the 23 children of the 2 fetched ones.
    assert len(exhausted) == 25
    assert all("budget-exhausted" in r.reasons[0] for r in exhausted)
    assert fetch.call_count == 5


def test_same_url_fetched_once_across_queries() -> None:
    search = FakeSearchClient(results=[index_result(url, "") for url in INDEX_PAGES] * 2)
    fetch = FakeFetchClient()
    service = DiscoveryService(
        search_client=search, fetch_client=fetch, detail_fetch_budget=70
    )
    run = service.run(benrath_criteria())
    #assert run.cross_query_duplicates == 20  # 8 duplicated results per later query
    expected_duplicates = (
    len(INDEX_PAGES) * 2 * run.search_calls
    - len(INDEX_PAGES)
    )

    assert run.cross_query_duplicates == expected_duplicates

    assert fetch.call_count == 66 + 4  # no URL fetched twice


def test_authenticated_search_is_required_for_live_use(monkeypatch) -> None:
    monkeypatch.delenv("KEENABLE_API_KEY", raising=False)
    with pytest.raises(DiscoveryError, match="KEENABLE_API_KEY"):
        DiscoveryService()
    monkeypatch.setenv("KEENABLE_API_KEY", " test-key ")
    service = DiscoveryService()
    assert service is not None


_SHARED_EXPOSE = "https://www.immowelt.de/expose/14b14aac-2c76-4e34-a3ba-212a5eeee739"


def _two_child_index_results() -> FakeSearchClient:
    return FakeSearchClient(
        results=[
            {
                "title": "Wohnung kaufen in Düsseldorf-Benrath | example.de",
                "url": "https://www.example.de/immobilien/wohnung-kaufen-benrath",
                "snippet": "Eigentumswohnung kaufen in Düsseldorf-Benrath",
            }
        ]
    )


class TwoPortalFetch(FakeFetchClient):
    """An index page plus two listing pages referencing the same expose."""

    def invoke(self, tool_input: dict):
        url = tool_input["url"]
        self.calls.append(url)
        if "wohnung-kaufen-benrath" in url:
            return {
                "url": url,
                "title": "Wohnung kaufen in Düsseldorf-Benrath | example.de",
                "content": (
                    "# Wohnung kaufen in Düsseldorf-Benrath | example.de\n\n"
                    "- [Listing one](https://www.immobilo.de/immobilien/listing-one-HABC12)\n"
                    "- [Listing two](https://www.yourimmo.de/immobilien/listing-two-HXYZ34)\n"
                ),
            }
        if "HABC12" in url:
            return {
                "url": url,
                "title": "Kapitalanlage in Düsseldorf-Benrath",
                "content": (
                    "# Kapitalanlage in Düsseldorf-Benrath\n\n 40597 Düsseldorf\n\n"
                    " 189.000 €\nKaufpreis\n\n 2\nZimmer\n\n 55 m2\nFläche\n\n"
                    f"[ Weitere Informationen ]({_SHARED_EXPOSE}?utm_source=immobilo)\n"
                ),
            }
        if "HXYZ34" in url:
            return {
                "url": url,
                "title": "Kapitalanlage in Düsseldorf-Benrath",
                "content": (
                    "# Kapitalanlage in Düsseldorf-Benrath\n\n 40597 Düsseldorf\n\n"
                    " 189.000 €\nKaufpreis\n\n 2\nZimmer\n\n 55 m2\nFläche\n\n"
                    f"[ Weitere Informationen ]({_SHARED_EXPOSE}?utm_source=yourimmo)\n"
                ),
            }
        return None


def test_shared_reference_merges_cross_portal_records() -> None:
    fetch = TwoPortalFetch()
    service = DiscoveryService(
        search_client=_two_child_index_results(), fetch_client=fetch
    )
    run = service.run(benrath_criteria())
    complete = [r for r in run.records if r.status is DiscoveryStatus.COMPLETE]
    assert len(complete) == 1  # two portal records merged into one
    merged = complete[0]
    assert merged.portal == "immobilo"
    assert merged.portals == ["yourimmo"]
    assert len(merged.merged_from) == 1
    assert merged.source_references == [_SHARED_EXPOSE]


def test_same_attributes_without_reference_are_flagged_not_merged() -> None:
    class NoReferenceFetch(TwoPortalFetch):
        def invoke(self, tool_input: dict):
            page = super().invoke(tool_input)
            listing_url = tool_input["url"]
            if page is not None and ("HABC12" in listing_url or "HXYZ34" in listing_url):
                page = {**page, "content": page["content"].split("Weitere Informationen")[0]}
            return page

    fetch = NoReferenceFetch()
    service = DiscoveryService(
        search_client=_two_child_index_results(), fetch_client=fetch
    )
    run = service.run(benrath_criteria())
    complete = [r for r in run.records if r.status is DiscoveryStatus.COMPLETE]
    assert len(complete) == 2  # nothing merged without a verified reference
    assert all(not r.source_references for r in complete)
    first, second = complete
    assert second.url in first.possible_duplicates
    assert first.url in second.possible_duplicates


def test_csv_text_layout_and_values() -> None:
    service, _ = replay_service(detail_fetch_budget=70)
    run = service.run(benrath_criteria())
    text = csv_text(run.records)
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == list(CSV_COLUMNS)
    by_url = {row[0]: dict(zip(rows[0], row)) for row in rows[1:]}
    toplage = next(url for url in by_url if "toplage-benrath" in url)
    row = by_url[toplage]
    assert row["portal"] == "kleinanzeigen"
    assert row["status"] == "complete"
    assert row["price_eur"] == "200000"
    assert row["rooms"] == "2"
    assert row["area_m2"] == "49"
    assert row["matches_criteria"] == "true"
    frei = next(url for url in by_url if "H4SJHG" in url)
    assert by_url[frei]["rooms"] == "3.5"  # exact fractional room count preserved
    failed = [row for row in by_url.values() if row["status"] == "fetch_failed"]
    assert failed and all(row["reasons"] for row in failed)


def test_run_cli_writes_output_file(tmp_path, capsys) -> None:
    service, _ = replay_service()
    output = tmp_path / "discovery.csv"
    exit_code = run_cli(
        [
            "--city", "Düsseldorf", "--budget", "300000", "--postcode", "40597",
            "--output", str(output),
        ],
        service=service,
    )
    assert exit_code == 0
    text = output.read_text(encoding="utf-8")
    assert text.splitlines()[0] == ",".join(CSV_COLUMNS)
    assert len(text.splitlines()) > 10
    captured = capsys.readouterr()
    assert captured.out == ""  # CSV went to the file, not stdout
    assert "detail fetch(es)" in captured.err


def test_run_cli_prints_csv_to_stdout(capsys) -> None:
    service, _ = replay_service()
    exit_code = run_cli(
        ["--city", "Düsseldorf", "--budget", "300000"], service=service
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out.startswith(",".join(CSV_COLUMNS) + "\n")
    assert "detail fetch(es)" in captured.err


def test_run_cli_requires_api_key_without_injected_service(monkeypatch) -> None:
    monkeypatch.delenv("KEENABLE_API_KEY", raising=False)
    exit_code = run_cli(["--city", "Düsseldorf", "--budget", "300000"])
    assert exit_code == 2


def test_build_parser_defaults_to_required_budgets() -> None:
    args = build_parser().parse_args(["--city", "Köln", "--budget", "500000"])
    assert args.search_budget == DEFAULT_SEARCH_BUDGET == 10
    assert args.index_fetch_budget == DEFAULT_INDEX_FETCH_BUDGET == 10
    assert args.detail_fetch_budget == DEFAULT_DETAIL_FETCH_BUDGET == 20
    criteria = build_criteria(args)
    assert criteria.locations == ["Köln"]
    assert criteria.maximum_purchase_price.amount == 500000


def test_wuppertal_single_property_not_index_page() -> None:
    """A broker's legal postcode must not turn one property into an index."""

    fixture = FIXTURES / "immobiliya_wuppertal.json"
    page = json.loads(fixture.read_text(encoding="utf-8"))
    url = page["url"]

    criteria = benrath_criteria().model_copy(
        update={
            "locations": ["Wuppertal"],
            "postal_codes": [],
            "minimum_room_count": 2,
            "minimum_living_area_sqm": 50,
        }
    )

    children = []
    child_seen = set()

    records = _process_index_page(
        page, url, criteria, children, child_seen
    )

    assert len(records) == 1
    assert records[0].status is DiscoveryStatus.COMPLETE
    assert records[0].price_eur == 20_000
    assert records[0].area_m2 == 43
    assert records[0].rooms == 1
    assert records[0].postal_code == "42107"
    assert records[0].matches_criteria is False
    assert children == []



def test_genuine_multi_listing_remains_index_page() -> None:
    """Multiple property links must remain an index page."""

    url = "https://www.immobilo.de/kaufen/wohnung/duesseldorf-benrath"
    content = (
        FIXTURES / "index_immobilo_benrath.md"
    ).read_text(encoding="utf-8")

    page = {
        "url": url,
        "title": "Wohnungen kaufen Düsseldorf-Benrath",
        "content": content,
    }

    children = []
    child_seen = set()

    records = _process_index_page(
        page,
        url,
        benrath_criteria(),
        children,
        child_seen,
    )

    assert len(records) == 1
    assert records[0].status is DiscoveryStatus.INDEX_PAGE
    assert len(children) > 1
    assert records[0].child_count == len(children)

