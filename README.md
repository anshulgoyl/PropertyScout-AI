# PropertyScout AI

PropertyScout AI is a stateful, human-supervised real-estate acquisition workflow built with Python, LangChain, and LangGraph.

The system coordinates six specialist agents:

1. Market Scout
2. Investment Analyst
3. Contact Researcher
4. Outreach Agent
5. Scheduling Agent
6. Meeting Intelligence

The central LangGraph orchestrator owns workflow state, routing, retries, and approval pauses. Agents return structured state updates; they do not call one another directly.

## Current milestone

The executable vertical slice now reaches Agent 6, Meeting Intelligence. It includes typed
state, deterministic routing, four human-interrupt boundaries, fixture-backed
contact research, fake email delivery, reply classification, availability checks,
fake calendar booking, and a structured broker-call brief. External gateways are
injectable; the defaults perform no network calls.

## Run the first vertical slice

This workspace uses Python 3.12 and uv. The project-local uv executable created during setup can reproduce the environment:

```bash
./.tools/uv sync --extra dev --python 3.12
./.venv/bin/python -m propertyscout.demo
```

The demo runs three independent property threads:

- an above-budget property rejected by the Market Scout
- a property valued against the comparable market basis before approval (renting
  potential is evaluated in a later stage)
- a promising property paused and resumed through shortlist, contact, outreach,
  inbound reply, and meeting scheduling

By default checkpoints live only in memory. To persist every thread in a local
SQLite database, pass a database path:

```bash
./.venv/bin/python -m propertyscout.demo --sqlite data/propertyscout.sqlite
```

The graph can then be closed and reconstructed against the same file. Calling it
with the same `thread_id` and a LangGraph `Command(resume=...)` continues from the
saved interrupt instead of rerunning earlier agents. SQLite files are ignored by
Git because checkpoints can contain property, contact, message, and approval data.
See `docs/persistence.md` for the lifecycle and production boundary.

## Run the local API

Start the API with Uvicorn:

```bash
PROPERTYSCOUT_DB_PATH=data/propertyscout.sqlite \
  ./.venv/bin/uvicorn propertyscout.api:app --reload
```

Then open `http://127.0.0.1:8000/` for the PropertyScout search form or
`http://127.0.0.1:8000/docs` for FastAPI's interactive OpenAPI page.
The API can start fixture deals, list saved threads, inspect current state, and
resume the active LangGraph interrupt. See `docs/api.md` for request examples.

The form keeps the first decision intentionally small: city, maximum price, and
property type are required; postcode, rooms, size, yield, strategy, required
features, and exclusions are optional refinements. Scheduling preferences and
broker questions are collected only when the workflow reaches those stages. One
submission searches the public web through Keenable and creates a persisted thread
for every result that passes the purchase, location, and critical-field safety
checks.

Keenable works without a key at its public rate limit. Set `KEENABLE_API_KEY` to
use an authenticated allowance. This is general web discovery, not a licensed
real-estate feed: snippets may be incomplete or stale, so every normalized listing
retains its source URL and excerpt, and deals without a living area or a usable
comparable basis route to research instead of receiving an invented valuation.

Normalization is deliberately conservative. A Keenable result becomes a listing
only when its title and snippet describe exactly one property:

- Purchase intent with rental-context awareness: a sale page may mention rental
  income ("vermietete Eigentumswohnung", "Kaltmiete"), but rental ads do not
  pass a bare "Eigentumswohnung" wording.
- A city match that tolerates umlaut and ASCII spelling variants
  (Düsseldorf/Duesseldorf/Dusseldorf).
- An EUR asking price that shares a line with its currency symbol; USD figures
  on adjacent lines are never recorded as the EUR price.
- No evidence of a second property. Pages with two or more distinct prices or
  postal codes are quarantined (`multi-listing-page`) instead of stitching
  price, area, and rooms from different units into a fabricated listing.

Rejected candidates and their reasons are retained on the search service
(`KeenableListingSearchService.last_rejections`) after each search for
diagnostics, alongside `last_incomplete` (verified candidates still missing
the living area or room count) and `last_fetches` (detail-page fetch outcomes,
including failures and price discrepancies).

