"""Test agent refresh functionality."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import code_puppy.agents.agent_manager as am
from code_puppy.agents import get_available_agents, refresh_agents


def test_discovery_is_cached_between_unchanged_calls():
    """fix #4: read paths must NOT rebuild the registry when nothing changed.

    After an explicit refresh (which forces discovery + records the signature),
    a subsequent read with no filesystem/plugin change must skip the expensive
    ``_discover_agents`` rebuild.
    """
    # Establish a known-good baseline: registry populated, signature recorded.
    refresh_agents()
    assert len(am._AGENT_REGISTRY) > 0

    with patch.object(am, "_discover_agents") as mock_discover:
        get_available_agents()  # signature unchanged → cache hit
        mock_discover.assert_not_called()


def test_refresh_forces_rediscovery():
    """fix #4: refresh_agents() is the explicit cache-buster — it must always
    call _discover_agents even right after a cached read."""
    # Prime the cache so a naive implementation might skip discovery.
    get_available_agents()
    with patch.object(am, "_discover_agents") as mock_discover:
        refresh_agents()
        mock_discover.assert_called_once()


def test_refresh_agents_function():
    """Test that refresh_agents clears the cache and rediscovers agents."""
    # First call to get_available_agents should populate the cache
    agents1 = get_available_agents()

    # Call refresh_agents
    refresh_agents()

    # Second call should work (this tests that the cache was properly cleared)
    agents2 = get_available_agents()

    # Should find the same agents (since we didn't add any new ones)
    assert agents1 == agents2
    assert len(agents1) > 0  # Should have at least the built-in agents


def test_get_available_agents():
    """Test that get_available_agents works correctly."""
    # Call get_available_agents
    agents = get_available_agents()

    # Should find agents
    assert len(agents) > 0


def test_json_agent_discovery_refresh():
    """Test that refresh picks up new JSON agents."""
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch(
            "code_puppy.config.get_user_agents_directory", return_value=temp_dir
        ):
            # Get initial agents (should not include our test agent)
            initial_agents = get_available_agents()
            assert "test-agent" not in initial_agents

            # Create a test JSON agent file
            test_agent_config = {
                "name": "test-agent",
                "description": "A test agent for refresh functionality",
                "system_prompt": "You are a test agent.",
                "tools": ["list_files", "read_file"],
            }

            agent_file = Path(temp_dir) / "test-agent.json"
            import json

            with open(agent_file, "w") as f:
                json.dump(test_agent_config, f)

            # Refresh agents and check if the new agent is discovered
            refreshed_agents = get_available_agents()
            assert "test-agent" in refreshed_agents
            assert (
                refreshed_agents["test-agent"] == "Test-Agent 🤖"
            )  # Default display name format
