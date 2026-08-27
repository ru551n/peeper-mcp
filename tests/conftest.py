"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def all_types_path() -> Path:
    """Small FST covering int/vec/enum-string/X-Z/real/string signals."""
    return FIXTURES / "all_types.fst"


@pytest.fixture
def bench_path() -> Path:
    """Dense FST: 2 ms of a 100 MHz clock plus wide vectors (~400k changes)."""
    return FIXTURES / "bench.fst"
