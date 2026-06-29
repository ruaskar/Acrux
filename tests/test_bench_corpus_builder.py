# tests/test_bench_corpus_builder.py
from benchmarks.terminalbench.build_corpus import parse_solve_sh


def test_parses_reads_and_greps():
    sh = "#!/bin/bash\ncat src/main.py\ngrep -rn 'TODO' src/\nls -R data/\n"
    cmds = parse_solve_sh(sh)
    kinds = {c["tool"] for c in cmds}
    assert "cat" in kinds and "grep" in kinds and "ls" in kinds
    assert any(c.get("path") == "src/main.py" for c in cmds)


def test_ignores_non_read_commands():
    sh = "python train.py\nrm -rf /tmp/x\necho done\n"
    assert parse_solve_sh(sh) == []