Discovery then verifies candidates before analysis. Snippets alone often lack
the living area, room count, or price, so the service fetches a bounded number
of detail pages through the Keenable page-fetch tool — enrichment candidates
first, then price-recovery candidates — default 3 fetches per search
(`PROPERTYSCOUT_DETAIL_FETCH_LIMIT`, 0 disables). A fetched page must still
describe exactly one property in the target city. A page price that conflicts
with the snippet price by more than 0.5% is adopted only when the page
identity is clear (single price, matching or absent postal code); both values
are always recorded for verification, otherwise the candidate is quarantined.
Only complete listings — price, living area, room count, location, and source
URL attributable to one property — proceed to automated analysis.

When the primary German query yields no verified listing, bounded fallback
variants are tried (default 3 search calls per search,
`PROPERTYSCOUT_SEARCH_QUERY_LIMIT`), with candidate URLs deduplicated across
queries. These budgets exclude the existing comparable-property searches.

## Standalone property discovery MVP

`propertyscout.discovery` is a standalone pipeline outside the LangGraph
workflow: it runs authenticated Keenable searches, fetches portal index pages
through the keyless public Keenable fetch endpoint, extracts the individual
listing URLs they link to (kleinanzeigen, immobilo, yourimmo, immowelt,
meinestadt exposes), fetches each listing page, deduplicates URLs across
portals, validates every page against the same gates as the graph discovery
(see `docs/workflow.md`), and writes a CSV report covering the complete
inventory: complete, incomplete, rejected, quarantined, index-page,
fetch-failed, and budget-exhausted candidates, including a `matches_criteria`
column and rejection reasons.

Live search requires `KEENABLE_API_KEY` — there is no silent keyless fallback
for search. Page fetches always use the keyless public endpoint. Request
budgets are hard limits without retries or early stopping: 10 search calls,
10 index-page fetches, and 20 individual-listing fetches per run. Cross-portal
records are merged only on verified shared expose/source references; similar
records without such a reference are merely flagged as possible duplicates.

```bash
./.venv/bin/python -m propertyscout.discovery \
  --city Düsseldorf --budget 300000 --postcode 40597 \
  --rooms 2 --min-area 50 --output discovery.csv
```

The CSV goes to stdout unless `--output` is given; a run summary is printed to
stderr. Offline behavior is verified by replaying the captured pages in
`tests/fixtures/` (`tests/test_discovery.py`); no live API calls happen in tests.

## Discovery engine in the local UI

`POST /searches` runs the same `DiscoveryService` used by the standalone CLI
(authenticated Keenable search, keyless index and listing fetches,
child-listing extraction, validation, and deduplication) and stores the full
inventory instead of starting analysis workflows automatically. Every run gets
a unique `search_id` and its own CSV under `data/discoveries/` — previous
inventories are never overwritten.

- `GET /discoveries` lists past discovery runs (search IDs, counts, budget
  usage, search errors); `GET /discoveries/{search_id}` returns every record
  with price, area, rooms, city, source URL, validation status,
  `matches_criteria`, rejection reasons, and missing attributes.
- `POST /discoveries/{search_id}/deals` starts the existing analysis workflow
  for **one selected complete listing**. Comparable research still runs at
  that moment through the existing `search_comps` service and feeds the same
  `build_market_basis` contract; a failed comps query starts the deal without
  a basis so the analyst routes it to research.
- Budgets match the standalone CLI and are configurable via environment
  variables: `PROPERTYSCOUT_DISCOVERY_SEARCH_BUDGET` (10),
  `PROPERTYSCOUT_DISCOVERY_INDEX_FETCH_BUDGET` (10), and
  `PROPERTYSCOUT_DISCOVERY_DETAIL_FETCH_BUDGET` (20).

The UI at `http://127.0.0.1:8000/app/` shows the discovery inventory with
per-status counts and search diagnostics; validated listings carry a
"Select for analysis" button that starts the durable deal workflow. Legacy
fixture-based usage (`listing_search_service=`) keeps its previous
auto-create-deal behavior for offline tests and demos.

