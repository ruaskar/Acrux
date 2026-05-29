"""End-to-end: build → generate every missing sidecar → query reflects truth."""
import os
from pathlib import Path

from keymd.engine import index, query, refresh
import keymd.engine.parsers.python  # noqa: F401


def test_full_flow(env_proj):
    pkg = Path(env_proj) / "pkg"
    created = [pkg / "parser.key.md", pkg / "pipeline.key.md"]
    try:
        index.build(verbose=False)
        # generate sidecars for both source files
        assert refresh.refresh_one(str(pkg / "parser.py")) is True
        assert refresh.refresh_one(str(pkg / "pipeline.py")) is True
        # parser.key.md must name pipeline as an impacted caller
        text = (pkg / "parser.key.md").read_text(encoding="utf-8")
        assert "called_by:" in text and "pipeline.py" in text
        impact = query.impact(str(pkg / "parser.py"))
        assert impact["unique_files"] >= 1
    finally:
        for k in created:
            k.unlink(missing_ok=True)
