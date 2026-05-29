from keymd.guardrails import checks
from keymd.guardrails import cli as gcli
from keymd import cli


def test_is_protected_push():
    assert checks.is_protected_push("main") is True
    assert checks.is_protected_push("master") is True
    assert checks.is_protected_push("feature/x") is False
    assert checks.is_protected_push("release", protected=("release",)) is True


def test_duplicate_candidates():
    sibs = ["process_data.py", "data_processor.py", "unrelated.py"]
    # shares {process, data} with process_data.py
    assert "process_data.py" in checks.duplicate_candidates("process_data_v2.py", sibs)
    # 'unrelated' shares nothing
    assert "unrelated.py" not in checks.duplicate_candidates("process_data_v2.py", sibs)
    # too-few tokens => no candidates
    assert checks.duplicate_candidates("a.py", sibs) == []


def test_uncommitted_in_scope():
    changed = ["pkg/a.py", "docs/x.md", "pkg/sub/b.py"]
    assert checks.uncommitted_in_scope(changed, ["pkg/"]) == ["pkg/a.py", "pkg/sub/b.py"]
    assert checks.uncommitted_in_scope(changed, ["nope/"]) == []


def test_guard_cli_exit_codes(capsys):
    assert gcli.run("check-push", ["main"]) == 1      # blocked
    assert gcli.run("check-push", ["feature/x"]) == 0  # allowed
    assert cli.main(["guard", "check-push", "main"]) == 1
    assert cli.main(["guard", "check-push", "dev"]) == 0
