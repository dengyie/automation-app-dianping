def test_app_package_imports():
    from automation_app_dianping import __version__

    assert __version__ == "0.1.0"
