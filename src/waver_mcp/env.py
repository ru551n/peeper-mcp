"""Environment lookup for the waver-mcp configuration.

Configuration variables are named ``WAVE_MCP_*`` (like the sibling MCP
servers: ``VUNIT_MCP_*``, ``YOSYNTH_MCP_*``, ``VHDL_RAG_MCP_*``). The
original ``WAVE_*`` names are still honored as a deprecated fallback so
existing client configurations keep working.
"""

from __future__ import annotations

import os


def env_int(name: str, default: str) -> int:
    """Parse ``WAVE_MCP_<name>`` (or the deprecated ``WAVE_<name>``
    fallback) as an int; the first non-empty value wins, else default."""
    for key in (f"WAVE_MCP_{name}", f"WAVE_{name}"):
        raw = os.environ.get(key, "").strip()
        if raw:
            return int(raw)
    return int(default)
