from keymd.proxy.adapters import base


def test_toolcall_shape():
    tc = base.ToolCall(id="t1", name="Read", input={"file_path": "a.py"})
    assert tc.id == "t1" and tc.name == "Read" and tc.input["file_path"] == "a.py"
