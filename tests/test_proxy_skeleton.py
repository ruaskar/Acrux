def test_proxy_package_importable():
    import keymd.proxy  # noqa: F401
    import keymd.proxy.adapters  # noqa: F401
    assert True
