from keymd.proxy import tools


def test_virtual_defs_cover_expected_tools():
    names = {d["name"] for d in tools.VIRTUAL_TOOL_DEFS}
    assert {"keymd_read", "keymd_read_full", "keymd_impact",
            "keymd_callers", "keymd_callees", "keymd_search"} <= names
    for d in tools.VIRTUAL_TOOL_DEFS:
        assert d["description"] and d["schema"]["type"] == "object"


def test_directive_mentions_summary_first():
    assert "keymd_read" in tools.SYSTEM_DIRECTIVE
    assert "keymd_read_full" in tools.SYSTEM_DIRECTIVE
