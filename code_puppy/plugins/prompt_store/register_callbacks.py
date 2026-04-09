"""Callback registration for prompt_store plugin.

Registers callbacks for:
- load_prompt: Injects user's custom prompts into system prompts (early hook for base prompt)
- custom_command: Handles /prompts slash commands
- custom_command_help: Advertises /prompts commands in /help menu

Storage: ~/.code_puppy/prompt_store.json (configurable via PUPPY_PROMPT_STORE env var)

Note on hook architecture:
    - load_prompt: Used for base system prompt contributions (returns str | None)
    - get_model_system_prompt: Used for model-specific overrides (returns dict | None)
    
    prompt_store uses load_prompt to provide the base template, which then gets
    enhanced by other plugins (agent_skills, repo_compass) via get_model_system_prompt.
    This prevents collisions where prompt_store would overwrite other plugins' content.
"""

from __future__ import annotations

import logging

from code_puppy.callbacks import register_callback

from .commands import get_prompts_help, handle_prompts_command, load_custom_prompt

logger = logging.getLogger(__name__)


def _register() -> None:
    """Register all prompt_store callbacks."""
    # Hook into system prompt generation at the load_prompt phase.
    # This runs BEFORE get_model_system_prompt hooks, allowing other plugins
    # (like agent_skills and repo_compass) to enhance our base template.
    register_callback("load_prompt", load_custom_prompt)

    # Register slash command handlers
    register_callback("custom_command", handle_prompts_command)

    # Register help entries for /help menu
    register_callback("custom_command_help", get_prompts_help)

    logger.info("Prompt Store plugin loaded")
    logger.debug("Storage: ~/.code_puppy/prompt_store.json")


# Auto-register on import
_register()
