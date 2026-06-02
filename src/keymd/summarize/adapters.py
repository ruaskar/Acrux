"""adapters.py — per-protocol request/response shaping for `keymd summarize`.

Distinct from proxy/adapters (those drive the gate's tool-use LOOP via
inject/tool_uses/append_tool_results/terminal); summarize needs only a one-shot
prompt -> text call. Each wire supplies: the endpoint URL, the request body, the
auth header, and response-text extraction. Adding a protocol = add a class + a
WIRES entry. The headers each wire emits are within the proxy _post forward
allowlist (authorization / x-api-key / anthropic-version / content-type), so
summarize reuses that IPv4-pinned transport unchanged."""
from __future__ import annotations

from typing import Protocol


class SummarizeWire(Protocol):
    name: str
    def endpoint(self, base: str) -> str: ...
    def build_request(self, system: str, file_text: str, model: str, max_tokens: int) -> dict: ...
    def auth_headers(self, key: str) -> dict: ...
    def extract_text(self, resp: dict) -> str: ...


class OpenAIWire:
    name = "openai"

    def endpoint(self, base: str) -> str:
        # Append ONLY the endpoint path — the version segment lives in the BASE,
        # exactly as the OpenAI SDK and LiteLLM require ("api_base must have the
        # /v1 postfix"). This is what makes every OpenAI-compatible provider work
        # from one wire: the user points the base at their provider's documented
        # URL (which already carries the version) and we never double it:
        #   OpenAI   https://api.openai.com/v1
        #   DeepSeek https://api.deepseek.com/v1
        #   Gemini   https://generativelanguage.googleapis.com/v1beta/openai
        #   Qwen     https://dashscope-intl.aliyuncs.com/compatible-mode/v1
        #   Ollama   http://localhost:11434/v1
        return f"{base.rstrip('/')}/chat/completions"

    def build_request(self, system: str, file_text: str, model: str, max_tokens: int) -> dict:
        return {"model": model, "max_tokens": max_tokens, "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": file_text}]}

    def auth_headers(self, key: str) -> dict:
        return {"Authorization": f"Bearer {key}", "content-type": "application/json"}

    def extract_text(self, resp: dict) -> str:
        return (resp.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""


class AnthropicWire:
    name = "anthropic"

    def endpoint(self, base: str) -> str:
        return f"{base.rstrip('/')}/v1/messages"

    def build_request(self, system: str, file_text: str, model: str, max_tokens: int) -> dict:
        return {"model": model, "max_tokens": max_tokens, "system": system,
                "messages": [{"role": "user", "content": file_text}]}

    def auth_headers(self, key: str) -> dict:
        return {"x-api-key": key, "anthropic-version": "2023-06-01",
                "content-type": "application/json"}

    def extract_text(self, resp: dict) -> str:
        # `b.get("text") or ""` (not get(...,"")): a text block can carry an explicit
        # null value, and "".join over a None would raise — coerce to "".
        return "".join((b.get("text") or "") for b in (resp.get("content") or [])
                       if isinstance(b, dict) and b.get("type") == "text")


WIRES: dict[str, SummarizeWire] = {"openai": OpenAIWire(), "anthropic": AnthropicWire()}
