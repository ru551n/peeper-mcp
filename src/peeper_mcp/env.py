"""Environment lookup for the peeper-mcp configuration.

Configuration variables are named ``PEEPER_MCP_*`` (like the sibling MCP
servers: ``VUNIT_MCP_*``, ``YOSYNTH_MCP_*``, ``VHDL_RAG_MCP_*``). The
project's former name (``waver-mcp``) used ``WAVE_MCP_*``, and before that
plain ``WAVE_*``; both are still honored as deprecated fallbacks so
existing client configurations keep working.
"""

from __future__ import annotations

import os


def env_int(name: str, default: str) -> int:
    """Parse ``PEEPER_MCP_<name>`` (or the deprecated ``WAVE_MCP_<name>``
    / ``WAVE_<name>`` fallbacks) as an int; the first non-empty value
    wins, else default."""
    for key in (f"PEEPER_MCP_{name}", f"WAVE_MCP_{name}", f"WAVE_{name}"):
        raw = os.environ.get(key, "").strip()
        if raw:
            return int(raw)
    return int(default)
