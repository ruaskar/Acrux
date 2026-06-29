"""responses.py — OpenAI Responses API (/v1/responses) wire adapter.

Codex's default `wire_api=responses` uses a DIFFERENT shape than Chat Completions:
flat tool defs (`{type:"function", name, description, parameters}`), a top-level
`instructions` system prompt, an `input` item list, and function_call /
function_call_output items correlated by `call_id`. The orchestrator is unchanged
(this conforms to the WireAdapter protocol).
"""
from __future__ import annotations

import json

from keymd.proxy import tools
from keymd.proxy.adapters.base import ToolCall, ToolResultRef

_MARKER = "[keymd]"


class ResponsesAdapter:
    def inject(self, body: dict) -> dict:
        # input may be a string or a list; normalize to a list so we can append
        # function_call / function_call_output items during the gate loop.
        inp = body.get("input")
        if isinstance(inp, str):
            body["input"] = [{"role": "user", "content": inp}]
        elif inp is None:
            body["input"] = []
        # flat virtual tool defs (NOT nested under "function")
        defs = [{"type": "function", "name": d["name"],
                 "description": d["description"], "parameters": d["schema"]}
                for d in tools.VIRTUAL_TOOL_DEFS]
        existing = body.get("tools") or []
        have = {t.get("name") for t in existing if isinstance(t, dict)}
        body["tools"] = existing + [d for d in defs if d["name"] not in have]
        # steering directive → top-level `instructions` (idempotent)
        instr = body.get("instructions")
        if not isinstance(instr, str):
            body["instructions"] = tools.SYSTEM_DIRECTIVE.strip()
        elif _MARKER not in instr:
            body["instructions"] = instr + tools.SYSTEM_DIRECTIVE
        return body

    def tool_uses(self, resp: dict) -> list[ToolCall]:
        out = []
        for it in resp.get("output") or []:
            if it.get("type") == "function_call":
                raw = it.get("arguments") or "{}"
                try:
                    args = json.loads(raw) if isinstance(raw, str) else (raw or {})
                except (json.JSONDecodeError, TypeError):
                    args = {}
                # call_id (not id) is what function_call_output must echo back.
                out.append(ToolCall(it.get("call_id", ""), it.get("name", ""), args))
        return out

    def messages(self, body: dict) -> list:
        return body.get("input", []) or []

    def append_assistant(self, body: dict, resp: dict) -> dict:
        # Keep `reasoning` items too, in their original order: reasoning models
        # (gpt-5-codex — Codex's default) emit a `reasoning` item (rs_…) immediately
        # before each `function_call`, and the API 400s if a function_call is replayed
        # as input without its adjacent reasoning item. all-or-forward means the whole
        # turn is resolved locally here, so keeping all reasoning+function_call items
        # preserves the reasoning→function_call→function_call_output chain.
        items = [it for it in (resp.get("output") or [])
                 if it.get("type") in ("reasoning", "function_call")]
        body.setdefault("input", []).extend(items)
        return body

    def append_tool_results(self, body: dict, results: list[tuple[str, str]]) -> dict:
        inp = body.setdefault("input", [])
        for call_id, text in results:
            inp.append({"type": "function_call_output", "call_id": call_id,
                        "output": text})
        return body

    def tool_call_names(self, body):
        out = {}
        for it in body.get("input", []) or []:
            if it.get("type") == "function_call":
                tid = it.get("call_id") or it.get("id", "")
                name = it.get("name", "")
                if tid in out and out[tid] != name:
                    out[tid] = ""   # collision: un-routable
                else:
                    out[tid] = name
        return out

    def iter_tool_results(self, body):
        refs = []
        for it in body.get("input", []) or []:
            if it.get("type") == "function_call_output":
                tid = it.get("call_id", "")
                text = it.get("output")
                text = text if isinstance(text, str) else ""
                def setter(new, _it=it):
                    _it["output"] = new
                refs.append(ToolResultRef(tid, text, setter))
        return refs

    def terminal(self, text: str, template: dict | None = None) -> dict:
        out = {"object": "response", "status": "completed",
               "output": [{"type": "message", "role": "assistant",
                           "content": [{"type": "output_text", "text": text}]}]}
        if template:
            for k in ("id", "model", "created", "usage"):
                if k in template:
                    out[k] = template[k]
        return out
