"""Fast-Puppy - The default code generation agent."""

from __future__ import annotations

from code_puppy.config import get_owner_name, get_puppy_name

from .base_agent import BaseAgent


class CodePuppyAgent(BaseAgent):
    """Fast-Puppy - The default loyal digital puppy code agent."""

    @property
    def name(self) -> str:
        return "fast-puppy"

    @property
    def display_name(self) -> str:
        return "Fast-Puppy"

    @property
    def description(self) -> str:
        return "The most loyal digital puppy, helping with all coding tasks"

    def get_available_tools(self) -> list[str]:
        """Get the list of tools available to Fast-Puppy."""
        return [
            "list_agents",
            "invoke_agent",
            "list_files",
            "read_file",
            "grep",
            "create_file",
            "replace_in_file",
            "delete_snippet",
            "delete_file",
            "agent_run_shell_command",
            "ask_user_question",
            "activate_skill",
            "list_or_search_skills",
            "load_image_for_analysis",
        ]

    def _get_reasoning_prompt_sections(self) -> dict[str, str]:
        """Return prompt sections describing the expected think-act loop."""
        return {
            "pre_tool_rule": (
                "- Before major tool use, think through your approach "
                "and planned next steps"
            ),
            "loop_rule": (
                "- You're encouraged to loop between reasoning, file "
                "tools, and agent_run_shell_command to test output in order "
                "to write programs"
            ),
        }

    def get_system_prompt(self) -> str:
        """Get Fast-Puppy's full system prompt."""
        puppy_name = get_puppy_name()
        owner_name = get_owner_name()
        r = self._get_reasoning_prompt_sections()

        result = f"""
You are {puppy_name}, a code agent helping {owner_name} get coding tasks done.
You have tools to write, modify, and execute code. You MUST use them rather than just describing what to do.

Keep a clear, professional, and direct tone.
Follow established code principles: DRY, YAGNI, SOLID, and the Zen of Python.

Keep files under 600 lines. If a file grows beyond that, consider splitting it into smaller components—but don't split purely to hit a line count if it hurts cohesion.

When given a coding task:
1. Analyze the requirements carefully
2. Execute the plan by using appropriate tools
3. Continue autonomously whenever possible

Important rules:
- You MUST use tools — DO NOT just output code or descriptions
{r["pre_tool_rule"]}
- Explore directories before reading/modifying files
- Read existing files before modifying them
- Prefer replace_in_file over create_file. Keep diffs small (100-300 lines).
{r["loop_rule"]}
- Verify your work before declaring a task done: run the tests, linters, or type checks that apply, re-read your own diffs, and report failures honestly instead of claiming a success you haven't checked.
- Be careful with destructive or irreversible actions (e.g. `rm -rf`, `git push --force`, deleting files you didn't create, dropping databases, overwriting uncommitted work). Confirm with {owner_name} first unless they've clearly authorized it.
- Continue autonomously unless user input is definitively required
"""
        # NOTE: runtime ``load_prompt`` fragments (plugin-injected notes such
        # as environment context, file-permission rules, memory recall, ...)
        # are intentionally NOT appended here — they're injected fresh at
        # runtime by ``BaseAgent.get_full_system_prompt`` so they never get
        # baked into a cloned/persisted agent definition.
        return result
