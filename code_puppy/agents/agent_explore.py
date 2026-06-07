"""Explore Agent - Fast, cheap, read-only codebase explorer."""

from __future__ import annotations

from code_puppy.config import (
    get_agent_pinned_model,
    get_puppy_name,
    set_agent_pinned_model,
)
from code_puppy.model_factory import ModelFactory

from .base_agent import BaseAgent

_DEFAULT_EXPLORE_MODEL = "stepfun-step-3.7-flash"


def _set_default_explore_model_pin() -> None:
    """Pin a cheap default model for the explore agent if not already configured.

    Uses the current config-backed model registry state, and only sets the
    pin when the model actually exists. This avoids writing invalid defaults
    at import time.
    """
    if get_agent_pinned_model("explore") is not None:
        return

    try:
        models = ModelFactory.load_config()
    except Exception:
        return

    available_models = set(models.keys())
    if _DEFAULT_EXPLORE_MODEL not in available_models:
        return

    set_agent_pinned_model("explore", _DEFAULT_EXPLORE_MODEL)


def _register_explore_startup_pin() -> None:
    """Apply the default explore model pin once at application startup."""
    _set_default_explore_model_pin()


class ExploreAgent(BaseAgent):
    """Fast, low-cost, read-only codebase explorer for file discovery and context gathering."""

    @property
    def name(self) -> str:
        return "explore"

    @property
    def display_name(self) -> str:
        return "Explore 🔍"

    @property
    def description(self) -> str:
        return (
            "Fast, low-cost, read-only codebase explorer. "
            "Discover files, walk the repo, and gather context without modifying anything. "
            "Leaf agent — delegates to no one."
        )

    def get_available_tools(self) -> list[str]:
        """Get the list of tools available to the Explore agent.

        Strictly read-only tool set. No write tools, no invoke_agent.
        """
        return [
            "list_files",
            "read_file",
            "grep",
            "agent_run_shell_command",
            "list_or_search_skills",
        ]

    def get_system_prompt(self) -> str:
        """Get the Explore agent's system prompt."""
        puppy_name = get_puppy_name()

        return f"""You are {puppy_name} in Explore Mode — a fast, low-cost, READ-ONLY codebase explorer. You are the cheap first-pass other agents call to discover files, walk the repo, and gather context.

HARD RULES: READ-ONLY. Never create/modify/delete files. Never run write or destructive shell commands. If asked to change code, report findings and state that edits are out of scope.

WORKFLOW: (1) Restate the target in one line. (2) grep/list_files to locate relevant files BEFORE reading. (3) read_file only the most relevant spans. (4) Report concisely.

OUTPUT: Lead with the answer. Then relevant file paths (with line refs), key snippets, and a 1-3 sentence summary. No speculation, no planning, no fluff.

EFFICIENCY: Prefer search over full-file reads; never re-read; stop as soon as the question is answered."""
