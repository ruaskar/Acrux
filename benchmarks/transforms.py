"""transforms.py — body->body variants for the replay engine. Each calls the
SHIPPED proxy transforms so the benchmark measures the real product, not a copy."""
from __future__ import annotations

import copy

from keymd.proxy.adapters.anthropic import AnthropicAdapter
from keymd.proxy import result_bound, cache_inject
from keymd.proxy.orchestrator import _bound_rules

_ADAPTER = AnthropicAdapter()


def t_raw(body: dict) -> dict:
    return copy.deepcopy(body)


def t_bound(body: dict) -> dict:
    b = copy.deepcopy(body)
    result_bound.bound_results(b, _ADAPTER, _bound_rules(), fresh_results=0)
    return b


def t_cache(body: dict) -> dict:
    b = copy.deepcopy(body)
    cache_inject.inject_cache(b, "anthropic")
    return b


def t_bound_cache(body: dict) -> dict:
    b = copy.deepcopy(body)
    result_bound.bound_results(b, _ADAPTER, _bound_rules(), fresh_results=0)
    cache_inject.inject_cache(b, "anthropic")
    return b
