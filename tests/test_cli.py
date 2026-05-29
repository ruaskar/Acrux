from keymd import cli


def test_cli_run_parses_double_dash(monkeypatch):
    from keymd import onboarding
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return 0
    monkeypatch.setattr(onboarding, "run_agent", fake_run)
    rc = cli.main(["run", "--port", "8799", "--", "claude", "--flag"])
    assert rc == 0 and seen["cmd"] == ["claude", "--flag"]


def test_cli_up_calls_onboarding(monkeypatch):
    from keymd import onboarding
    called = {}

    def fake_up(**kw):
        called["ok"] = True
        return 0
    monkeypatch.setattr(onboarding, "up", fake_up)
    assert cli.main(["up", "--port", "9001"]) == 0 and called["ok"]


def test_cli_build_then_impact(env_proj, capsys):
    assert cli.main(["build", "--quiet"]) == 0
    out = capsys.readouterr().out
    assert "files" in out
    import os
    parser_py = os.path.join(str(env_proj), "pkg", "parser.py")
    assert cli.main(["impact", parser_py]) == 0
    out = capsys.readouterr().out
    assert "pipeline.py" in out
