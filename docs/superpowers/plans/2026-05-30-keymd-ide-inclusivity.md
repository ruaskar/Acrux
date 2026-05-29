# keymd IDE Inclusivity (Round 2) — Implementation Plan

> REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** Make IDE/extension agents (Claude Code, Codex, Cline, Continue, Cursor) and
self-hosted/OpenClaw/Hermes users first-class — not just terminal `keymd run` users.

**Architecture:** keymd already serves IDEs via **attach mode** (`keymd up` long-running +
the agent points its own base-URL at the proxy). This round closes the concrete gaps:
(1) a `/v1/messages/count_tokens` passthrough so Claude Code doesn't 404; (2) a third wire
adapter for the **OpenAI Responses API** (Codex's default `wire_api=responses`); (3) a
verified per-tool wiring guide + a `keymd ide` helper that prints exact settings.

## Verified Responses-API wire shapes (probed 2026-05-30 — do not code from memory)

- **Tool def (flat):** `{"type":"function","name":...,"description":...,"parameters":{...}}`
  (NOT nested under `"function"` like Chat Completions).
- **System prompt:** top-level `instructions` (string).
- **Request `input`:** string OR array of items. Message item: `{"role":"user","content":"…"}`
  (shorthand accepted) or `{"type":"message","role",...}`.
- **Model tool call (in response `output[]`):**
  `{"type":"function_call","id":"fc_…","call_id":"call_…","name":…,"arguments":"<json str>"}`.
- **Reasoning item (reasoning models, e.g. gpt-5-codex):** a `{"type":"reasoning","id":"rs_…",…}`
  item appears in `output[]` IMMEDIATELY BEFORE each `function_call`. When replaying the
  function_call inline as input (no `previous_response_id`), the reasoning item MUST be kept
  adjacent or the API 400s ("function_call … provided without its required 'reasoning' item").
  `append_assistant` therefore re-appends `reasoning` items alongside `function_call` items.
- **Tool result (appended to `input`):**
  `{"type":"function_call_output","call_id":"call_…","output":"<str>"}` — correlated by `call_id`.
- **Text answer (in `output[]`):**
  `{"type":"message","role":"assistant","content":[{"type":"output_text","text":…}]}`.
- **Non-stream response:** `{"id","object":"response","status":"completed","output":[…],"model",…}`.
- **Streaming events (typed SSE):** `response.created` → `response.output_item.added` →
  `response.content_part.added` → `response.output_text.delta`(×N) → `response.output_text.done`
  → `response.content_part.done` → `response.output_item.done` → `response.completed`. Tool
  calls stream via `response.function_call_arguments.delta/done`. Each event carries an
  incrementing `sequence_number`.
- **Path:** base ends `/v1`, `wire_api="responses"` → `POST /v1/responses`.

Sources: OpenAI function-calling guide, Responses API reference, migrate-to-responses,
responses-streaming reference.

---

### Task R1: `/v1/messages/count_tokens` passthrough

**Files:** `src/keymd/proxy/server.py`, `tests/test_proxy_count_tokens.py`

- [ ] Test: a POST to `/v1/messages/count_tokens` is forwarded to
  `{anthropic_base}/v1/messages/count_tokens` (monkeypatch `_post`, assert URL) and the
  upstream JSON is returned verbatim (no gating).
- [ ] Impl: add a `count_tokens_route` that calls a new
  `forward_count_tokens(body, headers, base=None)` → `_post(f"{_anthropic_base(base)}/v1/messages/count_tokens", …)`, return `JSONResponse`. Register `Route("/v1/messages/count_tokens", …, ["POST"])` BEFORE `/v1/messages` (Starlette matches first; distinct path so order is safe either way).
- [ ] Commit.

### Task R2: loop-guard learns the Responses `function_call_output` shape

**Files:** `src/keymd/proxy/gate.py`, `tests/test_proxy_gate.py`

- [ ] Test: `summarized_paths([{ "type":"function_call_output","call_id":"c","output":"⟪keymd-summary:/abs/x.py⟫ …"}])` returns `{"/abs/x.py"}`.
- [ ] Impl: in `summarized_paths`, after the existing str/list handling, also scan
  `m.get("output")` when it's a str (the Responses tool-result field).
- [ ] Commit.

### Task R3: `ResponsesAdapter` (WireAdapter protocol)

**Files:** `src/keymd/proxy/adapters/responses.py`, `tests/test_proxy_adapter_responses.py`

Implement the 6 protocol methods:
- `inject(body)`: ensure `body["input"]` is a list (wrap a string as `[{"role":"user","content":<str>}]`); add flat virtual tool defs to `body["tools"]` (dedupe by `name`); append `tools.SYSTEM_DIRECTIVE` to `body["instructions"]` (create it if absent), guarded by the `[keymd]` marker (idempotent).
- `tool_uses(resp)`: `[ToolCall(it["call_id"], it["name"], json.loads(it.get("arguments") or "{}")) for it in resp.get("output",[]) if it.get("type")=="function_call"]` (tolerant arg parse).
- `messages(body)`: `body.get("input", [])` (list).
- `append_assistant(body, resp)`: extend `body["input"]` with the `function_call` items from `resp["output"]`.
- `append_tool_results(body, results)`: for each `(call_id, text)` append `{"type":"function_call_output","call_id":call_id,"output":text}` to `body["input"]`.
- `terminal(text, template)`: `{"object":"response","status":"completed","output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":text}]}]}` + copy `id/model/created/usage` from template.
- [ ] Tests: inject (flat tools + instructions marker idempotent + string-input wrap); tool_uses (extracts call_id/name/args); append_assistant + append_tool_results round-trip; terminal shape.
- [ ] Commit.

### Task R4: server `/v1/responses` route + `forward_responses` + `_responses_sse`

**Files:** `src/keymd/proxy/server.py`, `tests/test_proxy_responses_route.py`, `tests/test_proxy_responses_sse.py`

- [ ] `forward_responses(body, headers, base=None)` → `_post(f"{_openai_base(base)}/v1/responses", …)`.
- [ ] `responses_route`: like `openai_route` but with `ResponsesAdapter()`; non-stream → `JSONResponse`; `stream:true` → `StreamingResponse(_responses_sse(result), media_type="text/event-stream")`. Register `Route("/v1/responses", …, ["POST"])`. Thread `openai_base` override (reuse the same `openai_base` build_app param).
- [ ] `_responses_sse(resp)`: synthesize the typed event sequence from the buffered final response. For a `message` output item: created → output_item.added → content_part.added → output_text.delta(full text) → output_text.done → content_part.done → output_item.done → completed. For a `function_call` output item (all-or-forward case): output_item.added(function_call) → function_call_arguments.delta(full args) → function_call_arguments.done → output_item.done → completed. Incrementing `sequence_number`; each event line is `event: <type>\n` + `data: <json>\n\n`. Final response object embedded in `response.completed`.
- [ ] Tests: scripted 2-turn upstream (turn1 returns a `function_call` Read → gate summarizes → turn2 returns a text message); assert gate fired (`state.n==2`), non-stream returns the text, and `stream:true` yields a valid event sequence ending `response.completed` whose reassembled text matches. (Mirror `tests/test_proxy_streaming.py` structure.)
- [ ] Commit.

### Task R5: wiring docs + `keymd ide` helper

**Files:** `src/keymd/onboarding.py` (add `ide`), `src/keymd/cli.py` (subcommand), `tests/test_onboarding.py`, `README.md`

- [ ] `ide(tool: str|None)`: print the exact wiring for a named tool, or all tools if None. Tools dict (verified): `claude-code` (`~/.claude/settings.json` env `ANTHROPIC_BASE_URL`), `codex` (`~/.codex/config.toml` named provider, `wire_api="chat"` OR keymd now also supports `responses`), `cline` (OpenAI-Compatible, Base URL `…/v1`), `continue` (`config.yaml apiBase`), `cursor`, `openclaw` (`baseUrl`), `hermes` (`provider:custom, base_url`). Each entry: the proxy URL (`http://HOST:PORT` for Anthropic wire, `…/v1` for OpenAI wire) + a one-line note. Model-agnostic note: keymd cares about the WIRE (OpenAI/Anthropic), not the model — Hermes/Qwen/Llama via vLLM/Ollama all work.
- [ ] CLI: `ide` subcommand with optional positional `tool`.
- [ ] Test: `ide("claude-code")` prints `ANTHROPIC_BASE_URL`; `ide(None)` prints ≥5 tools incl `openclaw` and `hermes`.
- [ ] README: add "Use keymd from your IDE / framework (attach mode)" section with the table + the `keymd up` background note + `keymd ide` pointer + the Codex `wire_api` note (chat or responses both work now).
- [ ] Commit.

### Task R6: full suite + dogfood + adversarial review + PR

- [ ] `python -m pytest -q` green.
- [ ] Dogfood: `python -m keymd ide`; a scripted `/v1/responses` round-trip through `build_app` proving the gate fires on the Responses wire.
- [ ] Adversarial review workflow over the new adapter + SSE + docs; fix findings.
- [ ] Branch `feature/ide-inclusivity`, push, PR.
