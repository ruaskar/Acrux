# keymd Phase 3 — Enforcing Proxy (full-TDD expansion)

> **Companion to** `2026-05-29-keymd-implementation-plan.md` (the consolidated plan keeps the Phase 3 *design overview*; this file is its executable TDD expansion — the proxy is a sub-project). REQUIRED SUB-SKILL on execution: superpowers:subagent-driven-development or executing-plans.

**Goal (Phase 3a):** a localhost reverse-proxy that the agent's LLM endpoint points at, which forwards to the real upstream with the user's key and, in-flight, **gates** a full read of a large indexed file behind its `.key.md` summary and answers **virtual `keymd_*` tools** from the Phase-1 query API — proven end-to-end against a **mock upstream** (zero API spend). Anthropic Messages wire format, non-streaming.

**Architecture:** pure core + thin async shell.
- `adapters/` — parse a provider request to neutral ops and re-emit provider JSON. `AnthropicAdapter` only in 3a (OpenAI in 3b). Pure, sync, fully unit-tested.
- `gate.py` — classification policy (virtual / gated-read / host) + transcript-derived "already-summarized" detection. Pure.
- `tools.py` + `engine.py` — virtual tool definitions and an answerer that calls the Phase-1 `query`/`render_keymd` and disk. Pure-ish (reads index/disk).
- `orchestrator.py` — `async complete(body, adapter, upstream, *, threshold)` runs the inner loop, awaiting an **injected** `upstream(body)->dict`. No network in tests.
- `server.py` — Starlette ASGI shell + `keymd serve`; smoke-tested via `httpx.ASGITransport` against a mock upstream.

**Locked design decisions** (rationale in the cover message): virtual-tool escalation (`keymd_read_full`), all-or-forward turn resolution, stateless transcript-derived loop-guard, `MAX_INNER_TURNS` safety bound.

**Tech:** `httpx` (upstream client + test transport), `starlette` + `uvicorn` (ASGI server) in a new `[proxy]` extra so the engine stays dependency-free. Async tests use `asyncio.run(...)` (no `pytest-asyncio` dependency).

## Status — IMPLEMENTED & GREEN (as-built, 2026-05-29)

Phase 3a is implemented under `src/keymd/proxy/` and **56/56 tests pass** (28 Phase 1 + 28 proxy) on Python 3.11.9/Windows, including the ASGI server smoke test. Dogfooded on the live repo: the gate fired on `index.py` (153 loc > 120 threshold, summary injected, host saw only the final turn) and confinement refused `C:/Windows/win.ini` with no content leak. **The committed source under `src/keymd/proxy/` is canonical** — the task code blocks below are the pre-review draft; the as-built deltas folded in from the adversarial review are:

- **[CRITICAL] `engine.full` path confinement** — reuses `keymd.engine.refresh._confined`; refuses any path outside the project root (closes the confused-deputy exfiltration of `/etc/passwd`/SSH keys/`.env`/API keys). Test: `test_full_refuses_outside_project_root`.
- **[MAJOR] realpath canonicalization** — `engine.canon = os.path.realpath` (not `os.path.abspath`) everywhere model paths enter (gate, tools, summary marker), matching `build()`'s resolved storage → no silent gate no-op under symlinked roots / Windows casing.
- **[MAJOR] `engine.full` line cap** (`MAX_FULL_LINES=800`) — truncate-with-notice so the model-advertised full-read can't dump an unbounded blob. Test: `test_full_truncates_huge_file`.
- **[MAJOR] synthetic-terminal on budget exhaustion** — `adapter.terminal(...)` returns a consumable `end_turn` turn, never an unanswerable `tool_use` turn. Test: `test_budget_exhaustion_returns_synthetic_terminal`.
- **[MAJOR] `engine.search` FTS5 survival** — catches `sqlite3.OperationalError` on arbitrary model text (`"a AND b"`, `"foo:bar"`) and retries quoted. Test: `test_search_survives_fts_syntax`.
- **[MAJOR] façade graceful without index** — `impact/callers/callees/search` return a sentinel instead of raising `SystemExit` (worker-killer in server mode). Test: `test_structure_queries_graceful_without_index`.
- **[MINOR] idempotent directive inject** (marker-guarded, like the tools branch — `test_inject_is_idempotent`); **deterministic summary** (`gate.summary_result` strips the live timestamp — `test_summary_result_marker_and_deterministic`); **intra-turn dedup** (one summary computed per path per turn, still one tool_result per id — `test_multi_nonhost_turn_answers_every_id_in_order`); **lazy `engine` import** in `tools.answer` (removes the task-ordering import hazard); **directive wording** softened to "LARGE file".
- **SHIPPED beyond 3a (extended):** the **OpenAI adapter** (`adapters/openai.py`, Chat Completions) + the **`/v1/chat/completions`** server route — the orchestrator is adapter-agnostic, proven by `test_proxy_adapter_openai.py` + `test_proxy_server_openai_smoke.py`.
- **Deferred → Phase 3b:** Grep gating, **SSE streaming to a live host** (real Claude Code/Codex stream by default), OpenAI **Responses API**, prompt-cache-safe blob redirect, `keymd_symbol`, output-cap. Real live-host use needs 3b streaming.

