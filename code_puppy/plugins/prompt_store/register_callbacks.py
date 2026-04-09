"""Callback registration for prompt_store plugin.

Registers callbacks for:
- get_model_system_prompt: Injects user's custom prompts into agent system prompts
- custom_command: Handles /prompts slash commands
- custom_command_help: Advertises /prompts commands in /help menu

Storage: ~/.code_puppy/prompt_store.json (configurable via PUPPY_PROMPT_STORE env var)
"""

from __future__ import annotations

import logging

from code_puppy.callbacks import register_callback

from .commands import get_prompts_help, handle_prompts_command, inject_custom_prompt

logger = logging.getLogger(__name__)


def _register() -> None:
    """Register all prompt_store callbacks."""
    # Hook into system prompt generation - inject custom prompts if set
    register_callback("get_model_system_prompt", inject_custom_prompt)

    # Register slash command handlers
    register_callback("custom_command", handle_prompts_command)

    # Register help entries for /help menu
    register_callback("custom_command_help", get_prompts_help)

    logger.info("Prompt Store plugin loaded")
    logger.debug("Storage: ~/.code_puppy/prompt_store.json")


# Auto-register on import
_register()
