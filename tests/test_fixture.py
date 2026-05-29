def test_sample_proj_present(sample_proj):
    assert (sample_proj / "pkg" / "parser.py").exists()
    assert (sample_proj / "pkg" / "pipeline.py").exists()