### Post end-to-end-review fix (2026-05-30)
A 4-agent end-to-end review found the **loop-guard was Anthropic-only**: `gate.summarized_paths` parsed only Anthropic `tool_result` blocks, so on OpenAI hosts (where a tool result is `{"role":"tool","content":"<str>"}`) the summary marker was never harvested and the same large file re-gated every inner turn (up to 24× upstream calls). Fixed: `summarized_paths` now also scans OpenAI `role:"tool"` string content. Regression: `test_review_fixes.py::test_openai_loopguard_marker_harvested`. Also: `engine.canon` now delegates to `config.canonical` so all faculties share one realpath normalization.

## Shared-contract addendum (proxy-facing — add to the consolidated plan's Contracts on merge)
- **Neutral type:** `ToolCall{id:str, name:str, input:dict}`.
- **WireAdapter:** `inject(body)->body` (add virtual tool defs + system directive) · `tool_uses(resp)->[ToolCall]` · `messages(body)->list` · `append_assistant(body, resp)->body` · `append_tool_results(body, [(id,text)])->body` · **`terminal(text, template)->dict`** (synthetic end-turn for the budget-exhaustion bail — required by the orchestrator; a new adapter that omits it crashes on exhaustion).
- **Engine façade (`proxy/engine.py`):** `summary(abspath)->str|None` (render_keymd) · `full(abspath)->str` · `is_indexed_large(abspath, threshold)->bool` · `impact/callers/callees/search` (delegate to `keymd.engine.query`).
- **Summary marker:** a gated/`keymd_read` summary begins with the line `⟪keymd-summary:{abspath}⟫` so the transcript-scan loop-guard can detect prior summaries.
- **Virtual tools (3a):** `keymd_read(path)`, `keymd_read_full(path)`, `keymd_impact(path)`, `keymd_callers(symbol)`, `keymd_callees(path)`, `keymd_search(text)`. (`keymd_symbol` needs symbol end-lines → 3b.)
- **Gated host read tools:** `READ_TOOLS = {"Read","read_file","view","cat"}`; path keys tried: `file_path, path, target_file, filename`.

---

## Task 3a.1: deps + proxy package skeleton

**Files:** Modify `pyproject.toml` (add `[project.optional-dependencies] proxy = ["httpx>=0.27","starlette>=0.37","uvicorn>=0.30"]`); Create `src/keymd/proxy/__init__.py`, `src/keymd/proxy/adapters/__init__.py`; Create `tests/test_proxy_skeleton.py`.

- [ ] **Step 1: failing test**
```python
# tests/test_proxy_skeleton.py
def test_proxy_package_importable():
    import keymd.proxy  # noqa: F401
    assert True
```
- [ ] **Step 2: run** `python -m pytest tests/test_proxy_skeleton.py -v` → FAIL (`No module named 'keymd.proxy'`).
- [ ] **Step 3:** create the two `__init__.py` (empty) and add the `proxy` extra to `pyproject.toml`. `python -m pip install -e ".[dev,proxy]"`.
- [ ] **Step 4: run** → PASS. (If httpx/starlette unavailable offline, the orchestrator/adapter/gate tests still run — only the server smoke test needs them.)
- [ ] **Step 5: commit** `feat(proxy): package skeleton + [proxy] extra`.

---

## Task 3a.2: neutral types + WireAdapter protocol

**Files:** Create `src/keymd/proxy/adapters/base.py`; Create `tests/test_proxy_adapter_base.py`.

