import keymd


def test_version_is_exposed():
    assert isinstance(keymd.__version__, str)
    assert keymd.__version__.count(".") >= 1
