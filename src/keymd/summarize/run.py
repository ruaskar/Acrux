"""run.py — `keymd summarize` orchestration.

Scan each GATED file once via the user's OWN model endpoint, cache a sha-keyed
prose summary. keymd NEVER uses its own key; the endpoint + key come from the
user's env (fail loudly if the key is absent — never a silent default-endpoint
call). Re-summarizes only files whose sha changed (incremental). Every summary is
secret-redacted before caching (the model may echo a secret from the file it read)."""
from __future__ import annotations

import os
import sys

from keymd.engine import config, db, index, summary_store
from keymd.engine.redact import redact_secrets
from keymd.summarize.adapters import WIRES

_SYSTEM = ("You are summarizing one source file for a code index. In 1-2 sentences, "
           "state what the file does and its role. No code, no preamble, no secrets.")
_MAX_TOKENS = 512

# per-wire env: (base_url_env, base_default, key_env)
# Per-wire env: (base_url_env, base_default, key_env). The OpenAI default carries
# the /v1 version segment because endpoint() appends only /chat/completions — the
# ecosystem convention (OpenAI SDK + LiteLLM). A user pointing at another provider
# supplies that provider's full documented base (DeepSeek/Gemini/Qwen/Ollama all
# include the version), e.g. KEYMD_OPENAI_BASE=http://localhost:11434/v1.
_ENV = {
    "openai": ("KEYMD_OPENAI_BASE", "https://api.openai.com/v1", "OPENAI_API_KEY"),
    "anthropic": ("KEYMD_ANTHROPIC_BASE", "https://api.anthropic.com", "ANTHROPIC_API_KEY"),
}


def _call(wire, base: str, key: str, headers: dict, body: dict) -> dict:
    """The one network seam (monkeypatched in tests). Reuses the proxy's
    IPv4-pinned _post so summarize and the gate share transport + error handling."""
    import anyio

    from keymd.proxy.server import _post
    return anyio.run(_post, wire.endpoint(base), body, headers)


def summarize(path: str | None, wire_name: str, model: str,
              limit: int, threshold: int) -> dict:
    if wire_name not in WIRES:
        raise SystemExit(f"error: unknown --wire {wire_name!r} (choices: {', '.join(WIRES)})")
    wire = WIRES[wire_name]
    base_env, base_default, key_env = _ENV[wire_name]
    key = os.environ.get(key_env)
    if not key:
        hint = ("e.g. http://localhost:11434/v1 (Ollama), "
                "https://api.deepseek.com/v1 (DeepSeek), "
                "https://dashscope-intl.aliyuncs.com/compatible-mode/v1 (Qwen), "
                "https://generativelanguage.googleapis.com/v1beta/openai (Gemini)"
                if wire_name == "openai" else "e.g. https://api.deepseek.com/anthropic")
        raise SystemExit(
            f"error: {key_env} is not set. `keymd summarize` uses YOUR OWN model "
            f"endpoint + key — set {key_env}, and {base_env} to your provider's base URL "
            f"(include the version segment). {hint}. keymd never uses its own key.")
    base = os.environ.get(base_env, base_default)

    # Resolve target repo + ensure an index (mirror the graph/build path).
    if path:
        from pathlib import Path
        p = Path(os.path.expanduser(path))
        if not p.is_dir():
            raise SystemExit(f"error: {path} is not a directory")
        root = os.path.realpath(p)
        os.environ["KEYMD_PROJECT_ROOT"] = root
        os.environ.setdefault("KEYMD_INDEX_PATH", os.path.join(root, ".keymd", "index.db"))
        config.project_pkg_prefixes.cache_clear()
        config._git_toplevel.cache_clear()
    if not config.index_path().exists():
        index.build(verbose=False)

    headers = wire.auth_headers(key)
    con = db.connect(config.index_path())
    summary_store.ensure_table(con)
    rows = con.execute(
        "SELECT path, sha256 FROM files WHERE line_count > ? ORDER BY path",
        (threshold,)).fetchall()

    done = skipped = failed = 0
    for fpath, sha in rows:
        if done >= limit:
            break
        if summary_store.get(con, fpath, sha) is not None:
            skipped += 1
            continue
        try:
            with open(fpath, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            body = wire.build_request(_SYSTEM, text, model, _MAX_TOKENS)
            resp = _call(wire, base, key, headers, body)
            # opaque=True (the STRONGER scrub, same as the docstring path): a model
            # can paraphrase/echo a secret it read from the file, so this surface needs
            # the bare-high-entropy-blob rule too, not just keyword/known-vendor shapes.
            # Over-redacting a legitimate long token in prose is the correct bias here.
            out = redact_secrets(wire.extract_text(resp).strip(), opaque=True)
            if out:
                summary_store.put(con, fpath, sha, out, model)
                done += 1
            else:
                failed += 1
        except Exception as e:                      # one bad file never aborts the run
            print(f"  ! {config.canonical(fpath)}: {e}", file=sys.stderr)
            failed += 1
    con.close()
    return {"summarized": done, "skipped": skipped, "failed": failed, "model": model}