- [ ] **Step 1: failing test**
```python
# tests/test_proxy_adapter_base.py
from keymd.proxy.adapters import base


def test_toolcall_shape():
    tc = base.ToolCall(id="t1", name="Read", input={"file_path": "a.py"})
    assert tc.id == "t1" and tc.name == "Read" and tc.input["file_path"] == "a.py"
```
- [ ] **Step 2: run** → FAIL (module missing).
- [ ] **Step 3: implement**
```python
# src/keymd/proxy/adapters/base.py
"""base.py — neutral proxy types + the WireAdapter protocol."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict = field(default_factory=dict)


class WireAdapter(Protocol):
    def inject(self, body: dict) -> dict: ...
    def tool_uses(self, resp: dict) -> list[ToolCall]: ...
    def messages(self, body: dict) -> list: ...
    def append_assistant(self, body: dict, resp: dict) -> dict: ...
    def append_tool_results(self, body: dict, results: list[tuple[str, str]]) -> dict: ...
```
- [ ] **Step 4: run** → PASS.
- [ ] **Step 5: commit** `feat(proxy): neutral ToolCall + WireAdapter protocol`.

---

## Task 3a.3: virtual tool definitions + directive

**Files:** Create `src/keymd/proxy/tools.py`; Create `tests/test_proxy_tool_defs.py`.

- [ ] **Step 1: failing test**
```python
# tests/test_proxy_tool_defs.py
from keymd.proxy import tools


def test_virtual_defs_cover_expected_tools():
    names = {d["name"] for d in tools.VIRTUAL_TOOL_DEFS}
    assert {"keymd_read", "keymd_read_full", "keymd_impact",
            "keymd_callers", "keymd_callees", "keymd_search"} <= names
    # each def has a description and an input schema (provider-neutral)
    for d in tools.VIRTUAL_TOOL_DEFS:
        assert d["description"] and d["schema"]["type"] == "object"


def test_directive_mentions_summary_first():
    assert "keymd_read" in tools.SYSTEM_DIRECTIVE
    assert "keymd_read_full" in tools.SYSTEM_DIRECTIVE
```
- [ ] **Step 2: run** → FAIL.
- [ ] **Step 3: implement**
```python
# src/keymd/proxy/tools.py
"""tools.py — virtual keymd_* tool definitions, the steering directive, and the
answerer that maps a virtual call to the Phase-1 engine."""
from __future__ import annotations

import json

from keymd.proxy import engine
from keymd.proxy.adapters.base import ToolCall

_PATH = {"type": "object", "properties": {"path": {"type": "string"}},
         "required": ["path"]}
_SYM = {"type": "object", "properties": {"symbol": {"type": "string"}},
        "required": ["symbol"]}
_TXT = {"type": "object", "properties": {"text": {"type": "string"}},
        "required": ["text"]}

VIRTUAL_TOOL_DEFS = [
    {"name": "keymd_read", "schema": _PATH,
     "description": "Return the compact .key.md summary (API, deps, callers) for a "
                    "file. Prefer this before reading a large file in full."},
    {"name": "keymd_read_full", "schema": _PATH,
     "description": "Return the FULL source of a file. Use only when the summary "
                    "from keymd_read is insufficient."},
    {"name": "keymd_impact", "schema": _PATH,
     "description": "List files that depend on (call into) this file."},
    {"name": "keymd_callers", "schema": _SYM,
     "description": "List call sites of a symbol (exact + leaf-name matches)."},
    {"name": "keymd_callees", "schema": _PATH,
     "description": "List resolved outgoing calls from a file."},
    {"name": "keymd_search", "schema": _TXT,
     "description": "Full-text search across all .key.md summaries."},
]

SYSTEM_DIRECTIVE = (
    "\n\n[keymd] Before reading a large file in full, call keymd_read(path) for "
    "its compact summary; use keymd_impact/keymd_callers/keymd_callees/keymd_search "
    "for structure instead of grepping. Call keymd_read_full(path) only when the "
    "summary is genuinely insufficient."
)


def answer(call: ToolCall, *, abspath=None) -> str:
    """Resolve a virtual keymd_* tool to text. `abspath` is an injectable path
    normalizer (defaults to os.path.abspath) so tests can pin behavior."""
    import os
    ap = abspath or os.path.abspath
    name, inp = call.name, call.input
    if name == "keymd_read":
        return engine.summary(ap(inp["path"])) or "(file not indexed)"
    if name == "keymd_read_full":
        return engine.full(ap(inp["path"]))
    if name == "keymd_impact":
        return json.dumps(engine.impact(ap(inp["path"])), indent=2)
    if name == "keymd_callers":
        return json.dumps(engine.callers(inp["symbol"]), indent=2)
    if name == "keymd_callees":
        return json.dumps(engine.callees(ap(inp["path"])), indent=2)
    if name == "keymd_search":
        return json.dumps(engine.search(inp["text"]), indent=2)
    return f"(unknown keymd tool: {name})"
```
- [ ] **Step 4: run** → PASS (imports `engine`, written next; if import fails, do 3a.4 first then re-run — order is fine since both land before the answerer is tested).
- [ ] **Step 5: commit** `feat(proxy): virtual tool defs + steering directive + answerer`.

