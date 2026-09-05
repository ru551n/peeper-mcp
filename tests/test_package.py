"""Package smoke tests."""

import peeper_mcp


def test_version() -> None:
    assert peeper_mcp.__version__ == "0.1.0"
