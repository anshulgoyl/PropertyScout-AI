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
- a property with missing rent data routed to research
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
retains its source URL and excerpt and missing financial data routes to research.

This milestone is intended for localhost development. It has no authentication,
authorization, rate limiting, or encrypted transport and must not be exposed to a
public network.

The analysis is deliberately deterministic. An LLM will replace selected reasoning steps only after the routing and approval behavior is tested.

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