## Deal pipeline dashboard

Opening `/app/` also shows a persistent deal pipeline below the search form. Every
persisted deal appears with a six-step stage tracker, a status badge (`Needs your
approval`, `In progress`, `Needs research`, `Dormant`, `Completed`, `Rejected`),
a Deal Score badge with gross yield and monthly cash flow when the Investment
Analyst produced them, and a market-valuation panel showing the estimated market
value, the comparable €/m² reference, and the price gap versus the estimate. Deals
waiting for a human decision render the matching
approval panel: shortlist decisions, contact selection, outreach editing, the
simulated broker-reply form, and out-of-policy schedule approvals. Approving
outreach always asks for confirmation before it sends through the configured
gateway (currently the local fake gateway). Dormant `awaiting_followup` deals
display a clear note and expose no resume controls. See `docs/api.md` for the
derived `status`, `pending_approval_type`, and `diagnostic` response fields.

The UI under `sites/propertyscout-ui/dist/` is hand-authored static HTML, CSS, and
JavaScript. There is no frontend build step; edit those files directly.

This milestone is intended for localhost development. It has no authentication,
authorization, rate limiting, or encrypted transport and must not be exposed to a
public network.

Financial calculations and graph routing stay deterministic in Python. When
`PROPERTYSCOUT_LLM_ENABLED=true`, the web API injects the Nebius model for the
qualitative investment judgment and the meeting brief; otherwise both fall back
to deterministic templates.

After shortlist approval, the graph now runs a fixture-backed Contact Researcher. One high-confidence result is selected automatically; zero results stop for further research; multiple plausible results pause for human resolution. No real personal data or enrichment API is used yet.

Once a contact is selected, a deterministic Outreach Agent prepares a personalized draft and pauses for approval of the exact recipient, subject, and body.

Approved drafts pass through a fake in-memory email gateway. It records a receipt but performs no network action. A stable idempotency key prevents duplicate messages when the send node is retried.

The durable workflow then pauses for an inbound broker reply. The Scheduling Agent
validates its sender, classifies the intent, and turns the first proposed time into
a 30-minute meeting. Weekday times from 09:00 through 17:00 Europe/Berlin book
automatically through a fake idempotent calendar gateway; exceptions require an
additional approval. Availability is represented by `SchedulingPreferences` and
can be supplied per workflow run.

After booking, Meeting Intelligence builds a validated brief containing the
investment summary, investor priorities, open questions, risks, negotiation
angles, and source evidence. The default is deterministic. The optional `--llm`
mode uses the same configured Nebius model for both qualitative investment
analysis and briefing while keeping calculations and routing in Python.

## Optional Nebius reasoning

The default remains deterministic and free to run. To enable the Nebius-backed qualitative analyst, create a local `.env` from `.env.example`, add your key, load it into the shell, and run:

```bash
cp .env.example .env
# Edit .env, set NEBIUS_API_KEY, and set PROPERTYSCOUT_LLM_ENABLED=true.
# Never commit this file.
set -a
source .env
set +a
./.venv/bin/python -m propertyscout.demo --llm
```

The Python calculator still owns financial metrics. The model receives those immutable results and returns validated structured output for qualitative analysis and the meeting brief. Provider settings are external so either adapter can be replaced without changing graph routing.

The web API also uses the configured Nebius model whenever
`PROPERTYSCOUT_LLM_ENABLED=true`. Leave it `false` to use the deterministic
offline analyst.

To run the optional live integration test:

```bash
./.venv/bin/pytest -q -m live
```

Run the quality checks with:

```bash
./.venv/bin/pytest -q
./.venv/bin/ruff check .
```

## Intended workflow

```text
criteria -> scout -> analyse -> shortlist approval -> research contact
         -> draft outreach -> email approval -> send -> monitor/schedule
         -> prepare meeting brief -> complete
```

Candidates can also be rejected, sent back for more research, paused for human review, or moved into an error-recovery path.
