"""Regression tests for adversarial planning agent registration.

Tests that the adversarial planning plugin correctly registers its agents
with the shared agent registry, enabling:
- Agents to appear in /agent picker and other listings
- Model pinning for AP agents via config_commands.py
- Description visibility in agent_menu.py and other surfaces
"""

import pytest


class TestAgentRegistration:
    """Test that AP agents are properly registered via callback."""

    def test_get_adversarial_agents_returns_six_agents(self):
        """Test get_adversarial_agents returns all six AP agents."""
        from code_puppy.plugins.adversarial_planning.agents import get_adversarial_agents

        agents = get_adversarial_agents()

        assert len(agents) == 6
        names = [a["name"] for a in agents]
        assert "ap-researcher" in names
        assert "ap-planner-a" in names
        assert "ap-planner-b" in names
        assert "ap-reviewer" in names
        assert "ap-arbiter" in names
        assert "ap-red-team" in names

    def test_get_adversarial_agents_returns_dict_with_name_and_class(self):
        """Test each agent definition has required keys."""
        from code_puppy.plugins.adversarial_planning.agents import get_adversarial_agents
        from code_puppy.agents.base_agent import BaseAgent

        agents = get_adversarial_agents()

        for agent_def in agents:
            assert "name" in agent_def, f"Agent missing name: {agent_def}"
            assert "class" in agent_def, f"Agent missing class: {agent_def}"
            assert isinstance(agent_def["name"], str)
            # Verify it's a BaseAgent subclass
            assert issubclass(agent_def["class"], BaseAgent)

    def test_all_ap_agents_have_role_properties(self):
        """Test all AP agents have ROLE_NAME and ROLE_DESCRIPTION defined."""
        from code_puppy.plugins.adversarial_planning.agents import get_adversarial_agents

        agents = get_adversarial_agents()

        for agent_def in agents:
            agent_class = agent_def["class"]
            assert hasattr(agent_class, "ROLE_NAME")
            assert hasattr(agent_class, "ROLE_DESCRIPTION")
            assert agent_class.ROLE_NAME, f"{agent_class} has empty ROLE_NAME"
            assert agent_class.ROLE_DESCRIPTION, f"{agent_class} has empty ROLE_DESCRIPTION"

    def test_ap_agent_names_match_role_names(self):
        """Test agent.name property matches the registered name."""
        from code_puppy.plugins.adversarial_planning.agents import get_adversarial_agents

        agents = get_adversarial_agents()

        for agent_def in agents:
            agent_instance = agent_def["class"]()
            expected_name = agent_def["name"]
            assert agent_instance.name == expected_name, (
                f"Agent name mismatch: {agent_instance.name} != {expected_name}"
            )


class TestAgentDisplayNames:
    """Test display name formatting for user-friendly rendering."""

    def test_researcher_display_name(self):
        """Test researcher has user-friendly display name."""
        from code_puppy.plugins.adversarial_planning.agents import APResearcherAgent

        agent = APResearcherAgent()
        assert "Researcher" in agent.display_name
        assert "⚔️" in agent.display_name  # Has the AP badge
        assert "-" not in agent.display_name  # No hyphens in display name

    def test_planner_display_names_handle_hyphens(self):
        """Test planner agents render nicely without hyphenated names."""
        from code_puppy.plugins.adversarial_planning.agents import APPlannerAAgent, APPlannerBAgent

        agent_a = APPlannerAAgent()
        agent_b = APPlannerBAgent()

        # Should have space instead of hyphen
        assert "A" in agent_a.display_name
        assert "B" in agent_b.display_name
        assert "Planner-A" not in agent_a.display_name
        assert "Planner-B" not in agent_b.display_name

    def test_reviewer_display_name(self):
        """Test reviewer has user-friendly display name."""
        from code_puppy.plugins.adversarial_planning.agents import APReviewerAgent

        agent = APReviewerAgent()
        assert "Reviewer" in agent.display_name
        assert "⚔️" in agent.display_name

    def test_arbiter_display_name(self):
        """Test arbiter has user-friendly display name."""
        from code_puppy.plugins.adversarial_planning.agents import APArbiterAgent

        agent = APArbiterAgent()
        assert "Arbiter" in agent.display_name
        assert "⚔️" in agent.display_name

    def test_red_team_display_name(self):
        """Test red team has user-friendly display name."""
        from code_puppy.plugins.adversarial_planning.agents import APRedTeamAgent

        agent = APRedTeamAgent()
        assert "Red Team" in agent.display_name
        assert "⚔️" in agent.display_name
        assert "red-team" not in agent.display_name.lower()  # No hyphenated version

    def test_all_agents_have_descriptions(self):
        """Test all AP agents have non-empty descriptions."""
        from code_puppy.plugins.adversarial_planning.agents import get_adversarial_agents

        agents = get_adversarial_agents()

        for agent_def in agents:
            agent_instance = agent_def["class"]()
            assert agent_instance.description, f"{agent_def['name']} has no description"
            assert isinstance(agent_instance.description, str)
            assert len(agent_instance.description) > 10  # Meaningful description


