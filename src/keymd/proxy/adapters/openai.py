"""openai.py — OpenAI Chat Completions wire adapter.

Same neutral ToolCall surface as the Anthropic adapter, so the orchestrator is
unchanged. Covers OpenAI-compatible hosts (Codex, Cline, Roo, Continue, Aider).
Non-streaming (Phase 3b core); SSE passthrough is handled at the server layer.
"""
from __future__ import annotations

import json

from keymd.proxy import tools
from keymd.proxy.adapters.base import ToolCall

_MARKER = "[keymd]"


class OpenAIAdapter:
    def inject(self, body: dict) -> dict:
        defs = [{"type": "function",
                 "function": {"name": d["name"], "description": d["description"],
                              "parameters": d["schema"]}}
                for d in tools.VIRTUAL_TOOL_DEFS]
        existing = body.get("tools") or []
        have = {t.get("function", {}).get("name") for t in existing
                if isinstance(t, dict)}
        body["tools"] = existing + [d for d in defs
                                    if d["function"]["name"] not in have]
        msgs = body.setdefault("messages", [])
        if msgs and msgs[0].get("role") == "system":
            content = msgs[0].get("content")
            if isinstance(content, str) and _MARKER not in content:
                msgs[0]["content"] = content + tools.SYSTEM_DIRECTIVE
        else:
            msgs.insert(0, {"role": "system",
                            "content": tools.SYSTEM_DIRECTIVE.strip()})
        return body

    def tool_uses(self, resp: dict) -> list[ToolCall]:
        choices = resp.get("choices") or []
        if not choices:
            return []
        msg = choices[0].get("message", {}) or {}
        out = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {}) or {}
            raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except (json.JSONDecodeError, TypeError):
                args = {}
            out.append(ToolCall(tc.get("id", ""), fn.get("name", ""), args))
        return out

    def messages(self, body: dict) -> list:
        return body.get("messages", []) or []

    def append_assistant(self, body: dict, resp: dict) -> dict:
        msg = (resp.get("choices") or [{}])[0].get("message", {})
        body.setdefault("messages", []).append(msg)
        return body

    def append_tool_results(self, body: dict, results: list[tuple[str, str]]) -> dict:
        msgs = body.setdefault("messages", [])
        for tid, txt in results:
            msgs.append({"role": "tool", "tool_call_id": tid, "content": txt})
        return body

    def terminal(self, text: str, template: dict | None = None) -> dict:
        out = {"choices": [{"index": 0, "finish_reason": "stop",
                            "message": {"role": "assistant", "content": text}}]}
        if template:
            for k in ("id", "model", "object", "created", "usage"):
                if k in template:
                    out[k] = template[k]
        return out
