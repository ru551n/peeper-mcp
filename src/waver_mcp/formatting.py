"""Rendering helpers for tool output (values, truncation notices)."""

from __future__ import annotations

MAX_STRING_LEN = 64


def format_value(value: object, bitwidth: int | None) -> str:
    """Render one sampled value for display.

    Ints are decimal, except wide (>= 32 bit) signals, which are hex —
    that is how a human (or an LLM) reads a 32+ bit datapath. Strings
    (X/Z samples, enums-as-strings, character strings) are quoted and
    capped so a 1024-char string cannot blow up the output.
    """
    if isinstance(value, str):
        if len(value) > MAX_STRING_LEN:
            return f'"{value[:MAX_STRING_LEN]}..." (truncated)'
        return f'"{value}"'
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, int):
        if bitwidth is not None and bitwidth >= 32:
            return f"0x{value:x}"
        return str(value)
    return str(value)


def truncation_note(shown: int, total: int, hint: str = "") -> str:
    suffix = f" {hint}" if hint else ""
    return f"showing {shown} of {total}{suffix}"
