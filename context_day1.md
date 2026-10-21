# PropertyScout AI — Day 1 Handoff

Use this document to continue the project in a new coding-agent session. Start by
reading this file, `README.md`, `docs/requirements.md`, and `docs/workflow.md`, then
run the verification commands below. Preserve existing behavior and secrets.

## 1. Product goal

PropertyScout AI is a human-supervised real-estate acquisition system built with
Python, LangChain, and LangGraph. A central LangGraph orchestrator coordinates six
specialist agents:

1. Market Scout
2. Investment Analyst
3. Contact Researcher
4. Outreach Agent
5. Scheduling Agent
6. Meeting Intelligence

The intended journey is property discovery → investment analysis → human shortlist
approval → broker contact research → approved outreach → reply handling and
scheduling → broker-call brief.

Important product decisions:

- The initial UI is for online property-search criteria only.
- Search-stage inputs include city, optional postcode, minimum rooms, minimum size,
  maximum price, property type, optional minimum yield, strategy, required features,
  and excluded features.
- Broker questions do not belong in the initial search form.
- Calendar availability such as 09:00–17:00 is collected later, during scheduling.
- Consequential decisions and initial external communication require human approval.

## 2. Current architecture

The code is under `src/propertyscout/`.

- `graph.py`: central LangGraph definition, nodes, edges, and deterministic routing.
- `state.py` and `schemas.py`: typed shared state and Pydantic contracts.
- `nodes.py`: agent-node adapters and interrupt boundaries.
- `bootstrap.py` and `fixtures.py`: deterministic learning/demo inputs.
- `market_search.py`: live Keenable public-web search plus normalization and evidence.
- `analyst.py`: trusted Python calculations and pluggable qualitative reasoner.
- `contact_research.py`: provider-neutral contact research; fixtures currently used.
- `outreach.py` and `email_gateway.py`: draft creation, approval, and fake idempotent send.
- `scheduling.py`: reply classification, scheduling policy, and fake calendar booking.
- `meeting_intelligence.py`: deterministic or Nebius-generated meeting brief.
- `persistence.py`: SQLite-backed LangGraph checkpoints.
- `api.py`: FastAPI endpoints and static-UI hosting.
- `config.py`: environment-based Nebius configuration.
- `demo.py`: CLI demonstration of the workflow branches.

One LangGraph thread represents one property. SQLite checkpoints allow a paused
thread to survive restarts and resume from its current interrupt using the same
`thread_id`.

## 3. What is implemented

### Six-agent workflow

The executable graph reaches Meeting Intelligence. It supports:

- deterministic market filtering and financial calculations;
- reject, research, review, and shortlist routing;
- human shortlist approval;
- fixture-backed contact discovery and ambiguous-contact resolution;
- personalized outreach draft and exact-message approval;
- fake idempotent email delivery;
- durable pause for an inbound broker reply;
- scheduling policy and exception approval;
- fake idempotent calendar booking; and
- structured broker-call briefing.

### Live property discovery

The search form calls `POST /searches`. `KeenableListingSearchService` searches the
public web, normalizes snippets, deduplicates URLs, and accepts only results with
purchase intent, target location, source URL, and an extractable asking price.

Every candidate retains source URL, retrieval time, and excerpt. Keenable is a
general web-search provider, not a licensed real-estate feed. Search snippets often
lack annual rent, so those properties correctly route to `needs_research` rather
than receiving an invented yield.

### Local UI

The static UI lives in `sites/propertyscout-ui/dist/` and is served by FastAPI at
`/app/`; `/` redirects there. It submits search criteria and renders one result card
per persisted property thread.

### Nebius runtime reasoning

PropertyScout uses Nebius model:

```text
zai-org/GLM-5.3-Flash
```

The web API injects the Nebius Investment Analyst and Meeting Intelligence service
when `PROPERTYSCOUT_LLM_ENABLED=true`. Python remains authoritative for financial
metrics and graph routing; the model supplies validated qualitative judgments.

A live integration test and an actual `POST /deals` web-API workflow both succeeded.
The verified API workflow returned HTTP 201, produced a nuanced shortlist thesis,
and paused at `shortlist_approval`.

## 4. Configuration and secrets

The private project `.env` exists locally and is ignored by Git. It currently has
configured Keenable and Nebius application credentials. Never print, copy into a
prompt, or commit its values.

The safe template is `.env.example`. Relevant variables are:

```text
NEBIUS_API_KEY
PROPERTYSCOUT_LLM_PROVIDER=nebius
PROPERTYSCOUT_LLM_ENABLED=true|false
PROPERTYSCOUT_LLM_MODEL=zai-org/GLM-5.3-Flash
PROPERTYSCOUT_LLM_BASE_URL=https://api.tokenfactory.nebius.com/v1/
PROPERTYSCOUT_LLM_TEMPERATURE=0
KEENABLE_API_KEY
```