---

## Task 3a.4: engine façade

**Files:** Create `src/keymd/proxy/engine.py`; Create `tests/test_proxy_engine.py`.

- [ ] **Step 1: failing test**
```python
# tests/test_proxy_engine.py
from pathlib import Path
from keymd.engine import index
from keymd.proxy import engine
import keymd.engine.parsers.python  # noqa: F401


def test_facade_summary_and_indexed_large(env_proj):
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    s = engine.summary(parser_py)
    assert s and s.startswith("# ")
    # threshold 0 => any indexed file counts as "large"; unknown file => False
    assert engine.is_indexed_large(parser_py, threshold=0) is True
    assert engine.is_indexed_large(str(Path(env_proj) / "nope.py"), threshold=0) is False


def test_facade_full_reads_disk(env_proj):
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    assert "def parse_header" in engine.full(parser_py)
```
- [ ] **Step 2: run** → FAIL.
- [ ] **Step 3: implement**
```python
# src/keymd/proxy/engine.py
"""engine.py — thin façade over the Phase-1 engine for the proxy layer.

Consumes only the Shared Contracts (query.*, render_keymd, the files table).
All paths are expected absolute (the caller normalizes)."""
from __future__ import annotations

from pathlib import Path

from keymd.engine import config, db, query
from keymd.engine.keymd_render import render_keymd


def _con_or_none():
    p = config.index_path()
    return db.connect(p) if p.exists() else None


def summary(abspath: str) -> str | None:
    con = _con_or_none()
    if con is None:
        return None
    row = con.execute("SELECT 1 FROM files WHERE path=?", (abspath,)).fetchone()
    if row is None:
        con.close()
        return None
    text = render_keymd(con, abspath)
    con.close()
    return text


def is_indexed_large(abspath: str, threshold: int) -> bool:
    con = _con_or_none()
    if con is None:
        return False
    row = con.execute("SELECT line_count FROM files WHERE path=?",
                      (abspath,)).fetchone()
    con.close()
    return bool(row) and row[0] > threshold


def full(abspath: str) -> str:
    try:
        return Path(abspath).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"(error reading {abspath}: {e})"


def impact(abspath: str) -> dict:
    return query.impact(abspath)


def callers(symbol: str) -> dict:
    return query.callers(symbol)


def callees(abspath: str) -> list:
    return query.callees(abspath)


def search(text: str, limit: int = 15) -> list:
    return query.search(text, limit)
```
- [ ] **Step 4: run** → PASS. Re-run `tests/test_proxy_tool_defs.py` to confirm the answerer imports resolve.
- [ ] **Step 5: commit** `feat(proxy): engine façade over query + render_keymd`.

---

## Task 3a.5: gate classification policy

**Files:** Create `src/keymd/proxy/gate.py`; Create `tests/test_proxy_gate.py`.

