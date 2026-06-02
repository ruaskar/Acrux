"""summary_store.py — sha-keyed cache of opt-in LLM file summaries.

One row per file (PRIMARY KEY path); the row carries the sha256 the summary was
written against, so a get() with a different sha is a MISS — a changed file never
serves a stale summary. Pure engine layer: no network, no LLM. Populated by
`keymd summarize`; read by render_keymd's summary lead (which feeds the .key.md,
the proxy gate, and the `keymd graph` side panel alike)."""
from __future__ import annotations

import sqlite3
import time

_DDL = """
CREATE TABLE IF NOT EXISTS llm_summaries (
    path TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    summary TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


def ensure_table(con: sqlite3.Connection) -> None:
    """Create the table if absent. summarize opens an EXISTING index (connect
    without create=True), so the full SCHEMA may not have been applied this
    session — this makes the writer self-sufficient."""
    con.executescript(_DDL)


def get(con: sqlite3.Connection, path: str, sha: str) -> str | None:
    row = con.execute(
        "SELECT summary FROM llm_summaries WHERE path=? AND sha256=?",
        (path, sha)).fetchone()
    return row[0] if row else None


def put(con: sqlite3.Connection, path: str, sha: str, summary: str, model: str) -> None:
    con.execute(
        "INSERT OR REPLACE INTO llm_summaries(path, sha256, summary, model, created_at) "
        "VALUES (?, ?, ?, ?, ?)", (path, sha, summary, model, time.time()))
    con.commit()