class TestRegisterCallbacks:
    """Test that the register_callbacks module properly registers agents."""

    def test_register_agents_callback_imports_agents(self):
        """Test _register_agents imports and returns agents."""
        from code_puppy.plugins.adversarial_planning.register_callbacks import _register_agents

        result = _register_agents()

        # Should return 6 agents, not empty list
        assert len(result) == 6
        names = [a["name"] for a in result]
        assert "ap-researcher" in names

    def test_register_agents_returns_proper_structure(self):
        """Test _register_agents returns list of dicts with name and class."""
        from code_puppy.plugins.adversarial_planning.register_callbacks import _register_agents
        from code_puppy.agents.base_agent import BaseAgent

        result = _register_agents()

        for agent_def in result:
            assert isinstance(agent_def, dict)
            assert "name" in agent_def
            assert "class" in agent_def
            assert issubclass(agent_def["class"], BaseAgent)


class TestAgentRegistryIntegration:
    """Test that AP agents integrate with the shared agent registry."""

    def test_agents_can_be_instantiated_for_registry(self):
        """Test that agent instances can be created and have required attributes."""
        from code_puppy.plugins.adversarial_planning.agents import get_adversarial_agents

        agents = get_adversarial_agents()

        for agent_def in agents:
            # Simulate what agent_manager._discover_agents does
            agent_class = agent_def["class"]
            agent_instance = agent_class()

            # These are the properties agent_manager reads
            assert agent_instance.name == agent_def["name"]
            assert agent_instance.display_name
            assert agent_instance.description
            assert isinstance(agent_instance.name, str)
            assert isinstance(agent_instance.display_name, str)
            assert isinstance(agent_instance.description, str)

    def test_agent_factory_pattern_works(self):
        """Test that agents work as factories for agent_manager.AgentInfo."""
        from code_puppy.plugins.adversarial_planning.agents import get_adversarial_agents

        agents = get_adversarial_agents()

        for agent_def in agents:
            factory = agent_def["class"]

            # Factory should be callable and return BaseAgent instance
            instance1 = factory()
            instance2 = factory()

            assert instance1.name == instance2.name
            assert instance1.display_name == instance2.display_name
            assert instance1.description == instance2.description


class TestRolePrompts:
    """Test that role prompts are available for all agents."""

    def test_all_roles_have_prompts(self):
        """Test get_role_prompt returns content for all agent roles."""
        from code_puppy.plugins.adversarial_planning.agents import get_role_prompt

        roles = ["researcher", "planner-a", "planner-b", "reviewer", "arbiter", "red-team"]

        for role in roles:
            prompt = get_role_prompt(role)
            assert prompt, f"Role {role} has no prompt"
            assert isinstance(prompt, str)
            assert len(prompt) > 50  # Substantial prompt content

    def test_unknown_role_returns_empty(self):
        """Test get_role_prompt returns empty string for unknown roles."""
        from code_puppy.plugins.adversarial_planning.agents import get_role_prompt

        result = get_role_prompt("unknown-role")
        assert result == ""

    def test_get_role_prompt_does_not_crash(self):
        """Test get_role_prompt handles edge cases gracefully."""
        from code_puppy.plugins.adversarial_planning.agents import get_role_prompt

        # Should not crash on any input
        assert get_role_prompt("") == ""
        assert get_role_prompt("nonexistent") == ""


class TestAgentToolAccess:
    """Test that AP agents have appropriate tool configurations."""

    def test_researcher_has_read_tools(self):
        """Test researcher has read-only exploration tools."""
        from code_puppy.plugins.adversarial_planning.agents import APResearcherAgent

        agent = APResearcherAgent()
        tools = agent.get_available_tools()

        assert "list_files" in tools
        assert "read_file" in tools
        assert "grep" in tools

    def test_planners_have_appropriate_tools(self):
        """Test planners have tools for planning and research."""
        from code_puppy.plugins.adversarial_planning.agents import APPlannerAAgent, APPlannerBAgent

        planner_a = APPlannerAAgent()
        planner_b = APPlannerBAgent()

        # Both should have agent awareness tools
        assert "list_agents" in planner_a.get_available_tools()
        assert "list_agents" in planner_b.get_available_tools()


