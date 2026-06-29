from benchmarks.phase2 import views
import benchmarks.enforced_gate_eval as ege


def test_treatment_gates_a_large_file():
    # server.py is large + indexed → treatment view must contain the summary marker
    v = views.treatment_view(["src/keymd/proxy/server.py"])
    assert "⟪keymd-summary:" in v


def test_control_is_full_source():
    v = views.control_view(["src/keymd/proxy/engine.py"])
    assert "def is_indexed_large" in v              # real source text present
    assert "⟪keymd-summary:" not in v               # NOT gated


def test_escape_returns_real_source():
    text, toks = views.escape("src/keymd/proxy/gate.py")
    assert "def classify" in text and toks > 0


def test_views_reuse_shipped_surface():
    # guard: the treatment path must be the real enforced_gate_eval, not a fork
    assert views.build_treatment_context is ege.build_treatment_context
