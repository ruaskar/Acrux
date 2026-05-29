from keymd import cli


def test_cli_build_then_impact(env_proj, capsys):
    assert cli.main(["build", "--quiet"]) == 0
    out = capsys.readouterr().out
    assert "files" in out
    import os
    parser_py = os.path.join(str(env_proj), "pkg", "parser.py")
    assert cli.main(["impact", parser_py]) == 0
    out = capsys.readouterr().out
    assert "pipeline.py" in out