- [ ] **Step 1: failing test**
```python
# tests/test_proxy_gate.py
from pathlib import Path
from keymd.engine import index
from keymd.proxy import gate
from keymd.proxy.adapters.base import ToolCall
import keymd.engine.parsers.python  # noqa: F401


def test_classify(env_proj):
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    # virtual
    assert gate.classify(ToolCall("1", "keymd_impact", {"path": parser_py}),
                         summarized=set(), threshold=0).kind == "virtual"
    # gated: a Read of an indexed (>threshold) file not yet summarized
    g = gate.classify(ToolCall("2", "Read", {"file_path": parser_py}),
                      summarized=set(), threshold=0)
    assert g.kind == "gated" and g.path.endswith("parser.py")
    # host: a Bash call
    assert gate.classify(ToolCall("3", "Bash", {"command": "ls"}),
                         summarized=set(), threshold=0).kind == "host"
    # loop-guard: same Read but path already summarized => pass through as host
    import os
    assert gate.classify(ToolCall("4", "Read", {"file_path": parser_py}),
                         summarized={os.path.abspath(parser_py)},
                         threshold=0).kind == "host"
    # not-indexed Read => host (engine can't help)
    assert gate.classify(ToolCall("5", "Read", {"file_path": str(Path(env_proj) / "nope.py")}),
                         summarized=set(), threshold=0).kind == "host"


def test_summarized_paths_from_transcript():
    msgs = [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "x",
         "content": "⟪keymd-summary:/abs/parser.py⟫\n# parser..."}]}]
    assert "/abs/parser.py" in gate.summarized_paths(msgs)


def test_summary_result_has_marker(env_proj):
    index.build(verbose=False)
    import os
    parser_py = os.path.abspath(str(Path(env_proj) / "pkg" / "parser.py"))
    text = gate.summary_result(parser_py)
    assert text.startswith(f"⟪keymd-summary:{parser_py}⟫")
    assert "keymd_read_full" in text
```
- [ ] **Step 2: run** → FAIL.
- [ ] **Step 3: implement**
```python
# src/keymd/proxy/gate.py
"""gate.py — decide how each tool call is handled: virtual / gated / host.

Pure policy over a ToolCall + the set of paths already summarized in the
transcript (the stateless loop-guard). Forwarding rule lives in the
orchestrator (all-or-forward)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from keymd.proxy import engine
from keymd.proxy.adapters.base import ToolCall

READ_TOOLS = {"Read", "read_file", "view", "cat"}
_PATH_KEYS = ("file_path", "path", "target_file", "filename")
MARKER_RE = re.compile(r"⟪keymd-summary:(.+?)⟫")


@dataclass
class Decision:
    kind: str            # "virtual" | "gated" | "host"
    call: ToolCall
    path: str | None = None   # absolute, set when kind == "gated"


def _extract_path(inp: dict) -> str | None:
    for k in _PATH_KEYS:
        v = inp.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def classify(call: ToolCall, *, summarized: set[str], threshold: int) -> Decision:
    if call.name.startswith("keymd_"):
        return Decision("virtual", call)
    if call.name in READ_TOOLS:
        raw = _extract_path(call.input)
        if raw:
            ap = os.path.abspath(raw)
            if ap not in summarized and engine.is_indexed_large(ap, threshold):
                return Decision("gated", call, ap)
    return Decision("host", call)


def summarized_paths(messages: list) -> set[str]:
    """Absolute paths for which a keymd summary already appears in the transcript."""
    found: set[str] = set()
    for m in messages:
        content = m.get("content")
        blocks = content if isinstance(content, list) else []
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                c = b.get("content")
                text = c if isinstance(c, str) else (
                    " ".join(x.get("text", "") for x in c
                             if isinstance(x, dict)) if isinstance(c, list) else "")
                found.update(MARKER_RE.findall(text))
    return found


def summary_result(abspath: str) -> str:
    body = engine.summary(abspath) or "(file not indexed)"
    return (f"⟪keymd-summary:{abspath}⟫\n{body}\n\n"
            "(Generated summary. Call keymd_read_full(path) for the full source, "
            "or keymd_impact/keymd_callers for structure.)")
```
- [ ] **Step 4: run** → PASS.
- [ ] **Step 5: commit** `feat(proxy): gate classification + transcript loop-guard`.

---

## Task 3a.6: Anthropic wire adapter

**Files:** Create `src/keymd/proxy/adapters/anthropic.py`; Create `tests/test_proxy_adapter_anthropic.py`.

