"""anthropic.py — Anthropic Messages API wire adapter."""
from __future__ import annotations

from keymd.proxy import tools
from keymd.proxy.adapters.base import ToolCall, ToolResultRef

_MARKER = "[keymd]"  # presence in system text => directive already injected


def _flatten_text(blocks):
    if not isinstance(blocks, list):
        return ""
    return "".join(b.get("text", "") for b in blocks
                   if isinstance(b, dict) and b.get("type") == "text")


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

    def tool_call_names(self, body):
        out = {}
        for m in body.get("messages", []) or []:
            if m.get("role") != "assistant":
                continue
            for b in m.get("content", []) or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    tid = b.get("id", "")
                    name = b.get("name", "")
                    if tid in out and out[tid] != name:
                        out[tid] = ""   # collision: un-routable
                    else:
                        out[tid] = name
        return out

    def iter_tool_results(self, body):
        refs = []
        for m in body.get("messages", []) or []:
            if m.get("role") != "user":
                continue
            content = m.get("content")
            if not isinstance(content, list):
                continue
            for blk in content:
                if not (isinstance(blk, dict) and blk.get("type") == "tool_result"):
                    continue
                tid = blk.get("tool_use_id", "")
                raw = blk.get("content")
                # content may be a str or a list of {"type":"text","text":...} blocks
                text = raw if isinstance(raw, str) else _flatten_text(raw)
                def setter(new, _blk=blk, raw=raw):
                    if isinstance(raw, list):
                        # Find cache_control from the LAST text block that has one.
                        # Anthropic honors up to 4 breakpoints on any block; collapsing
                        # all text blocks into one must not silently drop a breakpoint
                        # that sat on a non-first text block.
                        text_blocks = [b for b in raw
                                       if isinstance(b, dict) and b.get("type") == "text"]
                        cc = None
                        for b in text_blocks:
                            if b.get("cache_control") is not None:
                                cc = b["cache_control"]
                        if text_blocks:
                            # Start from a copy of the FIRST text block so sibling keys
                            # (e.g. citations, future Anthropic text-block fields) are
                            # preserved; then override text and apply last-cc logic.
                            rebuilt_text = dict(text_blocks[0])
                            rebuilt_text["text"] = new
                            if cc is not None:
                                rebuilt_text["cache_control"] = cc
                            elif "cache_control" in rebuilt_text:
                                # First block had cc but last-non-None scan chose None
                                # (impossible if first block had cc, but be explicit).
                                del rebuilt_text["cache_control"]
                        else:
                            # No text blocks at all — prepend a bare text block.
                            rebuilt_text = {"type": "text", "text": new}
                        # Rebuilt content: single text block FIRST, then non-text blocks.
                        # Note: original [image, text] ordering is normalized to [text, image];
                        # Anthropic treats tool_result sub-blocks as an unordered payload so
                        # this reorder is semantically safe.
                        non_text = [b for b in raw
                                    if not (isinstance(b, dict) and b.get("type") == "text")]
                        _blk["content"] = [rebuilt_text] + non_text
                    else:
                        _blk["content"] = new
                refs.append(ToolResultRef(tid, text, setter))
        return refs

    def terminal(self, text: str, template: dict | None = None) -> dict:
        out = {"role": "assistant", "stop_reason": "end_turn",
               "content": [{"type": "text", "text": text}]}
        if template:
            for k in ("id", "type", "model", "usage"):
                if k in template:
                    out[k] = template[k]
        return out
