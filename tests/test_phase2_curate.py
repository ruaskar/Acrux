from benchmarks.phase2 import curate


def test_selects_reading_heavy_code_task():
    meta = {"instruction": "fix the bug in the python package", "has_repo": True}
    solve = "cat src/app/main.py\ngrep -rn handler src/app/\ncat src/app/util.py\n"
    sel, reason = curate.is_code_nav_task(meta, solve)
    assert sel is True


def test_rejects_ml_train_task():
    meta = {"instruction": "train a CNN to 95% accuracy", "has_repo": False}
    solve = "python train.py --epochs 50\n"
    sel, reason = curate.is_code_nav_task(meta, solve)
    assert sel is False
    assert "read" in reason.lower() or "code" in reason.lower()


def test_solve_sh_not_counted_as_source():
    # solve.sh reads ONE real source file + the solve.sh script itself.
    # solve.sh must NOT count as a source read, so distinct sources == 1 → reject.
    meta = {"has_repo": True}
    solve = "cat src/main.py\ncat solve.sh\n"
    sel, reason = curate.is_code_nav_task(meta, solve)
    assert sel is False


def test_rejects_single_file_read():
    meta = {"instruction": "edit one file", "has_repo": True}
    solve = "cat README.md\n"
    sel, reason = curate.is_code_nav_task(meta, solve)
    assert sel is False
