"""orchestrator.py — the gate inner loop.

complete() injects virtual tools, then repeatedly calls the (injected) upstream.
A turn is resolved LOCALLY only if every tool_use in it is virtual-or-gated
(all-or-forward); otherwise the whole turn is returned to the host. Bounded by
MAX_INNER_TURNS, on exhaustion of which a synthetic terminal turn is returned
(never an unanswerable tool_use turn the host can't execute).
"""
from __future__ import annotations

from keymd.proxy import bounders, cache_inject, engine as _eng, gate, result_bound, tools
from keymd.proxy.adapters.base import WireAdapter

MAX_INNER_TURNS = 24


def _bound_rules() -> dict:
    cmap = _eng.centrality_map()
    return {
        r"grep|rg|ripgrep|search_files": bounders.bound_grep,
        r"ls|find|glob|list_dir|list_files": (lambda t: bounders.bound_listing(t, cmap)),
    }


async def complete(body: dict, adapter: WireAdapter, upstream, *,
                   threshold: int = 50, bound: bool = False,
                   cache: bool = False, wire: str = "anthropic") -> dict:
    # No index → keymd can't summarize anything: every read would pass through and
    # the virtual tools would all answer "(index not built)". Skip injection AND the
    # gate loop entirely so keymd is a true transparent pass-through — it adds zero
    # tokens (no tool defs, no directive) instead of advertising tools that don't work.
    from keymd.proxy import engine
    if not engine._index_ready():
        return await upstream(body)
    body = adapter.inject(body)
    if bound:
        result_bound.bound_results(body, adapter, _bound_rules(), fresh_results=0)
    if cache:
        cache_inject.inject_cache(body, wire)   # after bounding → frozen prefix = cache anchor
    last = None
    for _ in range(MAX_INNER_TURNS):
        resp = await upstream(body)
        last = resp
        calls = adapter.tool_uses(resp)
        if not calls:
            return resp  # final assistant answer — hand to host
        summarized = gate.summarized_paths(adapter.messages(body))
        decisions = [gate.classify(c, summarized=summarized, threshold=threshold)
                     for c in calls]
        if any(d.kind == "host" for d in decisions):
            return resp  # all-or-forward: host executes the whole turn
        # every call is virtual or gated → resolve locally and loop.
        body = adapter.append_assistant(body, resp)
        results: list[tuple[str, str]] = []
        batch_summary: dict[str, str] = {}  # dedupe same-file gated reads in one turn
        for d in decisions:
            if d.kind == "virtual":
                results.append((d.call.id, tools.answer(d.call)))
            else:  # gated read — one tool_result per id, summary computed once per path
                if d.path not in batch_summary:
                    batch_summary[d.path] = gate.summary_result(d.path)
                results.append((d.call.id, batch_summary[d.path]))
        body = adapter.append_tool_results(body, results)
    # Budget exhausted: return a synthetic terminal turn, NOT the last (unanswerable)
    # tool_use turn, so the host is never handed keymd_* tool_uses it can't execute.
    return adapter.terminal("[keymd] inner-tool budget exhausted; returning control.",
                            template=last)
