"""Register the Obsidian Agent plugin."""
from __future__ import annotations

from code_puppy.callbacks import register_callback

from .agent_obsidian import ObsidianAgent


def register_agents() -> list[dict[str, object]]:
    """Register the Obsidian Agent with Fast Puppy's agent catalog."""
    return [{"name": "obsidian-agent", "class": ObsidianAgent}]


register_callback("register_agents", register_agents)
