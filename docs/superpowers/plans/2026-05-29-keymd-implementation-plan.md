# keymd Implementation Plan (consolidated, phased)

> **One consolidated plan, executed phase-by-phase with a review checkpoint between phases.** Phase 1 (Index Engine) is fully detailed below; Phases 2–5 follow the same **Shared Contracts** (next section) so interfaces don't drift across phases. Supersedes the earlier standalone "Plan 1 / index-engine" filename.

**Product goal:** a local-only, cross-framework token-saving enforcement layer — a localhost proxy that gates full file reads behind LLM-optimized `.key.md` sidecars, backed by a live call-graph index. Full design: `docs/superpowers/specs/2026-05-29-keymd-token-saver-design.md`.

## Shared Contracts (all phases depend on these — change them HERE, never inside a phase)

These are the frozen interfaces. Any phase that needs to alter one must update this section first and re-check downstream phases.

- **Env / paths:** `KEYMD_PROJECT_ROOT` → git toplevel → cwd; index at `KEYMD_INDEX_PATH` or `<root>/.keymd/index.db`; source roots via `KEYMD_INDEX_DIRS` or auto-discover; excludes via `KEYMD_EXCLUDE_PATTERNS`.
- **DB schema (Phase 1, Task 4):** `files(path,lang,sha256,mtime,line_count,has_keymd,indexed_at)` · `symbols(path,name,kind,line,signature)` · `edges(from_path,from_name,to_name,to_path,kind,line)` · `keymds(path,src_path,sha256,auto_refreshed_at)` · `keymd_fts(path UNINDEXED, content)`.
- **Parser interface (Phase 1, Task 5):** `Parser.parse(path) -> ParseResult{ symbols:[Symbol(name,kind,line,signature)], edges:[Edge(from_name,to_name,kind,line)], line_count:int }`; registered by file extension; `get_parser_for(path)`.
- **Engine query API (consumed by Proxy + Watcher + CLI):** `query.callers(symbol)` · `query.callees(path)->[(to_name,relpath)]` · `query.symbols(path)->[(name,kind,line)]` · `query.impact(path)->{path,per_symbol,unique_files}` · `query.search(text,limit)->[(relpath,snippet)]` · `query.stats()`. Heuristic: `graph.callers_for_symbol(cur,sym,defining_path,defining_stem)->set[str]`.
- **Sidecar contract:** whole-file machine-generated, **no human region**; `render_keymd(con,src_path)->str`; idempotent modulo the `refreshed:` line via `strip_timestamp`.
- **Engine entrypoints for later phases:** `index.build(verbose)->dict` · `refresh.refresh_one(src_path)->bool` · `sync_one.sync_one(src_path)->None`.

### Phase roadmap (status)
1. **Index Engine** — fully detailed below (Tasks 1–15).
2. **FS Watcher** — debounced `sync_one` on source writes + FTS refresh on sidecar writes. *(outline at end; detailed after Phase 1 review)*
3. **Enforcing Proxy** — asyncio reverse-proxy (Anthropic + OpenAI wire formats), virtual `keymd_*` tools over the query API, pre-read gate with `:full` escalation, deterministic prompt-cache-safe rewrite. *(outline)*
4. **Host integration + A/B benchmark** — Claude Code / Codex / Cline setup, `AGENTS.md`, paired-subagent token benchmark. *(outline)*
5. **v1.1** — portable guardrails module + `/handoff` session-compaction. *(outline)*

---

# Phase 1 — Index Engine

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A dependency-light Python package that indexes a Python repo into a SQLite call-graph (`.keymd/index.db`), generates fully-machine-maintained LLM-optimized `.key.md` sidecars, and answers structure queries (callers / callees / impact / search) from one indexed lookup — all with zero LLM/API calls.

**Architecture:** A pluggable `Parser` interface emits language-neutral `ParseResult`s; the Python parser uses the stdlib `ast` module (more accurate and zero-dependency for Python than tree-sitter — JS/TS parsers arrive in Plan 1b behind the same interface). `index.build()` walks the repo, populates `files`/`symbols`/`edges`/`keymds`/`keymd_fts` tables, and resolves edges with a unique-defender rule. `keymd_render` deterministically renders a sidecar from the index; `refresh`/`sync_one` keep sidecars current; `query`/`graph` answer structure questions using an import-gated caller heuristic ported verbatim from the proven `aotc-harness` engine. No human-authored region in `.key.md` — the whole file is regenerated.

**Tech Stack:** Python 3.11, stdlib only at runtime (`ast`, `sqlite3` + FTS5, `pathlib`, `hashlib`), `pytest` for tests, `src/` layout with a `keymd` console-script entry point.

**Source provenance:** ported & generalized from `WhiteBox-Macro/aotc-harness` `hooks/key-files/keymd/{build_index,refresh,query,aotc_config}.py`. Changes vs source: renamed `aotc_config`→`config` and `AOTC_*`→`KEYMD_*` and `.aotc/`→`.keymd/`; dropped the Claude-Code-coupled staleness drain (`fcntl` — also fixes the Windows blocker) and the `memrefs`/memory subsystem (out of scope); added a `signature` column + LLM-optimized `.key.md` format with **no sentinel/human region**.

---

## File Structure

- `pyproject.toml` — package metadata, `keymd` entry point, pytest config.
- `src/keymd/__init__.py` — version.
- `src/keymd/engine/config.py` — path/env resolution (project root, index path, roots, excludes, pkg prefixes, registered extensions).
- `src/keymd/engine/db.py` — schema + connection helper (WAL, busy_timeout).
- `src/keymd/engine/parsers/base.py` — `Symbol`/`Edge`/`ParseResult` dataclasses, `Parser` protocol, extension→parser registry + `get_parser_for`.
- `src/keymd/engine/parsers/python.py` — Python parser (stdlib `ast`): symbols (+signatures) and edges.
- `src/keymd/engine/index.py` — `build()`: walk → parse → insert → resolve edges → index `.key.md` FTS.
- `src/keymd/engine/graph.py` — `callers_for_symbol()` import-gated heuristic + `STDLIB_STEMS`.
- `src/keymd/engine/keymd_render.py` — `render_keymd(con, src_path)` → LLM-optimized sidecar text (deterministic).
- `src/keymd/engine/refresh.py` — `refresh_one(src_path)`: regenerate the whole sidecar atomically, idempotent excluding timestamp.
- `src/keymd/engine/sync_one.py` — `sync_one(src_path)`: incremental re-index of one file + cascade-refresh dependents.
- `src/keymd/engine/query.py` — `callers`/`callees`/`symbols`/`impact`/`stats`/`search`/`missing-keymds`.
- `src/keymd/cli.py` — `keymd build|refresh|sync|callers|callees|symbols|impact|search|missing-keymds|stats`.
- `tests/fixtures/sample_proj/` — tiny deterministic fixture repo.
- `tests/` — one test module per engine module.

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/keymd/__init__.py`
- Create: `src/keymd/engine/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_scaffold.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scaffold.py
import keymd


def test_version_is_exposed():
    assert isinstance(keymd.__version__, str)
    assert keymd.__version__.count(".") >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scaffold.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keymd'` (package not installed yet).

