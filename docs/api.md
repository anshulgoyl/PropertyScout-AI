# Local workflow API

The API is a thin delivery layer over the existing LangGraph orchestrator. It does
not duplicate routing or agent logic. Each request opens the SQLite-backed graph,
operates on one or more `thread_id` values, and closes the database connection.

## Start the server

```bash
PROPERTYSCOUT_DB_PATH=data/propertyscout.sqlite \
  ./.venv/bin/uvicorn propertyscout.api:app --reload
```

Interactive documentation is available at `http://127.0.0.1:8000/docs`.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Check that the process is responding |
| `POST` | `/deals` | Start a workflow from a learning fixture |
| `POST` | `/searches` | Discover public listings through Keenable and start deal threads |
| `GET` | `/deals` | List the latest state of every persisted thread |
| `GET` | `/deals/{thread_id}` | Inspect one deal and its pending interrupt |
| `POST` | `/deals/{thread_id}/resume` | Supply input to the current interrupt |

## Start a promising fixture deal

```bash
curl -X POST http://127.0.0.1:8000/deals \
  -H 'Content-Type: application/json' \
  -d '{"property_key":"shortlist"}'
```

The response contains four useful sections:

- `thread_id`: stable identity used for later requests.
- `state`: the latest validated `DealState` encoded as JSON.
- `next_nodes`: graph nodes eligible to execute next.
- `interrupts`: the human input currently required.

## Resume shortlist approval

Replace `THREAD_ID` with the value returned by the start request:

```bash
curl -X POST http://127.0.0.1:8000/deals/THREAD_ID/resume \
  -H 'Content-Type: application/json' \
  -d '{"response":{"decision":"approved","decided_by":"local-investor"}}'
```

The same resume endpoint accepts the payload described by the current interrupt.
For example, contact resolution expects a `contact_id`, outreach expects a
decision and optional edited subject/body, and the reply listener expects the
structured inbound reply fields.

The server rejects a resume request when the thread is not paused. It also relies
on Pydantic and the graph nodes to reject malformed or invalid decisions.

## Current scope and safety

`POST /deals` retains the three training fixtures for deterministic learning and
testing. The user-facing `POST /searches` route uses Keenable for live web
discovery. Keenable is keyless by default; `KEENABLE_API_KEY` is optional and
raises the provider's rate limit.

This API exposes contact information, messages, approvals, and investment data.
It is for localhost development only. Before deployment it needs authentication,
per-user authorization, HTTPS, request limits, secret management, audit access
controls, and a production database.

## Search form contract

The local UI at `/` calls `POST /searches`. Its required fields are city, maximum
price, and property type. Postcode, minimum room count, minimum living area, gross
yield, investment strategy, required features, and excluded features are optional
refinements. Scheduling availability and broker-call questions deliberately do not
belong to this search-stage contract; the workflow requests them later when needed.

Each search creates a separate persisted deal thread for every normalized public
candidate. Results must contain purchase intent, the target location, a source URL,
and an extractable asking price. Python parses price, area, rooms, postcode, and
common features; it never invents missing fields. Listings without rental income
continue through the graph as `needs_research` rather than receiving a confident
investment score.

Keenable is a general web-search API rather than a licensed property-data feed.
Pages may be stale, aggregate several listings, disappear, or prohibit downstream
automation. Production use should add provider-specific agreements, freshness
checks, canonical listing IDs, and compliance review.
