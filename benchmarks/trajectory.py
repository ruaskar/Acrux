"""trajectory.py — a replay trajectory is an ordered list of Anthropic request
bodies; this module loads them and counts the input tokens a body would bill."""
from __future__ import annotations

import json


def load_trajectory(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _text_of_block(b: dict) -> str:
    if not isinstance(b, dict):
        return str(b)
    t = b.get("type")
    if t == "text":
        return b.get("text", "")
    if t == "tool_result":
        c = b.get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return "".join(_text_of_block(x) for x in c)
        return ""
    if t == "tool_use":
        return (b.get("name", "") + json.dumps(b.get("input", {}), sort_keys=True))
    # image / document / unknown → serialize structurally (counts its footprint)
    return json.dumps(b, sort_keys=True)


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_text_of_block(b) for b in content)
    return ""


def body_input_tokens(body: dict, count_fn) -> int:
    total = 0
    sys = body.get("system")
    if isinstance(sys, str):
        total += count_fn(sys)
    elif isinstance(sys, list):
        total += count_fn("".join(_text_of_block(b) for b in sys))
    for tool in body.get("tools", []) or []:
        total += count_fn(json.dumps(tool, sort_keys=True))
    for msg in body.get("messages", []) or []:
        total += count_fn(_content_text(msg.get("content")))
    return total