- [ ] **Step 3: Write minimal implementation**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "keymd"
version = "0.1.0"
description = "Cross-framework token-saving enforcement layer: LLM-optimized .key.md sidecars + call-graph index"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
keymd = "keymd.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
addopts = "-q"
testpaths = ["tests"]
```

```python
# src/keymd/__init__.py
__version__ = "0.1.0"
```

```python
# src/keymd/engine/__init__.py
```

```python
# tests/__init__.py
```

- [ ] **Step 4: Install editable + run test to verify it passes**

Run: `python -m pip install -e ".[dev]" && python -m pytest tests/test_scaffold.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/keymd/__init__.py src/keymd/engine/__init__.py tests/__init__.py tests/test_scaffold.py
git commit -m "feat: project scaffold + keymd package"
```

---

## Task 2: Fixture repo

A deterministic mini-project the engine tests run against. `pkg/parser.py` defines `parse_header` and class `Parser` (method `parse`); `pkg/pipeline.py` imports and calls both, so `impact pkg/parser.py` must report `pkg/pipeline.py` as a caller.

**Files:**
- Create: `tests/fixtures/sample_proj/pkg/__init__.py` (empty)
- Create: `tests/fixtures/sample_proj/pkg/parser.py`
- Create: `tests/fixtures/sample_proj/pkg/pipeline.py`
- Create: `tests/conftest.py`
- Create: `tests/test_fixture.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fixture.py
def test_sample_proj_present(sample_proj):
    assert (sample_proj / "pkg" / "parser.py").exists()
    assert (sample_proj / "pkg" / "pipeline.py").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fixture.py -v`
Expected: FAIL — `fixture 'sample_proj' not found`.

- [ ] **Step 3: Write minimal implementation**

```python
# tests/fixtures/sample_proj/pkg/parser.py
def parse_header(buf: bytes) -> dict:
    return {"len": len(buf)}


class Parser:
    def parse(self, stream) -> list:
        return [parse_header(b"x")]
```

```python
# tests/fixtures/sample_proj/pkg/pipeline.py
from pkg.parser import Parser, parse_header


def run(stream) -> list:
    p = Parser()
    rows = p.parse(stream)
    rows.append(parse_header(b"hdr"))
    return rows
```

```python
# tests/conftest.py
import os
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "sample_proj"


@pytest.fixture
def sample_proj():
    return FIXTURE


@pytest.fixture
def env_proj(monkeypatch, tmp_path):
    """Point the engine at the fixture repo with an isolated index path."""
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(FIXTURE))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / "index.db"))
    # Clear caches that depend on env between tests.
    from keymd.engine import config
    config.project_pkg_prefixes.cache_clear()
    config._git_toplevel.cache_clear()
    return FIXTURE
```

Create the two empty files:

```bash
mkdir -p tests/fixtures/sample_proj/pkg
: > tests/fixtures/sample_proj/pkg/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fixture.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures tests/conftest.py tests/test_fixture.py
git commit -m "test: deterministic sample_proj fixture + env fixtures"
```

---

## Task 3: Config module

Port of `aotc_config.py`, renamed, with the staleness/memory functions removed and an `index_extensions()` registry hook added.

**Files:**
- Create: `src/keymd/engine/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from pathlib import Path

from keymd.engine import config


def test_project_root_from_env(env_proj):
    assert config.project_root() == Path(env_proj).resolve()


def test_index_path_from_env(env_proj, tmp_path):
    assert config.index_path().name == "index.db"


def test_index_roots_autodiscovers_pkg(env_proj):
    names = {r.name for r in config.index_roots()}
    assert "pkg" in names


def test_pkg_prefixes_contains_pkg(env_proj):
    assert "pkg" in config.project_pkg_prefixes()


def test_is_excluded():
    assert config.is_excluded("/x/__pycache__/y.py")
    assert not config.is_excluded("/x/pkg/y.py")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keymd.engine.config'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/keymd/engine/config.py
"""config.py — env / auto-detect path resolution for the keymd engine.

Precedence for project root: KEYMD_PROJECT_ROOT → git toplevel → cwd.
Other env overrides:
  KEYMD_INDEX_PATH       absolute path to .keymd/index.db
  KEYMD_INDEX_DIRS       colon-separated subdir names to walk
  KEYMD_EXCLUDE_PATTERNS colon-separated extra path-substring exclusions
"""
from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

# Source-file extensions that have a registered parser. parsers.base appends to
# this set at import time; config keeps it so index.py can ask without importing
# parsers (avoids a cycle).
REGISTERED_EXTENSIONS: set[str] = set()

DEFAULT_EXCLUDES = (
    "/__pycache__/", "/.git/", "/.venv/", "/venv/", "/node_modules/",
    "/.next/", "/dist/", "/build/", "/.ruff_cache/", "/.keymd/",
    "/.claude/", "/.pytest_cache/", "/.mypy_cache/",
)
SKIP_TOP_DIRS = {
    "node_modules", "venv", ".venv", "__pycache__", "dist", "build",
    ".next", ".git", ".keymd", ".ruff_cache", ".claude", ".pytest_cache",
    ".mypy_cache", "target",
}


@lru_cache(maxsize=1)
def _git_toplevel() -> Path | None:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True, timeout=2,
        )
        p = Path(r.stdout.strip())
        return p if p.exists() else None
    except (subprocess.CalledProcessError, FileNotFoundError,
            subprocess.TimeoutExpired):
        return None


def _env_path(name: str) -> Path | None:
    v = os.environ.get(name)
    if not v:
        return None
    v = os.path.expanduser(os.path.expandvars(v))
    p = Path(v)
    return p if p.exists() else None


def project_root() -> Path:
    p = _env_path("KEYMD_PROJECT_ROOT")
    if p:
        return p.resolve()
    gt = _git_toplevel()
    if gt:
        return gt
    return Path.cwd()


def index_path() -> Path:
    v = os.environ.get("KEYMD_INDEX_PATH")
    if v:
        return Path(os.path.expanduser(os.path.expandvars(v)))
    return project_root() / ".keymd" / "index.db"


def index_extensions() -> tuple[str, ...]:
    return tuple(sorted(REGISTERED_EXTENSIONS)) or (".py",)


def index_roots() -> list[Path]:
    pr = project_root()
    v = os.environ.get("KEYMD_INDEX_DIRS")
    if v:
        out = []
        for d in v.split(":"):
            d = d.strip()
            if not d:
                continue
            d = os.path.expanduser(os.path.expandvars(d))
            p = Path(d)
            out.append(p if p.is_absolute() else pr / p)
        return out
    out = []
    for child in sorted(pr.iterdir()):
        if (not child.is_dir() or child.name.startswith(".")
                or child.name in SKIP_TOP_DIRS):
            continue
        try:
            for ext in index_extensions():
                if next(child.rglob(f"*{ext}"), None):
                    out.append(child)
                    break
        except (PermissionError, OSError):
            continue
    return out


def exclude_patterns() -> tuple[str, ...]:
    extra = os.environ.get("KEYMD_EXCLUDE_PATTERNS", "")
    extras = tuple(p for p in extra.split(":") if p)
    return DEFAULT_EXCLUDES + extras


def is_excluded(path: str) -> bool:
    norm = path.replace(os.sep, "/")
    return any(pat in norm for pat in exclude_patterns())


