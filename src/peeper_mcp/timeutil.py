"""Simulation-time parsing and formatting.

peeper-mcp tools accept times as human-readable strings (``"10ns"``,
``"1.5us"``) or as bare integers (ticks of the file's timescale). This
module converts between the two against a file's timescale, so callers
never have to reason about raw tick counts.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

#: Seconds per VHDL/VCD time unit (lookup is case-insensitive on the unit).
_SECONDS_PER_UNIT: dict[str, Decimal] = {
    "s": Decimal(1),
    "ms": Decimal("1e-3"),
    "us": Decimal("1e-6"),
    "\u00b5s": Decimal("1e-6"),
    "ns": Decimal("1e-9"),
    "ps": Decimal("1e-12"),
    "fs": Decimal("1e-15"),
}

#: Display units, most to least significant, with seconds per unit.
_DISPLAY_UNITS: tuple[tuple[str, Decimal], ...] = (
    ("s", Decimal(1)),
    ("ms", Decimal("1e-3")),
    ("us", Decimal("1e-6")),
    ("ns", Decimal("1e-9")),
    ("ps", Decimal("1e-12")),
    ("fs", Decimal("1e-15")),
)

_TIME_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(fs|ps|ns|us|\u00b5s|ms|s)\s*$", re.IGNORECASE
)

#: Bare integer (optionally signed) = file time ticks, no unit.
_INT_RE = re.compile(r"^\s*(-?\d+)\s*$")


class TimeValueError(ValueError):
    """Raised for unparseable or off-timescale time values."""


def parse_time(value: str | int, ticks_per_second: Decimal) -> int:
    """Convert a time to integer ticks of the file's timescale.

    Integers and bare-integer strings (``"0"``, ``"1000"``) are file time
    ticks. Other strings are ``<number><unit>`` (e.g. ``"10ns"``,
    ``"1.5us"``, ``"2ms"``; unit fs, ps, ns, us/µs, ms or s,
    case-insensitive). Negative times are rejected.
    """
    if isinstance(value, int):
        ticks = value
    else:
        int_match = _INT_RE.match(value)
        if int_match is not None:
            ticks = int(int_match.group(1))
        else:
            match = _TIME_RE.match(value)
            if match is None:
                raise TimeValueError(
                    f"unrecognized time {value!r}: use '<number><unit>' with "
                    "unit fs, ps, ns, us, ms, s (e.g. '10ns'), or an integer "
                    "number of file time ticks"
                )
            seconds = (
                Decimal(match.group(1)) * _SECONDS_PER_UNIT[match.group(2).lower()]
            )
            ticks_decimal = seconds / ticks_per_second
            rounded = ticks_decimal.to_integral_value(rounding=ROUND_HALF_UP)
            if rounded != ticks_decimal:
                suggestion = format_ticks(int(rounded), ticks_per_second)
                raise TimeValueError(
                    f"time {value!r} is not a whole number of file time ticks "
                    f"(file timescale is {ticks_per_second} s per tick); "
                    f"did you mean {suggestion!r}?"
                )
            ticks = int(rounded)
    if ticks < 0:
        raise TimeValueError(f"negative time: {value!r}")
    return ticks


def display_unit(ticks: int, ticks_per_second: Decimal) -> tuple[str, Decimal]:
    """Largest display unit for which *ticks* is at least one unit wide.

    ``10_000_000`` ticks of a 1 fs file is ``("ns", Decimal("1e-9"))``.
    """
    if ticks < 0:
        raise TimeValueError(f"negative time: {ticks} ticks")
    seconds = Decimal(ticks) * ticks_per_second
    for unit, per_unit in _DISPLAY_UNITS:
        if seconds / per_unit >= 1:
            return unit, per_unit
    return "fs", _SECONDS_PER_UNIT["fs"]


def format_ticks(ticks: int, ticks_per_second: Decimal) -> str:
    """Format ticks as the largest human-readable unit with value >= 1.

    ``10_000_000`` ticks of a 1 fs file becomes ``"10ns"``.
    """
    if ticks < 0:
        raise TimeValueError(f"negative time: {ticks} ticks")
    if ticks == 0:
        return "0ns"
    unit, per_unit = display_unit(ticks, ticks_per_second)
    amount = Decimal(ticks) * ticks_per_second / per_unit
    return f"{amount.normalize():f}{unit}"


def ticks_per_second(factor: int, unit: str) -> Decimal:
    """Seconds per tick for a (factor, unit) timescale pair.

    Matches the timescale metadata reported by waveform files (e.g. nvc
    files commonly use factor 1 with unit fs).
    """
    if factor <= 0:
        raise TimeValueError(f"invalid timescale factor: {factor}")
    seconds_per_unit = _SECONDS_PER_UNIT.get(unit.lower())
    if seconds_per_unit is None:
        raise TimeValueError(f"unsupported timescale unit: {unit!r}")
    return Decimal(factor) * seconds_per_unit