Load the project environment before starting the live server:

```bash
set -a
source .env
set +a
./.venv/bin/uvicorn propertyscout.api:app --host 127.0.0.1 --port 8765
```

Then open `http://127.0.0.1:8765/app/`.

## 5. Coding-agent model setup

A user-level Codex profile named `nebius-glm` was added to
`/Users/anshulgoyal/.codex/config.toml`. It uses GLM-5.3-Flash through Nebius's
Responses API and references a separate environment variable:

```text
NEBIUS_CODEX_API_KEY
```

This coding-agent key is intentionally separate from PropertyScout's
`NEBIUS_API_KEY` and is not stored in this repository. The variable was not yet set
at the end of Day 1. To start a local coding session after setting it:

```bash
export NEBIUS_CODEX_API_KEY="your-separate-key"
codex --profile nebius-glm
```

GLM-5.3-Flash passed a live Nebius `/v1/responses` compatibility test.
Nebius `openai/gpt-oss-120b` did not work for Codex because Nebius returned:
`This model does not support Responses API`.

## 6. API surface

- `GET /health`: health check.
- `POST /searches`: run live Keenable discovery and create one thread per listing.
- `POST /deals`: start one of the deterministic learning fixtures.
- `GET /deals`: list latest persisted deal states.
- `GET /deals/{thread_id}`: inspect a deal and its pending interrupt.
- `POST /deals/{thread_id}/resume`: provide the response required by the interrupt.

This is localhost-only development software. It has no authentication,
authorization, HTTPS, or production-grade rate limiting.

## 7. Verification status

At the end of Day 1:

```text
33 offline tests passed
1 live Nebius test passed when the environment was loaded
Ruff: all checks passed
```

Run:

```bash
./.venv/bin/ruff check .
./.venv/bin/pytest -q -m 'not live'

# Optional; consumes a live Nebius request
set -a
source .env
set +a
./.venv/bin/pytest -q -m live
```

A Pydantic serializer warning about response metadata appeared during live Nebius
calls. It did not affect validated output or test success, but it can be cleaned up
later.

## 8. Persistence and repository status

- Source code, UI, documentation, tests, lockfile, and this handoff are saved locally.
- `.env` is ignored and must remain uncommitted.
- `*.sqlite`, `*.sqlite3`, and `*.db` are ignored because checkpoints may contain
  property, contact, approval, and message data.
- This folder did **not** contain a `.git` directory at the end of Day 1, so no Git
  commit could be created. Initialize or connect the repository before claiming a
  version-control recovery point.
- The system `git` command also reported missing Apple Command Line Developer Tools.
  Install/configure those tools before using normal Git commands on this Mac.

## 9. Known limitations

- Public search results commonly lack annual rent; no enrichment/research agent fills
  that field yet.
- Contact research uses fixtures, not a live enrichment provider.
- Email and calendar gateways are fake and perform no external side effects.
- Reply ingestion is simulated through the resume endpoint.
- The UI displays search results but does not yet provide controls for all later
  approval/resume stages.
- No production authentication, multi-user isolation, encrypted transport, provider
  quotas, or operational monitoring exists yet.
- Some README wording still describes deterministic analysis as the default; the
  actual web API uses GLM whenever the local enable flag is true.

## 10. Recommended next steps

Continue incrementally and explain each step to the user, who is learning while
building.

1. Set and verify the separate `NEBIUS_CODEX_API_KEY`, then start the new coding
   session with the `nebius-glm` profile.
2. Initialize or reconnect Git, verify ignored files, and create the first commit.
3. Add UI status showing whether Keenable and Nebius are enabled without exposing
   credentials.
4. Improve property enrichment so annual rent or comparable-rent evidence can be
   researched instead of leaving most live listings in `needs_research`.
5. Add UI controls for shortlist approval and later interrupts.
6. Replace fixture contact research only after defining provenance, privacy, and
   confidence requirements.
7. Keep email and calendar integrations fake until the corresponding approval and
   idempotency behavior is fully exercised in the UI.

## 11. Instructions for the next coding agent

- Do not overwrite existing work or regenerate the project from scratch.
- Do not display or commit `.env` or API-key values.
- Inspect current files and rerun offline tests before editing.
- Preserve deterministic calculations and explicit LangGraph routing.
- Keep human approval before shortlisting, ambiguous contact selection, initial
  outreach, and out-of-policy bookings.
- Use provider protocols and dependency injection so tests remain offline.
- Make one understandable increment at a time and explain why it is being made.
