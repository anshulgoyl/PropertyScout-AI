"""Local durable graph construction using SQLite checkpoints."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

from propertyscout.graph import build_graph, create_state_serializer


@contextmanager
def open_sqlite_graph(database_path: str | Path, **graph_options: Any) -> Iterator[Any]:
    """Yield a graph whose thread checkpoints survive process restarts.

    The context owns the SQLite connection. Callers must invoke the graph only
    inside the ``with`` block, then open a new context to simulate a restart.
    """

    path = Path(database_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False)
    try:
        checkpointer = SqliteSaver(connection, serde=create_state_serializer())
        yield build_graph(checkpointer=checkpointer, **graph_options)
    finally:
        connection.close()


def list_sqlite_thread_ids(database_path: str | Path) -> list[str]:
    """List persisted workflow thread IDs without decoding checkpoint payloads."""

    path = Path(database_path).expanduser().resolve()
    if not path.exists():
        return []
    connection = sqlite3.connect(path)
    try:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'checkpoints'"
        ).fetchone()
        if table_exists is None:
            return []
        rows = connection.execute(
            """
            SELECT thread_id
            FROM checkpoints
            GROUP BY thread_id
            ORDER BY MAX(rowid) DESC
            """
        ).fetchall()
        return [row[0] for row in rows]
    finally:
        connection.close()


def delete_sqlite_thread(database_path: str | Path, thread_id: str) -> bool:
    """Permanently remove one local workflow thread and its checkpoints."""

    path = Path(database_path).expanduser().resolve()
    if not path.exists():
        return False
    connection = sqlite3.connect(path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        found = False
        for table in ("writes", "checkpoints"):
            if table not in tables:
                continue
            columns = {
                row[1]
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if "thread_id" not in columns:
                continue
            exists = connection.execute(
                f"SELECT 1 FROM {table} WHERE thread_id = ? LIMIT 1", (thread_id,)
            ).fetchone()
            found = found or exists is not None
            connection.execute(f"DELETE FROM {table} WHERE thread_id = ?", (thread_id,))
        connection.commit()
        return found
    finally:
        connection.close()
