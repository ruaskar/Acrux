"""anthropic.py — Anthropic Messages API wire adapter."""
from __future__ import annotations

from keymd.proxy import tools
from keymd.proxy.adapters.base import ToolCall

_MARKER = "[keymd]"  # presence in system text => directive already injected


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
            if _MARKER not in sysv:                       # idempotent
                body["system"] = sysv + tools.SYSTEM_DIRECTIVE
        elif isinstance(sysv, list):
            if not any(_MARKER in (b.get("text", "") if isinstance(b, dict) else "")
                       for b in sysv):
                body["system"] = sysv + [{"type": "text",
                                          "text": tools.SYSTEM_DIRECTIVE}]
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

    def terminal(self, text: str, template: dict | None = None) -> dict:
        out = {"role": "assistant", "stop_reason": "end_turn",
               "content": [{"type": "text", "text": text}]}
        if template:
            for k in ("id", "type", "model", "usage"):
                if k in template:
                    out[k] = template[k]
        return out