- [ ] **Step 1: failing test**
```python
# tests/test_proxy_adapter_anthropic.py
from keymd.proxy.adapters.anthropic import AnthropicAdapter
from keymd.proxy import tools

A = AnthropicAdapter()


def test_inject_adds_tools_and_directive():
    body = {"model": "m", "messages": [], "system": "base", "tools": [{"name": "Read"}]}
    out = A.inject(dict(body))
    names = {t["name"] for t in out["tools"]}
    assert {"Read", "keymd_read", "keymd_impact"} <= names
    assert "keymd_read" in out["system"]  # directive appended
    # input_schema is the Anthropic key (not "schema")
    vk = next(t for t in out["tools"] if t["name"] == "keymd_read")
    assert vk["input_schema"]["type"] == "object"


def test_inject_handles_block_system_and_no_tools():
    body = {"messages": [], "system": [{"type": "text", "text": "base"}]}
    out = A.inject(dict(body))
    assert any("keymd_read" in b.get("text", "") for b in out["system"])
    assert any(t["name"] == "keymd_read" for t in out["tools"])


def test_tool_uses_and_appends():
    resp = {"role": "assistant", "stop_reason": "tool_use", "content": [
        {"type": "text", "text": "ok"},
        {"type": "tool_use", "id": "tu1", "name": "Read", "input": {"file_path": "a.py"}}]}
    calls = A.tool_uses(resp)
    assert len(calls) == 1 and calls[0].id == "tu1" and calls[0].name == "Read"
    body = {"messages": []}
    body = A.append_assistant(body, resp)
    body = A.append_tool_results(body, [("tu1", "SUMMARY")])
    assert body["messages"][0]["role"] == "assistant"
    tr = body["messages"][1]
    assert tr["role"] == "user" and tr["content"][0]["type"] == "tool_result"
    assert tr["content"][0]["tool_use_id"] == "tu1"
    assert tr["content"][0]["content"] == "SUMMARY"


def test_no_tool_uses_on_final():
    assert A.tool_uses({"content": [{"type": "text", "text": "done"}]}) == []
```
- [ ] **Step 2: run** → FAIL.
- [ ] **Step 3: implement**
```python
# src/keymd/proxy/adapters/anthropic.py
"""anthropic.py — Anthropic Messages API wire adapter."""
from __future__ import annotations

from keymd.proxy import tools
from keymd.proxy.adapters.base import ToolCall


class AnthropicAdapter:
    def inject(self, body: dict) -> dict:
        defs = [{"name": d["name"], "description": d["description"],
                 "input_schema": d["schema"]} for d in tools.VIRTUAL_TOOL_DEFS]
        existing = body.get("tools") or []
        have = {t.get("name") for t in existing}
        body["tools"] = existing + [d for d in defs if d["name"] not in have]
        sysv = body.get("system")
        if sysv is None:
            body["system"] = tools.SYSTEM_DIRECTIVE.strip()
        elif isinstance(sysv, str):
            body["system"] = sysv + tools.SYSTEM_DIRECTIVE
        elif isinstance(sysv, list):
            body["system"] = sysv + [{"type": "text", "text": tools.SYSTEM_DIRECTIVE}]
        return body

    def tool_uses(self, resp: dict) -> list[ToolCall]:
        out = []
        for b in resp.get("content", []) or []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                out.append(ToolCall(b["id"], b["name"], b.get("input", {}) or {}))
        return out

    def messages(self, body: dict) -> list:
        return body.get("messages", []) or []

    def append_assistant(self, body: dict, resp: dict) -> dict:
        body.setdefault("messages", []).append(
            {"role": "assistant", "content": resp.get("content", [])})
        return body

    def append_tool_results(self, body: dict, results: list[tuple[str, str]]) -> dict:
        body.setdefault("messages", []).append({
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tid, "content": txt}
                        for tid, txt in results]})
        return body
```
- [ ] **Step 4: run** → PASS.
- [ ] **Step 5: commit** `feat(proxy): Anthropic Messages wire adapter`.

---

## Task 3a.7: orchestrator inner loop (the core)

**Files:** Create `src/keymd/proxy/orchestrator.py`; Create `tests/test_proxy_orchestrator.py`.

