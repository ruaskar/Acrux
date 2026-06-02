"""Regenerate THIRD_PARTY_LICENSES.md from the installed keymd[all] dependency set.

The release binaries (PyApp) embed CPython + these wheels, so their license/permission
notices must travel with the binary (BSD/MIT/PSF/MPL requirement). Run in an env with
`keymd[all]` installed:  python scripts/gen_third_party_licenses.py
"""
from __future__ import annotations

import importlib.metadata as m
from pathlib import Path

# Runtime dependency closure of keymd[all] that PyApp installs into the binary.
PKGS = ["anyio", "certifi", "click", "colorama", "h11", "httpcore", "httpx", "idna",
        "lxml", "pypdf", "python-docx", "sniffio", "starlette", "tree-sitter",
        "tree-sitter-c", "tree-sitter-cpp", "tree-sitter-java",
        "tree-sitter-javascript", "tree-sitter-typescript", "typing-extensions", "uvicorn"]


def license_text(dist, md) -> str | None:
    cands = list(md.get_all("License-File") or [])
    try:
        for f in (dist.files or []):
            b = f.name.upper()
            if b.startswith(("LICEN", "COPYING", "NOTICE", "AUTHORS")) and not b.endswith(".PY"):
                cands.append(str(f))
    except Exception:
        pass
    for c in cands:
        for rel in (c, f"licenses/{c}", Path(c).name, f"licenses/{Path(c).name}"):
            try:
                t = dist.read_text(rel)
                if t and len(t.strip()) > 30:
                    return t.strip()
            except Exception:
                pass
        try:
            t = Path(dist.locate_file(c)).read_text(encoding="utf-8", errors="replace")
            if t and len(t.strip()) > 30:
                return t.strip()
        except Exception:
            pass
    return None


def lic_id(md) -> str:
    cls = [c.split("::")[-1].strip() for c in md.get_all("Classifier") or [] if "License" in c]
    return "; ".join(cls) or md.get("License-Expression") or (md.get("License") or "?").splitlines()[0][:60]


def main() -> None:
    out = ["# Third-party licenses\n",
           "The keymd release **binaries** (built with [PyApp](https://ofek.dev/pyapp)) embed an "
           "unmodified **CPython** runtime (from [python-build-standalone]"
           "(https://github.com/astral-sh/python-build-standalone)) and install keymd plus the "
           "dependencies below from standard wheels. Their copyright and permission notices are "
           "reproduced here as required for binary redistribution. keymd itself is Apache-2.0 "
           "(see `LICENSE`).\n",
           "> Regenerate: `python scripts/gen_third_party_licenses.py` (in an env with "
           "`keymd[all]` installed).\n",
           "## Python (CPython)\n\nEmbedded interpreter — **Python Software Foundation License "
           "(PSF-2.0)**. Full text: https://docs.python.org/3/license.html\n"]
    for p in PKGS:
        try:
            md, dist, ver = m.metadata(p), m.distribution(p), m.version(p)
        except Exception:
            continue
        url = md.get("Home-page") or ""
        if not url:
            for k in md.get_all("Project-URL") or []:
                if "://" in k:
                    url = k.split(",")[-1].strip()
                    break
        out.append(f"\n---\n\n## {p} ({ver}) — {lic_id(md)}\n{url}\n")
        txt = license_text(dist, md)
        out.append("\n```\n" + txt[:6000] + ("\n…(truncated)…" if len(txt) > 6000 else "") + "\n```\n"
                   if txt else "\n_(License text in the package's wheel; type above.)_\n")
    out.append("\n---\n\n## libxml2 / libxslt (statically bundled in lxml wheels) — MIT\n"
               "© Daniel Veillard. https://gitlab.gnome.org/GNOME/libxml2/-/blob/master/Copyright\n")
    Path("THIRD_PARTY_LICENSES.md").write_text("\n".join(out), encoding="utf-8")
    print(f"wrote THIRD_PARTY_LICENSES.md ({len(chr(10).join(out))} bytes)")


if __name__ == "__main__":
    main()
