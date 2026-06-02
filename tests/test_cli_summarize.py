"""The `keymd summarize` CLI subcommand parses args and dispatches to run.summarize."""
from keymd import cli


def test_summarize_subcommand_dispatches(monkeypatch, capsys):
    called = {}

    def fake_summarize(path, wire_name, model, limit, threshold):
        called.update(path=path, wire=wire_name, model=model,
                      limit=limit, threshold=threshold)
        return {"summarized": 2, "skipped": 1, "failed": 0, "model": model}

    monkeypatch.setattr("keymd.summarize.run.summarize", fake_summarize)
    rc = cli.main(["summarize", "/repo", "--wire", "anthropic",
                   "--model", "claude-sonnet-4-6", "--limit", "5"])
    assert rc == 0
    assert called["wire"] == "anthropic" and called["model"] == "claude-sonnet-4-6"
    assert called["path"] == "/repo" and called["limit"] == 5
    out = capsys.readouterr().out
    assert "summarized 2" in out


def test_summarize_defaults(monkeypatch):
    called = {}

    def fake_summarize(path, wire_name, model, limit, threshold):
        called.update(path=path, wire=wire_name, threshold=threshold)
        return {"summarized": 0, "skipped": 0, "failed": 0, "model": model}

    monkeypatch.setattr("keymd.summarize.run.summarize", fake_summarize)
    rc = cli.main(["summarize"])
    assert rc == 0
    assert called["path"] is None and called["wire"] == "openai"  # default wire
    assert called["threshold"] == 50                              # default gated threshold