- [ ] **Step 1: failing test** — scripted mock upstream + the real engine on the fixture (threshold 0 ⇒ any indexed file is "large").
```python
# tests/test_proxy_orchestrator.py
import asyncio
from pathlib import Path

from keymd.engine import index
from keymd.proxy.adapters.anthropic import AnthropicAdapter
from keymd.proxy.orchestrator import complete
import keymd.engine.parsers.python  # noqa: F401


def _mock_upstream(scripted):
    calls = {"bodies": []}

    async def upstream(body):
        calls["bodies"].append(body)
        return scripted[len(calls["bodies"]) - 1]
    return upstream, calls


def _read(file_path, tid="t1"):
    return {"role": "assistant", "stop_reason": "tool_use", "content": [
        {"type": "tool_use", "id": tid, "name": "Read", "input": {"file_path": file_path}}]}


def _virtual(name, inp, tid="v1"):
    return {"role": "assistant", "stop_reason": "tool_use", "content": [
        {"type": "tool_use", "id": tid, "name": name, "input": inp}]}


def _final(text="done"):
    return {"role": "assistant", "stop_reason": "end_turn",
            "content": [{"type": "text", "text": text}]}


def _run(env_proj, scripted):
    index.build(verbose=False)
    up, calls = _mock_upstream(scripted)
    body = {"model": "m", "system": "s", "messages": [
        {"role": "user", "content": [{"type": "text", "text": "refactor it"}]}]}
    resp = asyncio.run(complete(body, AnthropicAdapter(), up, threshold=0))
    return resp, calls


def test_gated_read_is_summarized_then_proceeds(env_proj):
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    resp, calls = _run(env_proj, [_read(parser_py), _final("ok")])
    # host sees only the final turn
    assert resp["stop_reason"] == "end_turn"
    # the loop ran twice; the 2nd upstream body carries the injected summary
    assert len(calls["bodies"]) == 2
    second = calls["bodies"][1]["messages"]
    tr = second[-1]["content"][0]
    assert tr["type"] == "tool_result" and "keymd-summary" in tr["content"]


def test_virtual_tool_answered_locally(env_proj):
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    resp, calls = _run(env_proj, [_virtual("keymd_impact", {"path": parser_py}), _final()])
    assert resp["stop_reason"] == "end_turn"
    assert len(calls["bodies"]) == 2  # impact answered locally, never returned to host


def test_host_tool_forwarded_immediately(env_proj):
    bash = {"role": "assistant", "stop_reason": "tool_use", "content": [
        {"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "ls"}}]}
    resp, calls = _run(env_proj, [bash, _final()])
    assert resp["content"][0]["name"] == "Bash"   # returned to host as-is
    assert len(calls["bodies"]) == 1


def test_mixed_turn_forwards_whole_turn(env_proj):
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    mixed = {"role": "assistant", "stop_reason": "tool_use", "content": [
        {"type": "tool_use", "id": "r1", "name": "Read", "input": {"file_path": parser_py}},
        {"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "ls"}}]}
    resp, calls = _run(env_proj, [mixed, _final()])
    assert len(resp["content"]) == 2  # forwarded intact (all-or-forward)
    assert len(calls["bodies"]) == 1


def test_final_with_no_tools_returns_immediately(env_proj):
    resp, calls = _run(env_proj, [_final("hi")])
    assert resp["content"][0]["text"] == "hi"
    assert len(calls["bodies"]) == 1
```
- [ ] **Step 2: run** → FAIL (`No module named 'keymd.proxy.orchestrator'`).
- [ ] **Step 3: implement**
```python
# src/keymd/proxy/orchestrator.py
"""orchestrator.py — the gate inner loop.

complete() injects virtual tools, then repeatedly calls the (injected) upstream.
A turn is resolved LOCALLY only if every tool_use in it is virtual-or-gated
(all-or-forward); otherwise the whole turn is returned to the host. Bounded by
MAX_INNER_TURNS."""
from __future__ import annotations

from keymd.proxy import gate, tools
from keymd.proxy.adapters.base import WireAdapter

MAX_INNER_TURNS = 24


async def complete(body: dict, adapter: WireAdapter, upstream, *,
                   threshold: int = 400) -> dict:
    body = adapter.inject(body)
    for _ in range(MAX_INNER_TURNS):
        resp = await upstream(body)
        calls = adapter.tool_uses(resp)
        if not calls:
            return resp  # final assistant answer — hand to host
        summarized = gate.summarized_paths(adapter.messages(body))
        decisions = [gate.classify(c, summarized=summarized, threshold=threshold)
                     for c in calls]
        if any(d.kind == "host" for d in decisions):
            return resp  # all-or-forward: host executes the whole turn
        # every call is virtual or gated → resolve locally and loop
        body = adapter.append_assistant(body, resp)
        results: list[tuple[str, str]] = []
        for d in decisions:
            if d.kind == "virtual":
                results.append((d.call.id, tools.answer(d.call)))
            else:  # gated read
                results.append((d.call.id, gate.summary_result(d.path)))
        body = adapter.append_tool_results(body, results)
    return resp  # safety bail
```
- [ ] **Step 4: run** → PASS (5 tests). This is the heart of the phase — if any fail, debug here before proceeding.
- [ ] **Step 5: commit** `feat(proxy): gate inner-loop orchestrator (all-or-forward, bounded)`.

---

## Task 3a.8: ASGI server shell + `keymd serve`

**Files:** Create `src/keymd/proxy/server.py`; Modify `src/keymd/cli.py` (add `serve`); Create `tests/test_proxy_server_smoke.py`.

