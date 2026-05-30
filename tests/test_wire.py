"""Phase 0: `keymd init -g` auto-wire — patch an agent's config to route through
the keymd proxy, idempotently, with a one-time backup and a clean undo."""
import json

import pytest

from keymd import wire
from keymd import onboarding as ob


# --- pure patchers ----------------------------------------------------------

def test_apply_merges_base_url_and_backs_up(tmp_path):
    cfg = tmp_path / "settings.json"
    cfg.write_text(json.dumps({"env": {"FOO": "bar"}}), encoding="utf-8")
    wire.apply_claude(cfg, base="http://127.0.0.1:8787")
    got = json.loads(cfg.read_text(encoding="utf-8"))
    assert got["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8787"
    assert got["env"]["FOO"] == "bar"                        # preserved
    assert (tmp_path / "settings.json.keymd.bak").exists()   # original backed up


def test_apply_creates_missing_file(tmp_path):
    cfg = tmp_path / "nested" / "settings.json"              # parent doesn't exist
    wire.apply_claude(cfg, base="http://h:1")
    got = json.loads(cfg.read_text(encoding="utf-8"))
    assert got["env"]["ANTHROPIC_BASE_URL"] == "http://h:1"


def test_apply_idempotent_no_dup(tmp_path):
    cfg = tmp_path / "settings.json"
    cfg.write_text("{}", encoding="utf-8")
    wire.apply_claude(cfg, base="http://h:1")
    wire.apply_claude(cfg, base="http://h:1")                # second: no error, no dup
    env = json.loads(cfg.read_text(encoding="utf-8"))["env"]
    assert env == {"ANTHROPIC_BASE_URL": "http://h:1"}


def test_apply_tolerates_garbage_json(tmp_path):
    cfg = tmp_path / "settings.json"
    cfg.write_text("not json {", encoding="utf-8")           # corrupt → treat as empty
    wire.apply_claude(cfg, base="http://h:1")
    assert json.loads(cfg.read_text(encoding="utf-8"))["env"]["ANTHROPIC_BASE_URL"] == "http://h:1"


def test_undo_removes_key_keymd_added(tmp_path):
    cfg = tmp_path / "settings.json"
    cfg.write_text(json.dumps({"env": {"FOO": "bar"}}), encoding="utf-8")
    wire.apply_claude(cfg, base="http://h:1")
    assert wire.undo_claude(cfg) is True
    env = json.loads(cfg.read_text(encoding="utf-8")).get("env", {})
    assert "ANTHROPIC_BASE_URL" not in env
    assert env.get("FOO") == "bar"                           # untouched


def test_undo_restores_prior_user_value(tmp_path):
    cfg = tmp_path / "settings.json"
    cfg.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": "http://mine"}}), encoding="utf-8")
    wire.apply_claude(cfg, base="http://127.0.0.1:8787")     # keymd overrides
    wire.undo_claude(cfg)
    env = json.loads(cfg.read_text(encoding="utf-8"))["env"]
    assert env["ANTHROPIC_BASE_URL"] == "http://mine"        # restored, not removed


def test_undo_when_absent_is_noop(tmp_path):
    cfg = tmp_path / "settings.json"
    cfg.write_text("{}", encoding="utf-8")
    assert wire.undo_claude(cfg) is False


def test_apply_refuses_non_dict_env_without_data_loss(tmp_path):
    cfg = tmp_path / "settings.json"
    cfg.write_text(json.dumps({"env": ["x"]}), encoding="utf-8")   # env is a list
    with pytest.raises(ValueError):
        wire.apply_claude(cfg, base="http://h:1")
    assert json.loads(cfg.read_text(encoding="utf-8")) == {"env": ["x"]}   # untouched
    assert not (tmp_path / "settings.json.keymd.bak").exists()             # no stray backup


def test_double_apply_then_undo_restores_true_original(tmp_path):
    # The highest-risk data path: backup-once must hold the FIRST original across
    # repeated applies, so undo returns the file to its pre-keymd state.
    cfg = tmp_path / "settings.json"
    cfg.write_text(json.dumps({"env": {"FOO": "bar"}}), encoding="utf-8")
    wire.apply_claude(cfg, base="http://one")
    wire.apply_claude(cfg, base="http://two")     # must NOT overwrite the original backup
    wire.undo_claude(cfg)
    assert json.loads(cfg.read_text(encoding="utf-8")) == {"env": {"FOO": "bar"}}


# --- CLI-facing orchestration ----------------------------------------------

def _fixed_resolve(monkeypatch):
    monkeypatch.setattr(ob, "resolve",
        lambda **k: ob.Resolved(host="127.0.0.1", port=8787, threshold=400,
                                wire="openai", upstream=None))


def test_wire_global_claude_apply_and_undo(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / ".claude" / "settings.json"
    monkeypatch.setitem(ob._AGENT_PATHS, "claude", lambda: cfg)
    _fixed_resolve(monkeypatch)
    assert ob.wire_global(agent="claude") == 0
    assert "ANTHROPIC_BASE_URL=http://127.0.0.1:8787" in capsys.readouterr().out
    assert json.loads(cfg.read_text(encoding="utf-8"))["env"]["ANTHROPIC_BASE_URL"] \
        == "http://127.0.0.1:8787"
    assert ob.wire_global(agent="claude", undo=True) == 0
    assert "ANTHROPIC_BASE_URL" not in json.loads(cfg.read_text(encoding="utf-8")).get("env", {})


def test_wire_global_unknown_agent(capsys):
    assert ob.wire_global(agent="nope-xyz") == 1
    assert "unknown agent" in capsys.readouterr().out.lower()


def test_cli_init_g_dispatches(tmp_path, monkeypatch):
    from keymd import cli
    cfg = tmp_path / ".claude" / "settings.json"
    monkeypatch.setitem(ob._AGENT_PATHS, "claude", lambda: cfg)
    _fixed_resolve(monkeypatch)
    assert cli.main(["init", "-g"]) == 0
    assert cfg.exists()


def test_cli_init_undo_without_global_errors():
    # `--undo` without `-g` must NOT silently fall through to a normal project init.
    from keymd import cli
    with pytest.raises(SystemExit):
        cli.main(["init", "--undo"])


def test_wire_global_refuses_non_dict_env(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / ".claude" / "settings.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"env": "oops"}), encoding="utf-8")
    monkeypatch.setitem(ob._AGENT_PATHS, "claude", lambda: cfg)
    _fixed_resolve(monkeypatch)
    assert ob.wire_global(agent="claude") == 1
    assert "refusing" in capsys.readouterr().out.lower()
    assert json.loads(cfg.read_text(encoding="utf-8")) == {"env": "oops"}   # untouched
