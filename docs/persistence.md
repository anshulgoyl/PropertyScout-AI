# Durable workflow persistence

## What is persisted

LangGraph creates a checkpoint after graph steps. A checkpoint includes the typed
deal state, current workflow position, pending interrupt, approvals, audit events,
and node-version metadata. The `thread_id` is the lookup key for one deal's
checkpoint history.

SQLite is appropriate for this local learning project because it is a single file,
requires no server, and demonstrates the same checkpointer contract used by a
production database.

## Lifecycle

```text
open SQLite connection
  -> compile graph with SqliteSaver
  -> invoke using a stable thread_id
  -> graph pauses at an interrupt
close application

open the same SQLite file
  -> compile a new graph
  -> resume using the same thread_id
  -> continue from the interrupt
```

Use the context manager so the database connection cannot accidentally outlive or
be closed underneath the graph:

```python
from langgraph.types import Command
from propertyscout.persistence import open_sqlite_graph

config = {"configurable": {"thread_id": "deal-123"}}

with open_sqlite_graph("data/propertyscout.sqlite") as graph:
    paused = graph.invoke(initial_state, config)

with open_sqlite_graph("data/propertyscout.sqlite") as restarted_graph:
    resumed = restarted_graph.invoke(
        Command(resume={"decision": "approved"}),
        config,
    )
```

## Important boundary

The checkpointer persists orchestration state; it is not the business system of
record. The current fake email and calendar gateways keep their provider records
in memory. Completed side-effect nodes are not replayed when a workflow resumes,
but a production integration must also use provider-supported idempotency or a
durable outbox table.

For deployment with concurrent workers, access control, backups, and retention,
replace SQLite with PostgreSQL while keeping the graph's checkpointer injection
point unchanged.

Checkpoint files can contain personal and commercially sensitive information.
They are excluded from Git and should be encrypted, access-controlled, backed up,
and deleted according to an explicit retention policy in production.
