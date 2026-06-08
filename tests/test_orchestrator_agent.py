"""Tests for Orchestrator and Planning agent tool sets and prompts.

Covers:
  1. Orchestrator discovery via agent_manager
  2. Orchestrator read-only tool set (no write tools)
  3. Orchestrator system prompt content (delegation/read-only)
  4. Orchestrator identity properties
  5. Planning read-only tool set (no write tools, no shell)
  6. Planning system prompt is plan-only (no fix/execute mode)

Self-contained: no project fixtures/conftest required.
"""

from __future__ import annotations

from code_puppy.agents.agent_manager import get_available_agents, refresh_agents
from code_puppy.agents.agent_orchestrator import OrchestratorAgent
from code_puppy.agents.agent_planning import PlanningAgent

# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def test_orchestrator_is_discovered():
    """Orchestrator shows up in the agent registry after refresh."""
    refresh_agents()
    agents = get_available_agents()
    assert "orchestrator" in agents, (
        f"Expected 'orchestrator' in {sorted(agents.keys())}"
    )


def test_orchestrator_toolset_is_readonly():
    """Orchestrator exposes exactly the intended read-only / coordination tools."""
    agent = OrchestratorAgent()
    tools = agent.get_available_tools()

    expected = [
        "list_files",
        "read_file",
        "grep",
        "agent_run_shell_command",
        "list_agents",
        "invoke_agent",
        "invoke_agent_with_model",
        "list_available_models",
        "ask_user_question",
        "list_or_search_skills",
    ]
    assert tools == expected, (
        f"Tool list mismatch.\n  got:      {tools}\n  expected: {expected}"
    )

    forbidden = {"create_file", "replace_in_file", "delete_snippet", "delete_file"}
    present_forbidden = forbidden & set(tools)
    assert not present_forbidden, (
        f"Write tools leaked into orchestrator: {present_forbidden}"
    )


def test_orchestrator_prompt():
    """System prompt is substantial and mentions delegation and read-only design."""
    agent = OrchestratorAgent()
    prompt = agent.get_system_prompt()

    assert len(prompt) > 500, f"Prompt too short: {len(prompt)} chars"

    lower = prompt.lower()
    assert "delegat" in lower, "Prompt should mention delegation"
    assert "invoke_agent" in lower, "Prompt should reference invoke_agent"
    assert "read-only" in lower or "conductor" in lower, (
        "Prompt should mention read-only or conductor role"
    )
    assert "planning-agent" in lower, (
        "Prompt should route complex work to planning-agent"
    )


def test_orchestrator_identity():
    """Name and display_name match expected values."""
    agent = OrchestratorAgent()
    assert agent.name == "orchestrator"
    assert "Orchestrator" in agent.display_name


def test_orchestrator_delegates_complexity():
    """Prompt forbids self-planning and routes complex work to planning-agent."""
    agent = OrchestratorAgent()
    lower = agent.get_system_prompt().lower()

    assert "planning-agent" in lower, (
        "Prompt must name planning-agent as the destination for complex work"
    )
    assert "complex" in lower, (
        "Prompt should reference complex work / complexity triggers"
    )
    assert (
        "do not plan" in lower
        or "never decompose" in lower
        or "not yours to do" in lower
    ), "Prompt should explicitly forbid the orchestrator from planning itself"


# ---------------------------------------------------------------------------
# Planning Agent — dual-mode
# ---------------------------------------------------------------------------


def test_planning_is_readonly():
    """PlanningAgent exposes a strictly read-only / coordination tool set."""
    agent = PlanningAgent()
    tools = set(agent.get_available_tools())

    forbidden = {
        "create_file",
        "replace_in_file",
        "delete_snippet",
        "delete_file",
        "agent_run_shell_command",
    }
    leaked = forbidden & tools
    assert not leaked, f"Write/execute tools leaked into planning agent: {leaked}"

    # It still needs read + coordination tools to plan and delegate.
    for required in ("list_files", "read_file", "grep", "invoke_agent"):
        assert required in tools, f"Planning agent missing core tool: {required}"


def test_planning_prompt_is_plan_only():
    """System prompt covers plan mode and does NOT advertise a write/execute mode."""
    agent = PlanningAgent()
    prompt = agent.get_system_prompt().lower()

    assert "plan mode" in prompt, "Prompt should mention plan mode"
    assert "fix/execute mode" not in prompt, (
        "Planning agent must not advertise a fix/execute mode"
    )


if __name__ == "__main__":
    import sys

    tests = [
        test_orchestrator_is_discovered,
        test_orchestrator_toolset_is_readonly,
        test_orchestrator_prompt,
        test_orchestrator_identity,
        test_orchestrator_delegates_complexity,
        test_planning_is_readonly,
        test_planning_prompt_is_plan_only,
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
