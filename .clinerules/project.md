# PropertyScout AI — Cline Project Rules

## Project context

- This is a Python 3.11+ project, developed and tested with Python 3.12 and `uv`.
- Source code lives under `src/propertyscout`; tests live under `tests`.
- The application is a stateful, human-supervised real-estate acquisition workflow built with FastAPI, LangGraph, Pydantic, and LangChain.
- The LangGraph orchestrator owns workflow state, routing, retries, and approval pauses. Specialist agents should return structured state updates and must not call one another directly.
- External gateways are injectable. Default/demo behavior must remain deterministic and offline unless a task explicitly requests a live integration.

## Engineering rules

- Preserve typed state and Pydantic validation at workflow boundaries.
- Keep calculations, routing, idempotency, and safety checks in Python; treat LLM output as validated qualitative input only.
- Preserve source URLs and evidence for externally discovered listings.
- Do not expose real personal data, API keys, or `.env` contents in code, tests, logs, or documentation.
- Avoid changing persisted checkpoint schemas or workflow interrupt semantics without updating the relevant persistence/API documentation and tests.
- Prefer small, focused changes. Keep the existing architecture and public behavior stable unless the task explicitly changes them.

## Verification

From the repository root, run:

```bash
./.venv/bin/pytest -q
./.venv/bin/ruff check .
```

For a local demo, use `./.venv/bin/python -m propertyscout.demo`. Do not run live integration tests unless explicitly requested; they require configured external credentials.