- [ ] **Step 1: failing test** — drive the ASGI app via `httpx.ASGITransport` with a **monkeypatched upstream** (no network). Skip if httpx/starlette absent.
```python
# tests/test_proxy_server_smoke.py
import json
import pytest
from pathlib import Path

pytest.importorskip("httpx")
pytest.importorskip("starlette")
import asyncio
import httpx
from keymd.engine import index
from keymd.proxy import server
import keymd.engine.parsers.python  # noqa: F401


def test_server_gates_read_via_asgi(env_proj, monkeypatch):
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    scripted = [
        {"role": "assistant", "stop_reason": "tool_use", "content": [
            {"type": "tool_use", "id": "t1", "name": "Read",
             "input": {"file_path": parser_py}}]},
        {"role": "assistant", "stop_reason": "end_turn",
         "content": [{"type": "text", "text": "ok"}]},
    ]
    state = {"n": 0}

    async def fake_upstream(body, headers):
        r = scripted[state["n"]]; state["n"] += 1
        return r
    monkeypatch.setattr(server, "forward_upstream", fake_upstream)

    app = server.build_app(threshold=0)

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://t") as c:
            return await c.post("/v1/messages",
                                json={"model": "m", "system": "s", "messages": [
                                    {"role": "user", "content": [
                                        {"type": "text", "text": "go"}]}]})
    resp = asyncio.run(go())
    assert resp.status_code == 200
    assert resp.json()["stop_reason"] == "end_turn"
    assert state["n"] == 2  # gated turn resolved locally, then final
```
- [ ] **Step 2: run** → FAIL (`No module named 'keymd.proxy.server'`) or skip if deps absent.
- [ ] **Step 3: implement** `server.py`: a Starlette app with `POST /v1/messages` that reads the JSON body, builds an `upstream(body)` closure wrapping the module-level `forward_upstream(body, headers)` (httpx POST to the real Anthropic base URL with the inbound `x-api-key`/`authorization` headers, IPv4 transport `local_address="0.0.0.0"`), calls `orchestrator.complete(body, AnthropicAdapter(), upstream, threshold=...)`, and returns `JSONResponse(result)`. `build_app(threshold)` wires it; `serve(host, port, threshold)` runs uvicorn. Add CLI `serve --port 8787 --threshold 400`. (Streaming + real-host wiring are 3b — 3a forwards/returns non-streamed JSON, sufficient for the gate logic and the smoke test.)
- [ ] **Step 4: run** → PASS (or `skipped` offline). Plus a MANUAL note: `keymd serve` + `ANTHROPIC_BASE_URL=http://localhost:8787` in Claude Code; confirm a read of a large indexed file returns a summary first.
- [ ] **Step 5: commit** `feat(proxy): Starlette serve shell + keymd serve (non-streaming 3a)`.

---

## Task 3a.9: full-suite gate + dogfood

- [ ] **Step 1:** `python -m pytest -v` → ALL PASS (record count: Phase 1's 28 + the proxy tests). 
- [ ] **Step 2:** dogfood the orchestrator against the keymd repo itself: a tiny script that builds the index, scripts a `Read(src/keymd/engine/index.py)` then a final, and asserts the summary was injected — confirms the gate works on real, large files (index.py is ~150 LOC > a realistic threshold like 120).
- [ ] **Step 3:** commit `test(proxy): full-suite + real-file dogfood`.

---

## Phase 3b — outline (next focused pass after 3a is green + reviewed)
- **OpenAI adapter** (`adapters/openai.py`): Chat-Completions + Responses `tool_calls`/`role:"tool"`; same orchestrator, new adapter. Table-driven parity tests.
- **Streaming (SSE):** inner-loop turns stay non-streamed; the FINAL turn streams through untouched. Required for real Claude Code use.
- **Prompt-cache-safe blob redirect:** rewrite oversized file blobs already present in `tool_result`s (non-gated paths: @-mentions, pastes) deterministically, preserving the cached prefix (the breakpoint-invariance test).
- **`keymd_symbol`:** needs symbol end-line extraction added to the Phase-1 parser/schema (a small engine change) to return a single function body.
- **Output-cap:** cap oversized non-file tool-results.

## Self-review (this plan)
- **Contracts:** consumes only Phase-1 `query.*`/`render_keymd`/`files` table via the façade; adds proxy-only neutral types. ✅
- **Testability:** the entire gate mechanism (3a.5–3a.7) is tested with a scripted mock upstream + the real fixture engine — no network, no API spend. Server (3a.8) uses `httpx.ASGITransport`, dep-gated via `importorskip`. ✅
- **Fidelity:** line-complete TDD for adapter/gate/tools/orchestrator (the hard, novel core); the server shell's Step-3 is prose (thin Starlette wiring) — acceptable, smoke-tested. Streaming/OpenAI/cache-invariance explicitly deferred to 3b and flagged. ✅
- **Honesty:** 3a proves the gate logic and is runnable against a mock; **real Claude Code integration needs 3b streaming** — do not claim live-host readiness until then.
