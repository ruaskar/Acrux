<!-- keymd steering snippet — append to your AGENTS.md / CLAUDE.md.
     Works as a soft nudge for hosts that can't point at the proxy; the proxy
     enforces it for hosts that can. -->

## Reading code efficiently (keymd)

Before reading a LARGE file in full, call `keymd_read(path)` for its compact
summary (API signatures, dependencies, callers). Use `keymd_impact(path)`,
`keymd_callers(symbol)`, `keymd_callees(path)`, and `keymd_search(text)` to
understand structure instead of grepping. Only call `keymd_read_full(path)`
when the summary is genuinely insufficient.

These tools answer from a local, always-fresh call-graph index — one indexed
lookup instead of many file reads or greps.
