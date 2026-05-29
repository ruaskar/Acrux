"""keymd CLI — build the index, refresh sidecars, and query structure."""
from __future__ import annotations

import argparse
import json
import sys

import keymd.engine.parsers.python  # noqa: F401  (registers the .py parser)
import keymd.engine.parsers.treesitter  # noqa: F401  (registers JS/TS if `lang` extra installed)
from keymd.engine import index, query, refresh, sync_one


def main(argv: list[str] | None = None) -> int:
    # The .key.md / search output uses non-ASCII glyphs; force UTF-8 on stdout
    # so `keymd search` / `build` don't crash on a non-UTF-8 Windows console.
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    p = argparse.ArgumentParser(prog="keymd")
    sp = p.add_subparsers(dest="cmd", required=True)

    b = sp.add_parser("build"); b.add_argument("--quiet", action="store_true")
    sp.add_parser("stats")
    r = sp.add_parser("refresh"); r.add_argument("path")
    sy = sp.add_parser("sync"); sy.add_argument("path")
    c = sp.add_parser("callers"); c.add_argument("symbol")
    ce = sp.add_parser("callees"); ce.add_argument("path")
    sym = sp.add_parser("symbols"); sym.add_argument("path")
    im = sp.add_parser("impact"); im.add_argument("path")
    se = sp.add_parser("search"); se.add_argument("text")
    se.add_argument("--limit", type=int, default=15)
    mk = sp.add_parser("missing-keymds"); mk.add_argument("--top", type=int, default=30)
    sv = sp.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8787)
    sv.add_argument("--threshold", type=int, default=400)
    gd = sp.add_parser("guard")
    gd.add_argument("action", choices=["check-push", "check-dup", "install"])
    gd.add_argument("rest", nargs="*")
    wt = sp.add_parser("watch")
    wt.add_argument("--delay", type=float, default=0.6)

    # --- regular-user onboarding ---
    def _serve_flags(parser):
        parser.add_argument("--host")
        parser.add_argument("--port", type=int)
        parser.add_argument("--threshold", type=int)
        parser.add_argument("--wire", choices=["openai", "anthropic"])
        parser.add_argument("--upstream")
        parser.add_argument("--rebuild", action="store_true")
    up = sp.add_parser("up"); _serve_flags(up)
    rn = sp.add_parser("run"); _serve_flags(rn)
    rn.add_argument("agent", nargs=argparse.REMAINDER)  # everything after `--`
    ini = sp.add_parser("init"); ini.add_argument("path", nargs="?")
    ini.add_argument("--force", action="store_true")
    ini.add_argument("--write-agents", action="store_true")
    doc = sp.add_parser("doctor")
    doc.add_argument("--wire", action="store_true")
    doc.add_argument("--net", action="store_true")
    idep = sp.add_parser("ide"); idep.add_argument("tool", nargs="?")

    a = p.parse_args(argv)

    if a.cmd == "build":
        print(json.dumps(index.build(verbose=not a.quiet)))
    elif a.cmd == "stats":
        print(json.dumps(query.stats(), indent=2))
    elif a.cmd == "refresh":
        print(f"{a.path}: {'updated' if refresh.refresh_one(a.path) else 'no change'}")
    elif a.cmd == "sync":
        sync_one.sync_one(a.path); print(f"{a.path}: synced")
    elif a.cmd == "callers":
        res = query.callers(a.symbol)
        print(f"# callers of {res['symbol']} — exact ({len(res['exact'])})")
        for path, name in res["exact"]:
            print(f"  {path:60s} {name}")
        if res["leaf"]:
            print(f"# leaf-name matches ({len(res['leaf'])}, may include overloads)")
            for path, name in res["leaf"]:
                print(f"  {path:60s} {name}")
    elif a.cmd == "callees":
        rows = query.callees(a.path)
        print(f"# resolved calls from {a.path} ({len(rows)})")
        for to_name, to_path in rows:
            print(f"  {to_name:40s} -> {to_path}")
    elif a.cmd == "symbols":
        for name, kind, line in query.symbols(a.path):
            print(f"  L{line:5d}  {kind:10s}  {name}")
    elif a.cmd == "impact":
        res = query.impact(a.path)
        print(f"# impact for {res['path']}")
        for sym, callers in res["per_symbol"].items():
            print(f"  {sym}")
            for c in callers[:8]:
                print(f"    ← {c}")
        print(f"# unique files depending: {res['unique_files']}")
    elif a.cmd == "search":
        for path, snip in query.search(a.text, a.limit):
            print(f"  {path}\n    {snip}")
    elif a.cmd == "missing-keymds":
        for lc, path in query.missing_keymds(a.top):
            print(f"  {lc:5d}L  {path}")
    elif a.cmd == "serve":
        from keymd.proxy import server  # lazy: proxy extra deps only needed here
        print(f"keymd proxy on http://{a.host}:{a.port} "
              f"(threshold={a.threshold} loc)")
        server.serve(host=a.host, port=a.port, threshold=a.threshold)
    elif a.cmd == "guard":
        from keymd.guardrails import cli as gcli
        return gcli.run(a.action, a.rest)
    elif a.cmd == "watch":
        from keymd.engine import config
        from keymd.watcher import run
        try:
            run.serve(root=str(config.project_root()), delay=a.delay)
        except ImportError:  # watchdog imported lazily inside build_observer
            print("keymd watch needs watchdog: pip install 'keymd[watch]'")
            return 1
    elif a.cmd == "up":
        from keymd import onboarding
        return onboarding.up(rebuild=a.rebuild, flag_host=a.host, flag_port=a.port,
                             flag_threshold=a.threshold, flag_wire=a.wire,
                             flag_upstream=a.upstream)
    elif a.cmd == "run":
        from keymd import onboarding
        cmd = a.agent[1:] if (a.agent and a.agent[0] == "--") else a.agent
        return onboarding.run_agent(cmd, rebuild=a.rebuild, flag_host=a.host,
                                    flag_port=a.port, flag_threshold=a.threshold,
                                    flag_wire=a.wire, flag_upstream=a.upstream)
    elif a.cmd == "init":
        from keymd import onboarding
        return onboarding.init(path=a.path, force=a.force,
                               write_agents=a.write_agents)
    elif a.cmd == "doctor":
        from keymd import onboarding
        return onboarding.doctor(wire=a.wire, net=a.net)
    elif a.cmd == "ide":
        from keymd import onboarding
        return onboarding.ide(tool=a.tool)
    return 0


if __name__ == "__main__":
    sys.exit(main())