@lru_cache(maxsize=1)
def project_pkg_prefixes() -> set[str]:
    """Top-level package names used by the import-gate heuristic in graph.py."""
    return {r.name for r in index_roots()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (5 passed). Note: `index_extensions()` defaults to `(".py",)` until parsers register.

- [ ] **Step 5: Commit**

```bash
git add src/keymd/engine/config.py tests/test_config.py
git commit -m "feat: engine config (path/env resolution)"
```

---

## Task 4: DB schema + connection

**Files:**
- Create: `src/keymd/engine/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db.py
from keymd.engine import db


def test_connect_creates_schema(tmp_path):
    p = tmp_path / "index.db"
    con = db.connect(p, create=True)
    names = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
    ).fetchall()}
    assert {"files", "symbols", "edges", "keymds"} <= names
    # FTS5 must be available.
    con.execute("INSERT INTO keymd_fts(path, content) VALUES ('a','hello')")
    rows = con.execute(
        "SELECT path FROM keymd_fts WHERE keymd_fts MATCH 'hello'").fetchall()
    assert rows == [("a",)]
    con.close()


def test_symbols_has_signature_column(tmp_path):
    con = db.connect(tmp_path / "i.db", create=True)
    cols = {r[1] for r in con.execute("PRAGMA table_info(symbols)").fetchall()}
    assert "signature" in cols
    con.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keymd.engine.db'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/keymd/engine/db.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_db.py -v`
Expected: PASS (2 passed). If the FTS test errors with `no such module: fts5`, the Python build lacks FTS5 — stop and report; the engine requires it.

- [ ] **Step 5: Commit**

```bash
git add src/keymd/engine/db.py tests/test_db.py
git commit -m "feat: SQLite schema + connection helper (FTS5, signature column)"
```

---

## Task 5: Parser interface + registry

**Files:**
- Create: `src/keymd/engine/parsers/__init__.py` (empty)
- Create: `src/keymd/engine/parsers/base.py`
- Create: `tests/test_parsers_base.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_parsers_base.py
from keymd.engine.parsers import base


def test_parseresult_shape():
    r = base.ParseResult(symbols=[], edges=[], line_count=3)
    assert r.line_count == 3 and r.symbols == [] and r.edges == []


def test_register_and_dispatch():
    class Dummy:
        extensions = (".dummy",)

        def parse(self, path):
            return base.ParseResult(symbols=[], edges=[], line_count=0)

    base.register(Dummy())
    from pathlib import Path
    p = base.get_parser_for(Path("/x/y.dummy"))
    assert p is not None
    assert base.get_parser_for(Path("/x/y.unknown")) is None
    assert ".dummy" in base.config.REGISTERED_EXTENSIONS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_parsers_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keymd.engine.parsers.base'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/keymd/engine/parsers/base.py
"""base.py — language-neutral parse result + parser registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from keymd.engine import config


@dataclass
class Symbol:
    name: str            # qualified name, e.g. "Parser.parse"
    kind: str            # "function" | "method" | "class"
    line: int
    signature: str | None = None


@dataclass
class Edge:
    from_name: str       # caller symbol or "<module>"
    to_name: str         # callee name (possibly dotted) / import target
    kind: str            # "call" | "import" | "inherit"
    line: int


@dataclass
class ParseResult:
    symbols: list[Symbol] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    line_count: int = 0


class Parser(Protocol):
    extensions: tuple[str, ...]

    def parse(self, path: Path) -> ParseResult: ...


_REGISTRY: dict[str, Parser] = {}


def register(parser: Parser) -> None:
    for ext in parser.extensions:
        _REGISTRY[ext] = parser
        config.REGISTERED_EXTENSIONS.add(ext)


def get_parser_for(path: Path) -> Parser | None:
    name = path.name
    # Handle compound extensions like .d.ts by longest-suffix match.
    for ext in sorted(_REGISTRY, key=len, reverse=True):
        if name.endswith(ext):
            return _REGISTRY[ext]
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_parsers_base.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/keymd/engine/parsers/__init__.py src/keymd/engine/parsers/base.py tests/test_parsers_base.py
git commit -m "feat: parser interface + extension registry"
```

---

## Task 6: Python parser — symbols & signatures

**Files:**
- Create: `src/keymd/engine/parsers/python.py`
- Create: `tests/test_parser_python_symbols.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_parser_python_symbols.py
from pathlib import Path

from keymd.engine.parsers.python import PythonParser

SRC = '''
def parse_header(buf: bytes) -> dict:
    return {}


class Parser:
    def parse(self, stream) -> list:
        return []
'''


def test_symbols_and_signatures(tmp_path):
    f = tmp_path / "m.py"
    f.write_text(SRC, encoding="utf-8")
    r = PythonParser().parse(f)
    by_name = {s.name: s for s in r.symbols}
    assert by_name["parse_header"].kind == "function"
    assert by_name["parse_header"].signature == "def parse_header(buf: bytes) -> dict"
    assert by_name["Parser"].kind == "class"
    assert by_name["Parser.parse"].kind == "method"
    assert by_name["Parser.parse"].signature == "def parse(self, stream) -> list"
    assert r.line_count == SRC.count("\n") + 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_parser_python_symbols.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keymd.engine.parsers.python'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/keymd/engine/parsers/python.py
"""python.py — Python source parser using the stdlib `ast` module.

Emits language-neutral ParseResult (symbols + edges). Chosen over tree-sitter
for Python because `ast` is zero-dependency, exact, and battle-tested; JS/TS
parsers (Plan 1b) use tree-sitter behind the same Parser interface.
"""
from __future__ import annotations

import ast
from pathlib import Path

from keymd.engine.parsers.base import Edge, ParseResult, Symbol, register


def _call_name(node) -> str | None:
    """Return 'foo' or 'obj.attr.x' from a Name/Attribute node, else None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts = []
        cur = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
            return ".".join(reversed(parts))
        return node.attr
    return None


def _signature(node) -> str:
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        return f"class {node.name}({bases})" if bases else f"class {node.name}"
    prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    args = ast.unparse(node.args)
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix}{node.name}({args}){ret}"


class _Analyzer(ast.NodeVisitor):
    def __init__(self) -> None:
        self.symbols: list[Symbol] = []
        self.edges: list[Edge] = []
        self.stack: list[str] = []

    def _enter(self, qn: str, node) -> None:
        self.stack.append(qn)
        self.generic_visit(node)
        self.stack.pop()

    def _from(self) -> str:
        return self.stack[-1] if self.stack else "<module>"

    def visit_FunctionDef(self, node) -> None:
        qn = ".".join(self.stack + [node.name]) if self.stack else node.name
        kind = "method" if self.stack else "function"
        self.symbols.append(Symbol(qn, kind, node.lineno, _signature(node)))
        self._enter(qn, node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node) -> None:
        qn = ".".join(self.stack + [node.name]) if self.stack else node.name
        self.symbols.append(Symbol(qn, "class", node.lineno, _signature(node)))
        for base in node.bases:
            tn = _call_name(base)
            if tn:
                self.edges.append(Edge(qn, tn, "inherit", node.lineno))
        self._enter(qn, node)

    def visit_Call(self, node) -> None:
        tn = _call_name(node.func)
        if tn:
            fn = self._from()
            self.edges.append(Edge(fn, tn, "call", node.lineno))
            if "." in tn:
                self.edges.append(Edge(fn, tn.rsplit(".", 1)[-1], "call", node.lineno))
        self.generic_visit(node)

    def visit_Import(self, node) -> None:
        fn = self._from()
        for alias in node.names:
            self.edges.append(Edge(fn, alias.name, "import", node.lineno))

    def visit_ImportFrom(self, node) -> None:
        fn = self._from()
        mod = node.module or ""
        for alias in node.names:
            target = f"{mod}.{alias.name}" if mod else alias.name
            self.edges.append(Edge(fn, target, "import", node.lineno))


class PythonParser:
    extensions = (".py",)

    def parse(self, path: Path) -> ParseResult:
        src = path.read_text(encoding="utf-8", errors="replace")
        lc = src.count("\n") + 1
        try:
            tree = ast.parse(src, filename=str(path))
        except SyntaxError:
            return ParseResult(symbols=[], edges=[], line_count=lc)
        az = _Analyzer()
        az.visit(tree)
        return ParseResult(symbols=az.symbols, edges=az.edges, line_count=lc)


register(PythonParser())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_parser_python_symbols.py -v`
Expected: PASS. (`ast.unparse` requires Python ≥3.9; we target 3.11.)

- [ ] **Step 5: Commit**

```bash
git add src/keymd/engine/parsers/python.py tests/test_parser_python_symbols.py
git commit -m "feat: Python parser — symbols + signatures via ast"
```

---

## Task 7: Python parser — edges

**Files:**
- Modify: none (edges already emitted in Task 6).
- Create: `tests/test_parser_python_edges.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_parser_python_edges.py
from keymd.engine.parsers.python import PythonParser

SRC = '''
from pkg.parser import Parser, parse_header
import os


def run(stream):
    p = Parser()
    parse_header(b"x")
    return p.parse(stream)
'''


def test_edges(tmp_path):
    f = tmp_path / "pipeline.py"
    f.write_text(SRC, encoding="utf-8")
    r = PythonParser().parse(f)
    triples = {(e.from_name, e.to_name, e.kind) for e in r.edges}
    # imports
    assert ("<module>", "pkg.parser.Parser", "import") in triples
    assert ("<module>", "pkg.parser.parse_header", "import") in triples
    assert ("<module>", "os", "import") in triples
    # calls (full + leaf for dotted)
    assert ("run", "parse_header", "call") in triples
    assert ("run", "Parser", "call") in triples
    assert ("run", "p.parse", "call") in triples
    assert ("run", "parse", "call") in triples  # leaf of p.parse
```

- [ ] **Step 2: Run test to verify it fails**

First confirm it actually exercises new ground (it should already pass given Task 6). Run: `python -m pytest tests/test_parser_python_edges.py -v`
Expected: PASS immediately (edges implemented in Task 6). If any assertion FAILS, fix `python.py` until green — this test pins the leaf-duplication contract the caller heuristic depends on.

- [ ] **Step 3: Write minimal implementation**

No new code expected. If failing, the most likely gap is the leaf-edge duplication in `visit_Call` — ensure both `p.parse` and `parse` edges are emitted.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_parser_python_edges.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_parser_python_edges.py
git commit -m "test: pin Python edge extraction contract (incl. leaf-call duplication)"
```

---

## Task 8: build() — index the repo

**Files:**
- Create: `src/keymd/engine/index.py`
- Create: `tests/test_index.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_index.py
from keymd.engine import config, db, index
import keymd.engine.parsers.python  # noqa: F401  (registers the parser)


def test_build_populates_tables_and_resolves_edges(env_proj):
    stats = index.build(verbose=False)
    assert stats["files"] >= 2
    con = db.connect(config.index_path())
    # symbols
    names = {r[0] for r in con.execute("SELECT name FROM symbols").fetchall()}
    assert {"parse_header", "Parser", "Parser.parse", "run"} <= names
    # an edge from pipeline → parser got resolved to a project path
    row = con.execute(
        "SELECT to_path FROM edges WHERE to_name='parse_header' "
        "AND kind='call' AND to_path IS NOT NULL LIMIT 1").fetchone()
    assert row is not None and row[0].endswith("parser.py")
    con.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_index.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keymd.engine.index'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/keymd/engine/index.py
"""index.py — build the symbol/edge graph for the active project into SQLite."""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

from keymd.engine import config, db
from keymd.engine.parsers.base import get_parser_for


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_source_files():
    exts = config.index_extensions()
    for root in config.index_roots():
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if not any(p.name.endswith(e) for e in exts):
                continue
            if not config.is_excluded(str(p)):
                yield p


def iter_keymd_files():
    for root in config.index_roots():
        if not root.exists():
            continue
        for p in root.rglob("*.key.md"):
            if not config.is_excluded(str(p)):
                yield p


def _lang_for(path: Path) -> str:
    return path.suffix.lstrip(".") or "?"


def build(verbose: bool = True) -> dict:
    db_path = config.index_path()
    if db_path.exists():
        db_path.unlink()
    con = db.connect(db_path, create=True)

    files = list(iter_source_files())
    if verbose:
        print(f"Indexing {len(files)} source files…")

    n_sym = n_edge = 0
    t0 = time.time()
    for p in files:
        sp = str(p)
        parser = get_parser_for(p)
        if parser is None:
            continue
        try:
            sha = _file_sha(p)
            mtime = p.stat().st_mtime
        except OSError:
            continue
        result = parser.parse(p)
        sibling_key = sp[:-len(p.suffix)] + ".key.md"
        has_keymd = 1 if os.path.exists(sibling_key) else 0
        con.execute(
            "INSERT INTO files(path, lang, sha256, mtime, line_count, "
            "has_keymd, indexed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sp, _lang_for(p), sha, mtime, result.line_count, has_keymd,
             time.time()),
        )
        con.executemany(
            "INSERT OR IGNORE INTO symbols(path, name, kind, line, signature) "
            "VALUES (?, ?, ?, ?, ?)",
            [(sp, s.name, s.kind, s.line, s.signature) for s in result.symbols],
        )
        con.executemany(
            "INSERT OR IGNORE INTO edges(from_path, from_name, to_name, "
            "to_path, kind, line) VALUES (?, ?, ?, NULL, ?, ?)",
            [(sp, e.from_name, e.to_name, e.kind, e.line) for e in result.edges],
        )
        n_sym += len(result.symbols)
        n_edge += len(result.edges)
    con.commit()

    if verbose:
        print("Resolving edges…")
    con.execute("""
        UPDATE edges
        SET to_path = (
            SELECT path FROM symbols s
            WHERE s.name = edges.to_name
            GROUP BY s.name
            HAVING COUNT(DISTINCT s.path) = 1
            LIMIT 1
        )
        WHERE to_path IS NULL
    """)
    con.commit()

    n_keymd = 0
    for k in iter_keymd_files():
        ksp = str(k)
        stem = ksp[:-len(".key.md")]
        src_path = ""
        for ext in config.index_extensions():
            if os.path.exists(stem + ext):
                src_path = stem + ext
                break
        content = k.read_text(encoding="utf-8", errors="replace")
        sha = hashlib.sha256(content.encode()).hexdigest()
        con.execute(
            "INSERT OR REPLACE INTO keymds(path, src_path, sha256, "
            "auto_refreshed_at) VALUES (?, ?, ?, NULL)", (ksp, src_path, sha))
        con.execute("INSERT INTO keymd_fts(path, content) VALUES (?, ?)",
                    (ksp, content))
        n_keymd += 1
    con.commit()

    n_resolved = con.execute(
        "SELECT COUNT(*) FROM edges WHERE to_path IS NOT NULL").fetchone()[0]
    con.close()

    dt = time.time() - t0
    stats = {
        "files": len(files), "symbols": n_sym, "edges": n_edge,
        "resolved_edges": n_resolved, "keymds": n_keymd,
        "seconds": round(dt, 2), "db_path": str(db_path),
    }
    if verbose:
        print(f"Done in {dt:.1f}s — {stats}")
    return stats


