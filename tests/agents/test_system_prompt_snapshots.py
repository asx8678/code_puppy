"""Snapshot tests for agent system prompts.

These tests catch accidental prompt drift. If a test fails and the change is
intentional, run:
    pytest tests/agents/test_system_prompt_snapshots.py --update-snapshots

Then review the diff in tests/snapshots/system_prompts/ and commit if correct.

Normalization:
Dynamic content (dates, agent IDs, absolute paths) is normalized to placeholders
to ensure snapshots are deterministic across runs and machines. See
`_snapshot_helpers.normalize_for_snapshot()` for details.
"""

from __future__ import annotations

import pytest
from unittest.mock import patch

from code_puppy.agents.agent_code_puppy import CodePuppyAgent
from code_puppy.agents.agent_pack_leader import PackLeaderAgent
from code_puppy.agents.agent_turbo_executor import TurboExecutorAgent
from code_puppy.agents.agent_security_auditor import SecurityAuditorAgent
from code_puppy.agents.agent_code_reviewer import CodeQualityReviewerAgent
from code_puppy.agents.agent_terminal_qa import TerminalQAAgent
from code_puppy.agents.agent_python_programmer import PythonProgrammerAgent
from code_puppy.agents.agent_qa_expert import QAExpertAgent

from tests.agents._snapshot_helpers import assert_snapshot, normalize_for_snapshot


# List of agents to snapshot. Focused on stable user-facing agents.
# Each tuple is (agent_name, agent_class) for direct instantiation.
AGENTS_TO_SNAPSHOT = [
    ("code-puppy", CodePuppyAgent),
    ("pack-leader", PackLeaderAgent),
    ("turbo-executor", TurboExecutorAgent),
    ("security-auditor", SecurityAuditorAgent),
    ("code-reviewer", CodeQualityReviewerAgent),
    ("terminal-qa", TerminalQAAgent),
    ("python-programmer", PythonProgrammerAgent),
    ("qa-expert", QAExpertAgent),
]


@pytest.fixture
def deterministic_agent_env(monkeypatch):
    """Set up a deterministic environment for snapshot tests.

    Mocks dynamic content that would otherwise vary between runs:
    - Dates (normalized to placeholder)
    - Working directory paths
    - Platform-specific strings
    - Environment variables that affect prompts
    """
    # Mock config values that might vary
    monkeypatch.setenv("PUPPY_NAME", "Code-Puppy")
    monkeypatch.setenv("OWNER_NAME", "Adam")

    # Ensure consistent model environment (no user plugins/skills interference)
    monkeypatch.setenv("PUPPY_NO_USER_PLUGINS", "1")
    monkeypatch.delenv("PUPPY_SESSION_LOGGER_ENABLED", raising=False)

    # Mock get_platform_info to return deterministic values
    def mock_platform_info(self):
        return (
            "- Platform: <PLATFORM>\n"
            "- Shell: SHELL=/bin/zsh\n"
            "- Current date: <DATE>\n"
            "- Working directory: <CWD>\n"
            "- The user is working inside a git repository\n"
        )

    # Mock get_identity to return a deterministic ID
    def mock_identity(self):
        return f"{self.name}-<AGENT_ID>"

    with patch(
        "code_puppy.agents.agent_prompt_mixin.AgentPromptMixin.get_platform_info",
        mock_platform_info,
    ):
        with patch(
            "code_puppy.agents.agent_prompt_mixin.AgentPromptMixin.get_identity",
            mock_identity,
        ):
            yield


@pytest.mark.parametrize("agent_name,agent_class", AGENTS_TO_SNAPSHOT)
def test_agent_system_prompt_snapshot(
    agent_name: str,
    agent_class: type,
    update_snapshots: bool,
    deterministic_agent_env,
):
    """Verify the composed system prompt matches its saved snapshot.

    This test ensures that changes to agent system prompts are intentional.
    If a snapshot mismatch occurs:
    1. Check the diff to understand what changed
    2. If intentional: run with --update-snapshots and commit the updated .md file
    3. If unintentional: investigate the source of the drift
    """
    # Instantiate the agent directly
    agent = agent_class()

    # Get the full composed system prompt (base + platform + identity)
    actual_prompt = agent.get_full_system_prompt()

    # Normalize dynamic content for deterministic comparison
    normalized_prompt = normalize_for_snapshot(actual_prompt)

    # Compare against or update the snapshot
    assert_snapshot(agent_name, normalized_prompt, update=update_snapshots)


@pytest.mark.parametrize("agent_name,agent_class", AGENTS_TO_SNAPSHOT)
def test_agent_base_prompt_no_platform(
    agent_name: str,
    agent_class: type,
    update_snapshots: bool,
):
    """Verify the base system prompt (without platform context) is stable.

    This catches drift in the agent's core instructions without the variable
    platform and identity sections that get_full_system_prompt() adds.
    """
    agent = agent_class()

    # Get just the base system prompt
    base_prompt = agent.get_system_prompt()

    # Still normalize in case base prompt has dynamic content
    normalized = normalize_for_snapshot(base_prompt)

    # Store in separate subdirectory for base prompts
    from tests.agents._snapshot_helpers import SNAPSHOT_DIR
    base_snapshot_dir = SNAPSHOT_DIR.parent / "base_prompts"
    base_snapshot_dir.mkdir(parents=True, exist_ok=True)

    from tests.agents._snapshot_helpers import assert_snapshot as _assert

    # Monkeypatch the snapshot dir for this test
    original_dir = SNAPSHOT_DIR
    try:
        import tests.agents._snapshot_helpers as helpers

        helpers.SNAPSHOT_DIR = base_snapshot_dir
        _assert(f"{agent_name}", normalized, update=update_snapshots)
    finally:
        helpers.SNAPSHOT_DIR = original_dir
