"""db.py — SQLite schema + connection helper for the keymd index."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    lang TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    mtime REAL NOT NULL,
    line_count INTEGER NOT NULL,
    has_keymd INTEGER NOT NULL,
    indexed_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS symbols (
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    line INTEGER NOT NULL,
    signature TEXT,
    end_line INTEGER,
    PRIMARY KEY (path, name)
);
CREATE INDEX IF NOT EXISTS ix_symbols_name ON symbols(name);

CREATE TABLE IF NOT EXISTS edges (
    from_path TEXT NOT NULL,
    from_name TEXT NOT NULL,
    to_name TEXT NOT NULL,
    to_path TEXT,
    kind TEXT NOT NULL,
    line INTEGER NOT NULL,
    PRIMARY KEY (from_path, from_name, to_name, kind, line)
);
CREATE INDEX IF NOT EXISTS ix_edges_to_name ON edges(to_name);
CREATE INDEX IF NOT EXISTS ix_edges_from_path ON edges(from_path);

CREATE TABLE IF NOT EXISTS keymds (
    path TEXT PRIMARY KEY,
    src_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    auto_refreshed_at REAL
);

CREATE VIRTUAL TABLE IF NOT EXISTS keymd_fts USING fts5(
    path UNINDEXED,
    content,
    tokenize='unicode61'
);
"""


def connect(db_path: str | Path, create: bool = False) -> sqlite3.Connection:
    db_path = Path(db_path)
    if create:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, timeout=10.0)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    if create:
        con.executescript(SCHEMA)
    return con
