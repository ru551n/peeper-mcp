"""Package smoke tests."""

import waver_mcp


def test_version() -> None:
    assert waver_mcp.__version__ == "0.1.0"