if __name__ == "__main__":
    build(verbose=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_index.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/keymd/engine/index.py tests/test_index.py
git commit -m "feat: build() indexes repo into SQLite + resolves edges"
```

---

## Task 9: graph — import-gated caller heuristic

Verbatim port of `_callers_for_symbol` + `STDLIB_STEMS` from `aotc-harness/refresh.py`, relocated to a shared module (proven heuristic: `OpBus.close` → 1 real caller not 221; `main` → 0).

**Files:**
- Create: `src/keymd/engine/graph.py`
- Create: `tests/test_graph.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_graph.py
from keymd.engine import config, db, graph, index
import keymd.engine.parsers.python  # noqa: F401


def test_callers_for_symbol_finds_pipeline(env_proj):
    index.build(verbose=False)
    con = db.connect(config.index_path())
    cur = con.cursor()
    parser_path = next(
        r[0] for r in cur.execute("SELECT path FROM files").fetchall()
        if r[0].endswith("parser.py"))
    callers = graph.callers_for_symbol(cur, "parse_header", parser_path, "parser")
    assert any(c.endswith("pipeline.py") for c in callers)
    con.close()


def test_stdlib_stems_present():
    assert "os" in graph.STDLIB_STEMS and "re" in graph.STDLIB_STEMS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_graph.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keymd.engine.graph'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/keymd/engine/graph.py
"""graph.py — import-gated caller heuristic over the edges table.

Ported verbatim from aotc-harness/refresh.py. The leaf-name caller match is
gated on an import-of-the-defining-module signal so `OpBus.close` does not
match all 221 `.close()` calls. Stems colliding with the stdlib drop the
bare-stem patterns to avoid false positives on `import os`-style lines.
"""
from __future__ import annotations

import os
import sqlite3

from keymd.engine import config

STDLIB_STEMS = frozenset({
    "abc", "argparse", "ast", "asyncio", "base64", "binascii", "bisect",
    "builtins", "bz2", "calendar", "cmath", "cmd", "code", "codecs",
    "collections", "colorsys", "concurrent", "configparser", "contextlib",
    "contextvars", "copy", "copyreg", "csv", "ctypes", "curses",
    "dataclasses", "datetime", "decimal", "difflib", "dis", "doctest",
    "email", "encodings", "enum", "errno", "faulthandler", "filecmp",
    "fileinput", "fnmatch", "fractions", "functools", "gc", "getopt",
    "getpass", "gettext", "glob", "graphlib", "grp", "gzip", "hashlib",
    "heapq", "hmac", "html", "http", "imaplib", "importlib", "inspect",
    "io", "ipaddress", "itertools", "json", "keyword", "linecache",
    "locale", "logging", "lzma", "mailbox", "math", "mimetypes",
    "mmap", "multiprocessing", "netrc", "numbers", "operator", "optparse",
    "os", "pathlib", "pdb", "pickle", "pkgutil", "platform", "plistlib",
    "poplib", "posix", "posixpath", "pprint", "profile", "pty", "pwd",
    "py_compile", "pyclbr", "queue", "quopri", "random", "re", "readline",
    "reprlib", "resource", "runpy", "sched", "secrets", "select",
    "selectors", "shelve", "shlex", "shutil", "signal", "site", "smtplib",
    "socket", "socketserver", "sqlite3", "ssl", "stat", "statistics",
    "string", "stringprep", "struct", "subprocess", "symtable", "sys",
    "sysconfig", "syslog", "tabnanny", "tarfile", "telnetlib", "tempfile",
    "termios", "textwrap", "threading", "time", "timeit", "tkinter",
    "token", "tokenize", "tomllib", "trace", "traceback", "tracemalloc",
    "tty", "turtle", "types", "typing", "unicodedata", "unittest",
    "urllib", "uu", "uuid", "venv", "warnings", "wave", "weakref",
    "webbrowser", "wsgiref", "xdrlib", "xml", "xmlrpc", "zipapp",
    "zipfile", "zipimport", "zlib", "zoneinfo",
})


def relpath(p: str) -> str:
    try:
        return os.path.relpath(p, config.project_root())
    except ValueError:
        return p


def is_project_import(name: str) -> bool:
    head = name.split(".", 1)[0]
    return head in config.project_pkg_prefixes()


def callers_for_symbol(cur: sqlite3.Cursor, sym: str, defining_path: str,
                       defining_stem: str) -> set[str]:
    """Files that plausibly call `sym` (defined in `defining_path`)."""
    leaf = sym.rsplit(".", 1)[-1] if "." in sym else sym
    class_name = sym.split(".", 1)[0] if "." in sym else None
    is_class_method = "." in sym

    callers: set[str] = set()
    if is_class_method:
        cur.execute(
            "SELECT DISTINCT from_path FROM edges "
            "WHERE kind='call' AND from_path != ? AND to_name = ?",
            (defining_path, sym))
        callers |= {r[0] for r in cur.fetchall()}

    if defining_stem in STDLIB_STEMS:
        like_patterns: list[str] = []
    else:
        like_patterns = [
            f"%.{defining_stem}", defining_stem,
            f"{defining_stem}.%", f"%.{defining_stem}.%",
        ]
    if class_name:
        like_patterns.append(f"%.{class_name}")
        like_patterns.append(class_name)
    if like_patterns:
        placeholders = " OR ".join(["i.to_name LIKE ?"] * len(like_patterns))
        cur.execute(
            f"""SELECT DISTINCT e.from_path FROM edges e
                  WHERE e.kind='call' AND e.from_path != ? AND e.to_name = ?
                    AND EXISTS (
                      SELECT 1 FROM edges i
                      WHERE i.from_path = e.from_path AND i.kind='import'
                        AND ({placeholders}))""",
            (defining_path, leaf, *like_patterns))
        callers |= {r[0] for r in cur.fetchall()}
    return callers
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_graph.py -v`
Expected: PASS. (`pipeline.py` imports `pkg.parser.parse_header`, which matches the `%.parser.%` import gate, so its `parse_header` call is attributed.)

- [ ] **Step 5: Commit**

```bash
git add src/keymd/engine/graph.py tests/test_graph.py
git commit -m "feat: import-gated caller heuristic (ported from aotc-harness)"
```

---

## Task 10: render the LLM-optimized .key.md

Deterministic renderer. **No human/sentinel region — the whole file is generated.** Reads the index; renders header + `api`/`deps`/`calls`/`called_by`/`refreshed`.

**Files:**
- Create: `src/keymd/engine/keymd_render.py`
- Create: `tests/test_keymd_render.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_keymd_render.py
from keymd.engine import config, db, index, keymd_render
import keymd.engine.parsers.python  # noqa: F401


def test_render_contains_api_and_callers(env_proj):
    index.build(verbose=False)
    con = db.connect(config.index_path())
    parser_path = next(
        r[0] for r in con.execute("SELECT path FROM files").fetchall()
        if r[0].endswith("parser.py"))
    text = keymd_render.render_keymd(con, parser_path)
    assert text.startswith("# ")
    assert "[python ·" in text
    assert "def parse_header(buf: bytes) -> dict" in text
    assert "called_by:" in text
    assert "pipeline.py" in text  # pipeline calls parse_header
    assert text.rstrip().splitlines()[-1].startswith("refreshed:")
    con.close()


def test_render_idempotent_modulo_timestamp(env_proj):
    index.build(verbose=False)
    con = db.connect(config.index_path())
    parser_path = next(
        r[0] for r in con.execute("SELECT path FROM files").fetchall()
        if r[0].endswith("parser.py"))
    a = keymd_render.strip_timestamp(keymd_render.render_keymd(con, parser_path))
    b = keymd_render.strip_timestamp(keymd_render.render_keymd(con, parser_path))
    assert a == b
    con.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_keymd_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keymd.engine.keymd_render'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/keymd/engine/keymd_render.py
"""keymd_render.py — deterministic LLM-optimized .key.md text from the index.

The entire file is machine-generated; there is no human-authored region.
Format is terse and token-dense (key: value lines), optimized for an LLM to
consume before reading the full source.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from keymd.engine import config
from keymd.engine.graph import callers_for_symbol, is_project_import, relpath

MAX_DEPS = 10
MAX_CALLS = 15
MAX_CALLERS_PER_SYM = 5
TS_PREFIX = "refreshed:"


def strip_timestamp(text: str) -> str:
    return "\n".join(l for l in text.splitlines()
                     if not l.startswith(TS_PREFIX))


def render_keymd(con: sqlite3.Connection, src_path: str) -> str:
    cur = con.cursor()
    frow = cur.execute(
        "SELECT lang, line_count, sha256 FROM files WHERE path=?",
        (src_path,)).fetchone()
    lang, loc, sha = frow if frow else ("?", 0, "")

    # API: top-level symbols with signatures, ordered by line.
    cur.execute(
        "SELECT name, kind, signature FROM symbols "
        "WHERE path=? AND name NOT LIKE '%.%' ORDER BY line", (src_path,))
    api_lines = []
    for name, kind, sig in cur.fetchall():
        api_lines.append(f"  {sig or name}")
        # include direct methods of a class for context
        cur2 = con.cursor()
        cur2.execute(
            "SELECT signature, name FROM symbols WHERE path=? "
            "AND name LIKE ? AND name NOT LIKE ? ORDER BY line",
            (src_path, f"{name}.%", f"{name}.%.%"))
        for msig, mname in cur2.fetchall():
            api_lines.append(f"    {msig or mname}")

    # deps
    cur.execute("SELECT DISTINCT to_name FROM edges "
                "WHERE from_path=? AND kind='import' ORDER BY to_name",
                (src_path,))
    imports = [r[0] for r in cur.fetchall()]
    proj = [i for i in imports if is_project_import(i)]
    deps_show = (proj or imports)[:MAX_DEPS]

    # calls (resolved, to other files)
    cur.execute(
        "SELECT DISTINCT to_name FROM edges WHERE from_path=? AND kind='call' "
        "AND to_path IS NOT NULL AND to_path!=? ORDER BY to_name",
        (src_path, src_path))
    calls = [r[0] for r in cur.fetchall()]
    calls_more = max(0, len(calls) - MAX_CALLS)
    calls_show = calls[:MAX_CALLS]

    # callers
    cur.execute("SELECT name FROM symbols WHERE path=?", (src_path,))
    own = sorted({r[0] for r in cur.fetchall()})
    stem = Path(src_path).stem
    caller_lines = []
    for sym in own:
        seen = sorted(callers_for_symbol(cur, sym, src_path, stem))
        if not seen:
            continue
        short = [relpath(f) for f in seen[:MAX_CALLERS_PER_SYM]]
        extra = (f" (+{len(seen) - MAX_CALLERS_PER_SYM} more)"
                 if len(seen) > MAX_CALLERS_PER_SYM else "")
        caller_lines.append(f"  {sym} ← {', '.join(short)}{extra}")

    out: list[str] = []
    out.append(f"# {relpath(src_path)}  [{lang} · {loc} loc · sha:{sha[:8]}]")
    out.append("api:")
    out.extend(api_lines or ["  (none)"])
    out.append("deps: " + (", ".join(deps_show) if deps_show else "(none)"))
    if calls_more:
        out.append(f"calls: {', '.join(calls_show)} (+{calls_more} more)")
    else:
        out.append("calls: " + (", ".join(calls_show) if calls_show else "(none)"))
    out.append("called_by:")
    out.extend(caller_lines or ["  (none)"])
    out.append(f"{TS_PREFIX} {time.strftime('%Y-%m-%dT%H:%M', time.localtime())}")
    return "\n".join(out) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_keymd_render.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/keymd/engine/keymd_render.py tests/test_keymd_render.py
git commit -m "feat: deterministic LLM-optimized .key.md renderer (no human region)"
```

---

## Task 11: refresh_one — write the sidecar atomically

Generates `<src>.key.md` for the whole file (creating it if missing), atomic tmp+replace, idempotent excluding the timestamp, with a realpath confinement guard. **Simplification vs source:** no sentinel merge — the file is overwritten wholesale.

**Files:**
- Create: `src/keymd/engine/refresh.py`
- Create: `tests/test_refresh.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_refresh.py
from pathlib import Path

from keymd.engine import config, index, refresh
import keymd.engine.parsers.python  # noqa: F401


def test_refresh_creates_and_is_idempotent(env_proj):
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    assert refresh.refresh_one(parser_py) is True            # created
    key = Path(parser_py[:-3] + ".key.md")
    assert key.exists()
    assert "def parse_header(buf: bytes) -> dict" in key.read_text(encoding="utf-8")
    assert refresh.refresh_one(parser_py) is False           # no content change
    key.unlink()  # keep fixture clean


def test_refresh_rejects_outside_root(env_proj, tmp_path):
    outside = tmp_path / "x.py"
    outside.write_text("def f(): pass\n", encoding="utf-8")
    assert refresh.refresh_one(str(outside)) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_refresh.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keymd.engine.refresh'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/keymd/engine/refresh.py
"""refresh.py — (re)generate one .key.md sidecar from the index.

Whole-file generation (no human region). Atomic write, idempotent excluding
the timestamp line, with realpath confinement so a symlinked path cannot write
outside the project root.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

from keymd.engine import config, db
from keymd.engine.keymd_render import render_keymd, strip_timestamp


def _confined(path: str) -> bool:
    try:
        real = os.path.realpath(path)
        root = os.path.realpath(str(config.project_root()))
    except OSError:
        return False
    return real == root or real.startswith(root + os.sep)


def refresh_one(src_path: str) -> bool:
    """Create/refresh the sibling .key.md for src_path. True iff it changed."""
    p = Path(src_path)
    if not p.exists() or get_ext(p) is None:
        return False
    if not _confined(src_path):
        return False
    key_path = Path(src_path[:-len(p.suffix)] + ".key.md")
    if key_path.exists() and not _confined(str(key_path)):
        return False
    db_path = config.index_path()
    if not db_path.exists():
        return False

    con = db.connect(db_path)
    new_content = render_keymd(con, str(p))
    con.close()

    existing = key_path.read_text(encoding="utf-8") if key_path.exists() else ""
    if existing and strip_timestamp(new_content) == strip_timestamp(existing):
        return False

    tmp = key_path.with_suffix(key_path.suffix + ".tmp")
    tmp.write_text(new_content, encoding="utf-8")
    os.replace(tmp, key_path)

    try:
        con = db.connect(db_path)
        sha = __import__("hashlib").sha256(new_content.encode()).hexdigest()
        con.execute(
            "INSERT OR REPLACE INTO keymds(path, src_path, sha256, "
            "auto_refreshed_at) VALUES (?, ?, ?, ?)",
            (str(key_path), str(p), sha, time.time()))
        con.commit()
        con.close()
    except sqlite3.Error:
        pass
    return True


def get_ext(p: Path) -> str | None:
    for ext in config.index_extensions():
        if p.name.endswith(ext):
            return ext
    return None


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        print(f"{arg}: {'updated' if refresh_one(arg) else 'no change'}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_refresh.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/keymd/engine/refresh.py tests/test_refresh.py
git commit -m "feat: refresh_one writes sidecar atomically (confined, idempotent)"
```

---

## Task 12: sync_one — incremental re-index + cascade

Re-index a single edited file and refresh its sidecar plus the sidecars of files that depend on it (so callers' `called_by` lines stay correct after a rename).

**Files:**
- Create: `src/keymd/engine/sync_one.py`
- Create: `tests/test_sync_one.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sync_one.py
from pathlib import Path

from keymd.engine import config, db, index, refresh, sync_one
import keymd.engine.parsers.python  # noqa: F401


def test_sync_one_reindexes_and_refreshes(env_proj):
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    refresh.refresh_one(parser_py)  # ensure a sidecar exists to keep current
    key = Path(parser_py[:-3] + ".key.md")
    # append a new top-level function, then sync
    src = Path(parser_py).read_text(encoding="utf-8")
    Path(parser_py).write_text(src + "\n\ndef brand_new():\n    return 1\n",
                               encoding="utf-8")
    try:
        sync_one.sync_one(parser_py)
        con = db.connect(config.index_path())
        names = {r[0] for r in con.execute(
            "SELECT name FROM symbols WHERE path=?", (parser_py,)).fetchall()}
        assert "brand_new" in names
        con.close()
        assert "brand_new" in key.read_text(encoding="utf-8")
    finally:
        Path(parser_py).write_text(src, encoding="utf-8")  # restore fixture
        if key.exists():
            key.unlink()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sync_one.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keymd.engine.sync_one'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/keymd/engine/sync_one.py
"""sync_one.py — incremental re-index of one file + cascade-refresh dependents."""
from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path

from keymd.engine import config, db
from keymd.engine.index import _lang_for
from keymd.engine.parsers.base import get_parser_for
from keymd.engine.refresh import refresh_one


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _dependents(con, src_path: str) -> list[str]:
    """Files that have a resolved edge pointing into src_path."""
    rows = con.execute(
        "SELECT DISTINCT from_path FROM edges WHERE to_path=? AND from_path!=?",
        (src_path, src_path)).fetchall()
    return [r[0] for r in rows]


def sync_one(src_path: str) -> None:
    p = Path(src_path)
    db_path = config.index_path()
    if not db_path.exists():
        return
    parser = get_parser_for(p)
    if parser is None or not p.exists():
        return
    con = db.connect(db_path)
    sp = str(p)

    # capture dependents BEFORE we mutate edges (so a removed call still cascades)
    dependents = set(_dependents(con, sp))

    con.execute("DELETE FROM symbols WHERE path=?", (sp,))
    con.execute("DELETE FROM edges WHERE from_path=?", (sp,))
    result = parser.parse(p)
    con.execute(
        "INSERT OR REPLACE INTO files(path, lang, sha256, mtime, line_count, "
        "has_keymd, indexed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (sp, _lang_for(p), _file_sha(p), p.stat().st_mtime, result.line_count,
         1 if os.path.exists(sp[:-len(p.suffix)] + ".key.md") else 0, time.time()))
    con.executemany(
        "INSERT OR IGNORE INTO symbols(path, name, kind, line, signature) "
        "VALUES (?, ?, ?, ?, ?)",
        [(sp, s.name, s.kind, s.line, s.signature) for s in result.symbols])
    con.executemany(
        "INSERT OR IGNORE INTO edges(from_path, from_name, to_name, to_path, "
        "kind, line) VALUES (?, ?, ?, NULL, ?, ?)",
        [(sp, e.from_name, e.to_name, e.kind, e.line) for e in result.edges])
    # re-resolve edges touching this file (both directions)
    con.execute("""
        UPDATE edges SET to_path = (
            SELECT path FROM symbols s WHERE s.name = edges.to_name
            GROUP BY s.name HAVING COUNT(DISTINCT s.path)=1 LIMIT 1)
        WHERE to_path IS NULL""")
    con.commit()
    dependents |= set(_dependents(con, sp))
    con.close()

    # refresh own sidecar + each dependent that already has one
    refresh_one(sp)
    for dep in dependents:
        if os.path.exists(dep[:-len(Path(dep).suffix)] + ".key.md"):
            refresh_one(dep)


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        sync_one(arg)
        print(f"{arg}: synced")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_sync_one.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/keymd/engine/sync_one.py tests/test_sync_one.py
git commit -m "feat: sync_one incremental re-index + cascade refresh"
```

---

## Task 13: query module

Port of `query.py` commands, dropping `memories`/`references` (memrefs out of scope) and `inspect`; reusing `graph.callers_for_symbol`. Returns structured data + a `print_*` for the CLI.

**Files:**
- Create: `src/keymd/engine/query.py`
- Create: `tests/test_query.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_query.py
from pathlib import Path

from keymd.engine import index, query
import keymd.engine.parsers.python  # noqa: F401


def test_impact_lists_pipeline(env_proj):
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    res = query.impact(parser_py)
    callers = {c for sym in res["per_symbol"].values() for c in sym}
    assert any(c.endswith("pipeline.py") for c in callers)
    assert res["unique_files"] >= 1


def test_callees_resolved(env_proj):
    index.build(verbose=False)
    pipeline_py = str(Path(env_proj) / "pkg" / "pipeline.py")
    res = query.callees(pipeline_py)
    assert any(to_name == "parse_header" for to_name, _ in res)


def test_search_matches_after_keymd(env_proj):
    from keymd.engine import refresh
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    refresh.refresh_one(parser_py)
    index.build(verbose=False)  # re-index so the new .key.md enters FTS
    hits = query.search("parse_header", limit=5)
    try:
        assert any("parser.key.md" in path for path, _ in hits)
    finally:
        Path(parser_py[:-3] + ".key.md").unlink(missing_ok=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_query.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keymd.engine.query'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/keymd/engine/query.py
"""query.py — read-only structured queries over the keymd index."""
from __future__ import annotations

import os
from pathlib import Path

from keymd.engine import config, db
from keymd.engine.graph import callers_for_symbol, relpath


def _con():
    p = config.index_path()
    if not p.exists():
        raise SystemExit(f"error: index not built at {p}. Run `keymd build`.")
    return db.connect(p)


def callers(symbol: str) -> dict:
    con = _con(); cur = con.cursor()
    cur.execute("SELECT DISTINCT from_path, from_name FROM edges "
                "WHERE kind='call' AND to_name=? ORDER BY from_path", (symbol,))
    exact = [(relpath(p), n) for p, n in cur.fetchall()]
    con.close()
    return {"symbol": symbol, "exact": exact}


def callees(path: str) -> list[tuple[str, str]]:
    path = os.path.abspath(path)
    con = _con(); cur = con.cursor()
    cur.execute("SELECT DISTINCT to_name, to_path FROM edges "
                "WHERE from_path=? AND kind='call' AND to_path IS NOT NULL "
                "ORDER BY to_name", (path,))
    out = [(to_name, relpath(to_path)) for to_name, to_path in cur.fetchall()]
    con.close()
    return out


def symbols(path: str) -> list[tuple[str, str, int]]:
    path = os.path.abspath(path)
    con = _con(); cur = con.cursor()
    cur.execute("SELECT name, kind, line FROM symbols WHERE path=? ORDER BY line",
                (path,))
    out = [(n, k, ln) for n, k, ln in cur.fetchall()]
    con.close()
    return out


def impact(path: str) -> dict:
    path = os.path.abspath(path)
    con = _con(); cur = con.cursor()
    cur.execute("SELECT name FROM symbols WHERE path=? ORDER BY line", (path,))
    own = sorted({r[0] for r in cur.fetchall()})
    stem = Path(path).stem
    per_symbol: dict[str, list[str]] = {}
    total: set[str] = set()
    for sym in own:
        c = {relpath(x) for x in callers_for_symbol(cur, sym, path, stem)}
        if c:
            per_symbol[sym] = sorted(c)
            total |= c
    con.close()
    return {"path": relpath(path), "per_symbol": per_symbol,
            "unique_files": len(total)}


def search(text: str, limit: int = 15) -> list[tuple[str, str]]:
    con = _con(); cur = con.cursor()
    cur.execute("SELECT path, snippet(keymd_fts, 1, '«', '»', '...', 32) "
                "FROM keymd_fts WHERE keymd_fts MATCH ? LIMIT ?", (text, limit))
    out = [(relpath(p), s) for p, s in cur.fetchall()]
    con.close()
    return out


def missing_keymds(top: int = 30) -> list[tuple[int, str]]:
    con = _con(); cur = con.cursor()
    cur.execute("SELECT path, line_count FROM files WHERE line_count>50 "
                "ORDER BY line_count DESC")
    out = []
    for path, lc in cur.fetchall():
        sibling = path[:-len(Path(path).suffix)] + ".key.md"
        if not os.path.exists(sibling):
            out.append((lc, relpath(path)))
            if len(out) >= top:
                break
    con.close()
    return out


def stats() -> dict:
    con = _con(); cur = con.cursor()
    d = {}
    for q, label in [
        ("SELECT COUNT(*) FROM files", "files"),
        ("SELECT COUNT(*) FROM symbols", "symbols"),
        ("SELECT COUNT(*) FROM edges", "edges"),
        ("SELECT COUNT(*) FROM edges WHERE to_path IS NOT NULL", "resolved_edges"),
        ("SELECT COUNT(*) FROM keymds", "keymds"),
    ]:
        d[label] = cur.execute(q).fetchone()[0]
    con.close()
    return d
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_query.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/keymd/engine/query.py tests/test_query.py
git commit -m "feat: structured query API (callers/callees/symbols/impact/search/stats)"
```

---

## Task 14: CLI entry point

**Files:**
- Create: `src/keymd/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
from keymd import cli


def test_cli_build_then_impact(env_proj, capsys):
    assert cli.main(["build", "--quiet"]) == 0
    out = capsys.readouterr().out
    assert "files" in out
    import os
    parser_py = os.path.join(str(env_proj), "pkg", "parser.py")
    assert cli.main(["impact", parser_py]) == 0
    out = capsys.readouterr().out
    assert "pipeline.py" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL — `AttributeError: module 'keymd.cli' has no attribute 'main'` (or ModuleNotFound).

- [ ] **Step 3: Write minimal implementation**

```python
# src/keymd/cli.py
"""keymd CLI — build the index, refresh sidecars, and query structure."""
from __future__ import annotations

import argparse
import json
import sys

import keymd.engine.parsers.python  # noqa: F401  (registers the .py parser)
from keymd.engine import index, query, refresh, sync_one


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="keymd")
    sp = p.add_subparsers(dest="cmd", required=True)

    b = sp.add_parser("build"); b.add_argument("--quiet", action="store_true")
    sp.add_parser("stats")
    r = sp.add_parser("refresh"); r.add_argument("path")
    sy = sp.add_parser("sync"); sy.add_argument("path")
    c = sp.add_parser("callers"); c.add_argument("symbol")
    ce = sp.add_parser("callees"); ce.add_argument("path")
    sym = sp.add_parser("symbols"); sym.add_argument("path")
    im = sp.add_parser("impact"); im.add_argument("path")
    se = sp.add_parser("search"); se.add_argument("text")
    se.add_argument("--limit", type=int, default=15)
    mk = sp.add_parser("missing-keymds"); mk.add_argument("--top", type=int, default=30)

    a = p.parse_args(argv)

    if a.cmd == "build":
        print(json.dumps(index.build(verbose=not a.quiet)))
    elif a.cmd == "stats":
        print(json.dumps(query.stats(), indent=2))
    elif a.cmd == "refresh":
        print(f"{a.path}: {'updated' if refresh.refresh_one(a.path) else 'no change'}")
    elif a.cmd == "sync":
        sync_one.sync_one(a.path); print(f"{a.path}: synced")
    elif a.cmd == "callers":
        res = query.callers(a.symbol)
        print(f"# callers of {res['symbol']} ({len(res['exact'])})")
        for path, name in res["exact"]:
            print(f"  {path:60s} {name}")
    elif a.cmd == "callees":
        rows = query.callees(a.path)
        print(f"# resolved calls from {a.path} ({len(rows)})")
        for to_name, to_path in rows:
            print(f"  {to_name:40s} -> {to_path}")
    elif a.cmd == "symbols":
        for name, kind, line in query.symbols(a.path):
            print(f"  L{line:5d}  {kind:10s}  {name}")
    elif a.cmd == "impact":
        res = query.impact(a.path)
        print(f"# impact for {res['path']}")
        for sym, callers in res["per_symbol"].items():
            print(f"  {sym}")
            for c in callers[:8]:
                print(f"    ← {c}")
        print(f"# unique files depending: {res['unique_files']}")
    elif a.cmd == "search":
        for path, snip in query.search(a.text, a.limit):
            print(f"  {path}\n    {snip}")
    elif a.cmd == "missing-keymds":
        for lc, path in query.missing_keymds(a.top):
            print(f"  {lc:5d}L  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/keymd/cli.py tests/test_cli.py
git commit -m "feat: keymd CLI (build/refresh/sync/query commands)"
```

---

## Task 15: End-to-end smoke test + full suite

**Files:**
- Create: `tests/test_e2e.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_e2e.py
"""End-to-end: build → generate every missing sidecar → query reflects truth."""
import os
from pathlib import Path

from keymd.engine import index, query, refresh
import keymd.engine.parsers.python  # noqa: F401


def test_full_flow(env_proj):
    pkg = Path(env_proj) / "pkg"
    created = [pkg / "parser.key.md", pkg / "pipeline.key.md"]
    try:
        index.build(verbose=False)
        # generate sidecars for both source files
        assert refresh.refresh_one(str(pkg / "parser.py")) is True
        assert refresh.refresh_one(str(pkg / "pipeline.py")) is True
        # parser.key.md must name pipeline as an impacted caller
        text = (pkg / "parser.key.md").read_text(encoding="utf-8")
        assert "called_by:" in text and "pipeline.py" in text
        impact = query.impact(str(pkg / "parser.py"))
        assert impact["unique_files"] >= 1
    finally:
        for k in created:
            k.unlink(missing_ok=True)
```

- [ ] **Step 2: Run test to verify it fails (or passes immediately)**

Run: `python -m pytest tests/test_e2e.py -v`
Expected: PASS (all engine pieces exist by now). If FAIL, the failure pinpoints an integration gap between modules — fix before proceeding.

- [ ] **Step 3: (no new impl unless e2e fails)**

If e2e fails, debug the named integration seam; do not add features.

- [ ] **Step 4: Run the WHOLE suite**

Run: `python -m pytest -v`
Expected: ALL PASS. Record the count.

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e.py
git commit -m "test: end-to-end build→sidecar→query flow"
```

---

## Self-Review

**1. Spec coverage (against `2026-05-29-keymd-token-saver-design.md` §3b, §2):**
- Index engine (tree-sitter → SQLite graph): **Plan 1 delivers the SQLite graph + Python parser; tree-sitter JS/TS deferred to Plan 1b by design** (the `Parser` interface in Task 5 is the seam). ✅ (with documented language scope)
- `.key.md` contract — fully machine-maintained, no human region, LLM-optimized, deterministic structure: Tasks 10–11. ✅
- Signatures in the API section (new vs source): Tasks 6, 10. ✅
- Caller/callee/impact/search queries: Tasks 9, 13, 14. ✅
- Incremental freshness (sync_one + cascade): Task 12. ✅
- Windows `fcntl` blocker removed: staleness drain dropped entirely (refresh.py has no `fcntl`). ✅
- Naming scrub (`AOTC_*`→`KEYMD_*`, `.aotc/`→`.keymd/`): Task 3. ✅
- **Deferred (correctly out of Plan 1):** proxy (Plan 3), watcher (Plan 2), JS/TS parsers (Plan 1b), guardrails (later), LLM digest (v2). Listed in roadmap below.

**2. Placeholder scan:** No "TBD/handle edge cases/similar to". Every code step has complete code; every run step has an exact command + expected outcome. ✅

**3. Type/name consistency:** `callers_for_symbol(cur, sym, defining_path, defining_stem)` defined in Task 9, used identically in Tasks 10 & 13. `render_keymd(con, src_path)` + `strip_timestamp` defined Task 10, used Task 11. `refresh_one(src_path)->bool` defined Task 11, used Tasks 12,14. `sync_one(src_path)` Task 12. `ParseResult`/`Symbol`/`Edge` fields consistent across Tasks 5,6,8,12. `index.build(verbose)` + `_lang_for` Task 8, reused Task 12. Env vars `KEYMD_PROJECT_ROOT`/`KEYMD_INDEX_PATH` consistent (Tasks 2,3). ✅

*One watch item for the executor:* `index.build` deletes & recreates the DB; `search` tests re-build after writing a sidecar so the new `.key.md` enters FTS (Task 13 test does this explicitly). `sync_one` does NOT re-add FTS rows for changed sidecars — acceptable in Plan 1 (FTS freshness on sidecar writes is a Plan 2/watcher concern); noted so it isn't mistaken for a bug.

---

## Phases 2–5 — outline (detailed in this same document after the Phase 1 review checkpoint)

- **Phase 1b — JS/TS parsers:** `parsers/javascript.py` + `parsers/typescript.py` behind the Task-5 `Parser` interface, using `tree-sitter` + `tree-sitter-language-pack`. **Pinned API (verified May 2026):** `from tree_sitter_language_pack import get_parser`; parse `bytes`; queries use `tree_sitter.Query(language, src)` + `QueryCursor(query).captures(root)` returning `{capture_name: [nodes]}` (the `Query.captures()` method was removed at 0.25.x). Add per-language collision sets analogous to `STDLIB_STEMS`. Pin `tree-sitter>=0.25,<0.26`.
- **Plan 2 — FS watcher:** debounced watcher (`watchdog`) that calls `sync_one` on source writes and re-indexes changed `.key.md` into FTS; daemonizable.
- **Plan 3 — Enforcing proxy:** asyncio reverse-proxy (Anthropic + OpenAI wire formats, SSE), virtual `keymd_*` tools answered from this engine's `query` API, pre-read gate with `:full` escalation, deterministic rewrite for prompt-cache safety, output-cap. The hard core.
- **Plan 4 — Host integration + A/B benchmark:** per-host setup (Claude Code `ANTHROPIC_BASE_URL`, Codex, Cline), `AGENTS.md` snippet, and the paired-subagent token benchmark on a public repo.
- **Later (v1.1):** portable guardrails module; `/handoff` session-compaction.
