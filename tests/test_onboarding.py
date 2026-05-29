import pytest

from keymd import onboarding as ob


# --- Task 3: resolve / child_env / wiring_hint / up ------------------------

def test_resolve_precedence_flag_over_env_over_toml(tmp_path, monkeypatch):
    (tmp_path / "keymd.toml").write_text(
        '[keymd]\nthreshold = 50\n[keymd.serve]\nport = 9000\n', encoding="utf-8")
    monkeypatch.setenv("KEYMD_PORT", "7000")
    r = ob.resolve(root=tmp_path, flag_port=1234, flag_threshold=None)
    assert r.port == 1234            # flag wins
    assert r.threshold == 50         # falls through to toml
    r2 = ob.resolve(root=tmp_path, flag_port=None, flag_threshold=None)
    assert r2.port == 7000           # env beats toml


def test_inject_env_sets_all_base_urls():
    env = ob.child_env({"PATH": "x"}, host="127.0.0.1", port=8787)
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8787"
    assert env["OPENAI_BASE_URL"] == "http://127.0.0.1:8787/v1"
    assert env["OPENAI_API_BASE"] == "http://127.0.0.1:8787/v1"
    assert env["PATH"] == "x"        # parent env preserved


def test_wiring_lines_mentions_both():
    text = ob.wiring_hint("127.0.0.1", 8787)
    assert "ANTHROPIC_BASE_URL=http://127.0.0.1:8787" in text
    assert "OPENAI_BASE_URL=http://127.0.0.1:8787/v1" in text


def test_up_builds_when_missing_and_serves(tmp_path, monkeypatch, capsys):
    calls = {"ensure": 0, "serve": None}
    monkeypatch.setattr(ob, "_ensure_index", lambda rebuild: calls.__setitem__("ensure", 1))
    from keymd.proxy import server
    monkeypatch.setattr(server, "serve", lambda **kw: calls.__setitem__("serve", kw))
    rc = ob.up(root=tmp_path, flag_port=9001)
    assert rc == 0 and calls["ensure"] == 1
    assert calls["serve"]["port"] == 9001
    assert "9001" in capsys.readouterr().out


# --- Task 4: run -----------------------------------------------------------

class _FakeServer:
    should_exit = False


def test_run_invokes_child_with_injected_env(tmp_path, monkeypatch):
    monkeypatch.setattr(ob, "_ensure_index", lambda rebuild: None)
    monkeypatch.setattr(ob, "_start_proxy", lambda r: _FakeServer())
    seen = {}

    def fake_run(cmd, env=None):
        seen["cmd"] = cmd
        seen["env"] = env

        class R:
            returncode = 0
        return R()
    monkeypatch.setattr(ob.subprocess, "run", fake_run)
    rc = ob.run_agent(["echo", "hi"], root=tmp_path, flag_port=8799)
    assert rc == 0
    assert seen["cmd"] == ["echo", "hi"]
    assert seen["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8799"
    assert seen["env"]["OPENAI_BASE_URL"] == "http://127.0.0.1:8799/v1"


def test_run_empty_command_errors():
    with pytest.raises(SystemExit):
        ob.run_agent([], root=None)


def test_run_command_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(ob, "_ensure_index", lambda rebuild: None)
    monkeypatch.setattr(ob, "_start_proxy", lambda r: _FakeServer())

    def boom(cmd, env=None):
        raise FileNotFoundError(cmd[0])
    monkeypatch.setattr(ob.subprocess, "run", boom)
    rc = ob.run_agent(["nope-xyz"], root=tmp_path)
    assert rc == 127


# --- Task 6: init ----------------------------------------------------------

def _isolate(tmp_path, monkeypatch):
    """Point the engine at tmp_path so init's index.build never touches the real repo."""
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / ".keymd" / "index.db"))
    from keymd.engine import config as c
    c.project_pkg_prefixes.cache_clear()
    c._git_toplevel.cache_clear()


def test_init_writes_toml_and_is_idempotent(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    (tmp_path / "m.py").write_text("y = 2\n", encoding="utf-8")
    assert ob.init(path=str(tmp_path)) == 0
    cfg = tmp_path / "keymd.toml"
    assert cfg.exists() and "[keymd.serve]" in cfg.read_text(encoding="utf-8")
    before = cfg.read_text(encoding="utf-8")
    capsys.readouterr()
    ob.init(path=str(tmp_path))                       # no clobber
    assert cfg.read_text(encoding="utf-8") == before
    assert "already" in capsys.readouterr().out.lower()


def test_init_write_agents_appends_once(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    ob.init(path=str(tmp_path), write_agents=True)
    agents = tmp_path / "AGENTS.md"
    assert agents.exists() and "keymd steering snippet" in agents.read_text(encoding="utf-8")
    ob.init(path=str(tmp_path), force=True, write_agents=True)   # not duplicated
    assert agents.read_text(encoding="utf-8").count("keymd steering snippet") == 1


# --- Task 7: doctor --------------------------------------------------------

def test_doctor_hard_fails_without_index(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    (tmp_path / "z.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    rc = ob.doctor()                                  # index not built yet
    out = capsys.readouterr().out
    assert "index" in out.lower()
    assert rc != 0


def test_doctor_passes_after_build(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    (tmp_path / "z.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    from keymd.engine import index
    index.build(verbose=False)
    rc = ob.doctor()
    assert rc == 0
    assert "✓" in capsys.readouterr().out
