"""Phase 0 smoke test: verify the package is importable."""


def test_tessera_is_importable() -> None:
    import tessera

    assert tessera is not None