class TestAgentRegistryIntegrationRealPath:
    """Integration test for AP agent registration via real registry path.

    This verifies that the fixes to callbacks.py (_ensure_plugins_loaded_for_phase
    calling load_plugin_callbacks and being called before count check) work
    correctly, ensuring AP agents appear in get_available_agents() and
    get_agent_descriptions() after fresh discovery.
    """

    @pytest.fixture(autouse=True)
    def reset_agent_registry(self):
        """Reset the agent registry before each test to ensure fresh discovery."""
        import code_puppy.agents.agent_manager as agent_manager

        # Clear registry state
        agent_manager._state.agent_registry.clear()
        agent_manager._state.registry_populated = False
        agent_manager._state.agent_histories.clear()
        agent_manager._state.current_agent = None
        yield
        # Cleanup after test
        agent_manager._state.agent_registry.clear()
        agent_manager._state.registry_populated = False

    def test_ap_agents_in_get_available_agents_real_path(self):
        """Verify AP agents appear in get_available_agents() via real registry path.

        This is the core regression test - it proves that the fix to callbacks.py
        works, ensuring plugins are discovered and loaded before checking callback counts.
        """
        from code_puppy.agents.agent_manager import get_available_agents

        agents = get_available_agents()

        # All 6 AP agents should be present
        ap_agents = {k: v for k, v in agents.items() if k.startswith("ap-")}
        assert len(ap_agents) == 6, f"Expected 6 AP agents, found {len(ap_agents)}: {list(ap_agents.keys())}"

        # Verify each expected agent is present with correct prefix
        expected_agents = [
            "ap-researcher",
            "ap-planner-a",
            "ap-planner-b",
            "ap-reviewer",
            "ap-arbiter",
            "ap-red-team",
        ]
        for agent_name in expected_agents:
            assert agent_name in agents, f"AP agent '{agent_name}' not found in available agents"

    def test_ap_agents_in_get_agent_descriptions_real_path(self):
        """Verify AP agents appear in get_agent_descriptions() via real registry path."""
        from code_puppy.agents.agent_manager import get_agent_descriptions

        descriptions = get_agent_descriptions()

        expected_agents = [
            "ap-researcher",
            "ap-planner-a",
            "ap-planner-b",
            "ap-reviewer",
            "ap-arbiter",
            "ap-red-team",
        ]

        for agent_name in expected_agents:
            assert agent_name in descriptions, f"AP agent '{agent_name}' not found in descriptions"
            assert descriptions[agent_name], f"AP agent '{agent_name}' has empty description"

    def test_register_agents_callback_executes_via_on_register_agents(self):
        """Verify that the register_agents callback executes and returns AP agents.

        This tests that on_register_agents() properly triggers the lazy-loading
        mechanism and returns results from plugin callbacks.
        """
        from code_puppy.callbacks import on_register_agents

        results = on_register_agents()

        # Should have at least one result (from adversarial_planning plugin)
        assert results, "on_register_agents() returned no results - callbacks not executing"

        # Find the AP agents result
        ap_result = None
        for result in results:
            if result and isinstance(result, list):
                for agent_def in result:
                    if isinstance(agent_def, dict) and agent_def.get("name", "").startswith("ap-"):
                        ap_result = result
                        break

        assert ap_result is not None, "No AP agent definitions found in register_agents results"
        assert len(ap_result) == 6, f"Expected 6 AP agent definitions, found {len(ap_result)}"

    def test_callback_registration_via_on_register_agents(self):
        """Verify callbacks are properly registered via on_register_agents public API.

        The narrow AP visibility fix ensures plugins are discovered and loaded
        specifically in on_register_agents(), not in the generic _trigger_callbacks.
        """
        from code_puppy.callbacks import count_callbacks, on_register_agents
        from code_puppy.plugins import _LAZY_PLUGIN_REGISTRY

        # Before: may or may not have callbacks depending on prior test state
        # Call on_register_agents which triggers plugin discovery and loading
        results = on_register_agents()

        # After: should have callbacks registered
        callback_count = count_callbacks("register_agents")
        assert callback_count >= 1, f"Expected at least 1 register_agents callback, found {callback_count}"

        # Verify we got AP agents from the results
        ap_found = False
        for result in results:
            if result and isinstance(result, list):
                for agent_def in result:
                    if isinstance(agent_def, dict) and agent_def.get("name", "").startswith("ap-"):
                        ap_found = True
                        break
        assert ap_found, "No AP agents found in on_register_agents results"

        # Verify adversarial_planning is in the lazy plugin registry
        if "register_agents" in _LAZY_PLUGIN_REGISTRY:
            entries = _LAZY_PLUGIN_REGISTRY["register_agents"]
            ap_entries = [e for e in entries if e[1] == "adversarial_planning"]
            assert ap_entries, "adversarial_planning not found in register_agents phase registry"
