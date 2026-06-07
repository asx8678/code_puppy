"""Tests for Explore agent tool set and prompts.

Covers:
  1. Explore discovery via agent_manager
  2. Explore read-only tool set (no write tools, no invoke_agent)
  3. Explore system prompt content (read-only, cheap, file discovery, repo walking, context gathering)
  4. Explore identity properties

Self-contained: no project fixtures/conftest required.
"""

from __future__ import annotations

from code_puppy.agents.agent_explore import ExploreAgent
from code_puppy.agents.agent_manager import get_available_agents, refresh_agents

# ---------------------------------------------------------------------------
# Explore Agent
# ---------------------------------------------------------------------------


def test_explore_is_discovered() -> None:
    """Explore shows up in the agent registry after refresh."""
    refresh_agents()
    agents = get_available_agents()
    assert "explore" in agents, f"Expected 'explore' in {sorted(agents.keys())}"


def test_explore_toolset_is_readonly() -> None:
    """Explore exposes exactly the intended read-only / exploration tools."""
    agent = ExploreAgent()
    tools = agent.get_available_tools()

    expected = [
        "list_files",
        "read_file",
        "grep",
        "agent_run_shell_command",
        "list_or_search_skills",
    ]
    assert tools == expected, (
        f"Tool list mismatch.\n  got:      {tools}\n  expected: {expected}"
    )

    forbidden = {
        "create_file",
        "replace_in_file",
        "delete_snippet",
        "delete_file",
        "invoke_agent",
    }
    present_forbidden = forbidden & set(tools)
    assert not present_forbidden, (
        f"Read-only contract violated; leaked tools: {present_forbidden}"
    )


def test_explore_prompt_substantial_and_readonly() -> None:
    """System prompt is substantial and mentions the intended explore contract."""
    agent = ExploreAgent()
    prompt = agent.get_system_prompt()

    assert len(prompt) > 500, f"Prompt too short: {len(prompt)} chars"

    lower = prompt.lower()
    assert "read-only" in lower, "Prompt should mention read-only"
    assert "cheap" in lower, "Prompt should mention cheap"
    assert "discover" in lower and "file" in lower, (
        "Prompt should mention file discovery"
    )
    assert "walk" in lower and "repo" in lower, "Prompt should mention repo walking"
    assert "context" in lower, "Prompt should mention context gathering"


def test_explore_identity() -> None:
    """Name and display_name match expected values."""
    agent = ExploreAgent()
    assert agent.name == "explore"
    assert agent.display_name == "Explore 🔍"


if __name__ == "__main__":
    import sys

    tests = [
        test_explore_is_discovered,
        test_explore_toolset_is_readonly,
        test_explore_prompt_substantial_and_readonly,
        test_explore_identity,
    ]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except Exception as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            failures += 1
    if failures:
        print(f"\n{failures}/{len(tests)} tests failed")
        sys.exit(1)
    else:
        print(f"\nAll {len(tests)} tests passed")
