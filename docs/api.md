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

The response contains seven useful sections:

- `thread_id`: stable identity used for later requests.
- `state`: the latest validated `DealState` encoded as JSON.
- `next_nodes`: graph nodes eligible to execute next.
- `interrupts`: the human input currently required.
- `status`: derived dashboard status (see below).
- `pending_approval_type`: which approval panel the UI should render, or `null`.
- `diagnostic`: explanation payload for unknown or failed terminal states, otherwise `null`.

`GET /deals` lists the most recently created thread first.

## Deal status

The status is derived in `propertyscout.api.derive_workflow_status`, in this priority
order:

1. A pending interrupt wins everything: the deal is `waiting_human`, even when the
   state contains historical error records. `pending_approval_type` comes from the
   interrupt's `approval_type`, or `input_type` for the simulated broker reply.
2. `current_stage == "failed"` reports `failed` (reserved for unrecoverable paths;
   no workflow node sets it today).
3. If the graph still has queued nodes, the deal is `running`.
4. Otherwise the graph has ended and the terminal `outcome` maps to a dashboard
   status: `completed` (`brief_ready`), `rejected` (`scout_rejected`,
   `analysis_rejected`, `shortlist_rejected`, `outreach_rejected`,
   `outreach_revision_requested`, `contact_not_found`, `broker_declined`,
   `schedule_rejected`), `needs_research`, or `awaiting_followup`.
5. An unrecognized terminal outcome reports `unknown` with a `diagnostic` payload
   naming the outcome and stage.

Errors in state are append-only history. They never change the status; the UI shows
them only as an advisory note.

`awaiting_followup` deals are dormant: the broker asked a question or answered
inconclusively, so no further automated action happens and resuming returns HTTP 409.

## Resume payloads by interrupt type

The nodes validate each payload; invalid input returns HTTP 422.

| Interrupt | Payload |
| --- | --- |
| `shortlist` | `{"decision": "approved" \| "rejected" \| "revision_requested", "decided_by": "…", "feedback": "…"}` (only `decision` required) |
| `contact_resolution` | `{"contact_id": "<uuid from the interrupt candidates>"}` |
| `outreach` | `{"decision": "approved" \| "rejected" \| "revision_requested", "subject": "…", "body": "…"}` — on `approved`, `subject`/`body` override the draft and must not be blank |
| `inbound_reply` | `{"message_id": "…", "sender_email": "…", "received_at": "ISO datetime", "body": "…", "proposed_times": ["ISO datetime"]}` — the sender must match the selected contact |
| `schedule_exception` | `{"decision": "approved" \| "rejected"}` |

Note that `outreach` decisions other than `approved` are terminal in the current
graph: rejected and revision-requested drafts end the workflow instead of looping
back into drafting.

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
and an extractable asking price. Python parses price, area, rooms, postcode, build
year, energy class, and condition; it never invents missing fields.

Every search also collects a comparable-listing basis for the same area before the
deals start. The basis (overall and per-condition median €/m² with source URLs) is
attached to every deal thread of that search, and the Investment Analyst values
candidates against it. Deals without a usable basis route to research instead of
being valued.

Keenable is a general web-search API rather than a licensed property-data feed.
Pages may be stale, aggregate several listings, disappear, or prohibit downstream
automation. Production use should add provider-specific agreements, freshness
checks, canonical listing IDs, and compliance review.
