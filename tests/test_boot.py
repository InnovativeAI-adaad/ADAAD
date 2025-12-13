def test_boot_imports():
    import app.main as m  # noqa: WPS433
    assert hasattr(m, "main")
