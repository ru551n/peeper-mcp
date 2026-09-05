"""Tests for the time model (parse/format against file timescales)."""

from decimal import Decimal

import pytest

from waver_mcp.timeutil import (
    TimeValueError,
    format_ticks,
    parse_time,
    ticks_per_second,
)

FS = ticks_per_second(1, "fs")
PS = ticks_per_second(1, "ps")
NS = ticks_per_second(1, "ns")


@pytest.mark.parametrize(
    ("value", "tps", "expected"),
    [
        # Integers are raw ticks: pass through.
        (0, FS, 0),
        (12345, NS, 12345),
        # Unit conversion.
        ("10ns", FS, 10_000_000),
        ("1.5us", ticks_per_second(100, "ps"), 15000),
        ("2ms", NS, 2_000_000),
        ("1s", NS, 1_000_000_000),
        ("1fs", FS, 1),
        ("1ps", PS, 1),
        # Zero with a unit is fine.
        ("0ns", FS, 0),
        # Bare integer strings are file ticks (LLMs often send "0" as a str).
        ("10", FS, 10),
        (" 1000", FS, 1000),
    ],
)
def test_parse_time(value: int | str, tps: Decimal, expected: int) -> None:
    assert parse_time(value, tps) == expected


@pytest.mark.parametrize("value", ["10ns", "10NS", "10 Ns"])
def test_parse_time_unit_case_insensitive(value: str) -> None:
    assert parse_time(value, FS) == 10_000_000


def test_parse_time_micro_sign() -> None:
    assert parse_time("1\u00b5s", PS) == 1_000_000
    assert parse_time("1us", PS) == 1_000_000


@pytest.mark.parametrize(
    ("value", "tps"),
    [
        ("abc", FS),
        ("-5", FS),  # negative
        ("-5ns", FS),
        ("", FS),
        ("1.25fs", ticks_per_second(3, "fs")),  # off timescale
        ("1ns", ticks_per_second(3, "fs")),  # 333.33 ticks
    ],
)
def test_parse_time_rejects(value: str, tps: Decimal) -> None:
    with pytest.raises(TimeValueError):
        parse_time(value, tps)


def test_parse_time_rejects_negative_int() -> None:
    with pytest.raises(TimeValueError):
        parse_time(-5, FS)


@pytest.mark.parametrize(
    ("value", "tps", "suggestion"),
    [
        # 1ns at a 3fs timescale is 333333.33... ticks -> rounds to
        # 999.999ps (333333 ticks).
        ("1ns", ticks_per_second(3, "fs"), "999.999ps"),
        # 1.25fs at a 3fs timescale rounds down to 0 ticks.
        ("1.25fs", ticks_per_second(3, "fs"), "0ns"),
    ],
)
def test_parse_time_rounding_error_suggests_nearest_tick(
    value: str, tps: Decimal, suggestion: str
) -> None:
    with pytest.raises(TimeValueError, match=f"did you mean {suggestion!r}"):
        parse_time(value, tps)


@pytest.mark.parametrize(
    ("ticks", "tps", "expected"),
    [
        (0, FS, "0ns"),
        (10_000_000, FS, "10ns"),
        (500_000, FS, "500ps"),
        (500_000_000, FS, "500ns"),
        (1_000_000_000_000_000, FS, "1s"),
        (1, FS, "1fs"),
        (1_000_000, NS, "1ms"),
        (1_000_000_000, NS, "1s"),
    ],
)
def test_format_ticks(ticks: int, tps: Decimal, expected: str) -> None:
    assert format_ticks(ticks, tps) == expected


def test_format_ticks_negative() -> None:
    with pytest.raises(TimeValueError):
        format_ticks(-1, FS)


def test_ticks_per_second() -> None:
    assert ticks_per_second(1, "ps") == Decimal("1e-12")
    assert ticks_per_second(100, "ps") == Decimal("1e-10")
    assert ticks_per_second(1, "NS") == Decimal("1e-9")


def test_ticks_per_second_rejects() -> None:
    with pytest.raises(TimeValueError):
        ticks_per_second(0, "ns")
    with pytest.raises(TimeValueError):
        ticks_per_second(1, "years")
