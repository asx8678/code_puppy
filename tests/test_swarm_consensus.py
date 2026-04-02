"""Integration tests for Agent Swarm Consensus.

Tests the core components of the swarm consensus system:
- Approach configuration and selection
- Confidence scoring algorithms
- Consensus detection logic
- Orchestrator initialization and execution
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# =============================================================================
# Approach Configuration Tests
# =============================================================================


class TestApproachConfiguration:
    """Test approach configuration and selection."""

    def test_approach_config_creation(self):
        """Test creating approach configurations."""
        from code_puppy.plugins.swarm_consensus.models import ApproachConfig

        approach = ApproachConfig(
            name="thorough",
            system_prompt_modifier="Be thorough and check edge cases.",
            temperature_override=0.3,
            description="Deep analysis approach",
        )

        assert approach.name == "thorough"
        assert approach.temperature_override == 0.3
        assert "edge cases" in approach.system_prompt_modifier

    def test_get_approaches_for_task(self):
        """Test getting approaches for different task types."""
        from code_puppy.plugins.swarm_consensus.approaches import get_approaches_for_task

        # Test default task type
        approaches = get_approaches_for_task("default", 3)
        assert len(approaches) == 3
        assert all(hasattr(a, "name") for a in approaches)

        # Test security task type
        security_approaches = get_approaches_for_task("security_review", 2)
        assert len(security_approaches) == 2

    def test_approach_selection_by_task_type(self):
        """Test that task types get appropriate approaches."""
        from code_puppy.plugins.swarm_consensus.approaches import get_approaches_for_task

        # Security tasks should include security approach
        security = get_approaches_for_task("security_review", 5)
        approach_names = [a.name for a in security]
        assert "security" in approach_names or "critical" in approach_names

        # Refactor tasks should include pragmatic/creative
        refactor = get_approaches_for_task("refactor", 5)
        refactor_names = [a.name for a in refactor]
        assert any(name in refactor_names for name in ["pragmatic", "creative", "thorough"])


# =============================================================================
# Confidence Scoring Tests
# =============================================================================


class TestConfidenceScoring:
    """Test confidence scoring algorithms."""

    def test_calculate_confidence_basic(self):
        """Test basic confidence calculation."""
        from code_puppy.plugins.swarm_consensus.models import AgentResult
        from code_puppy.plugins.swarm_consensus.scoring import calculate_confidence

        result = AgentResult(
            agent_name="test_agent",
            response_text="This is a valid response with some content.",
            execution_time_ms=1000.0,
        )

        confidence = calculate_confidence(result)
        assert 0.0 <= confidence <= 1.0

    def test_confidence_with_error_response(self):
        """Test confidence for error responses."""
        from code_puppy.plugins.swarm_consensus.models import AgentResult
        from code_puppy.plugins.swarm_consensus.scoring import calculate_confidence

        result = AgentResult(
            agent_name="error_agent",
            response_text="Error: Something went wrong",
            execution_time_ms=100.0,
        )

        confidence = calculate_confidence(result)
        assert confidence < 0.5  # Errors should have low confidence

    def test_confidence_empty_response(self):
        """Test confidence for empty responses."""
        from code_puppy.plugins.swarm_consensus.models import AgentResult
        from code_puppy.plugins.swarm_consensus.scoring import calculate_confidence

        result = AgentResult(
            agent_name="empty_agent",
            response_text="",
            execution_time_ms=500.0,
        )

        confidence = calculate_confidence(result)
        assert confidence < 0.3  # Empty responses should have very low confidence

    def test_score_by_consistency(self):
        """Test consistency scoring across multiple results."""
        from code_puppy.plugins.swarm_consensus.models import AgentResult
        from code_puppy.plugins.swarm_consensus.scoring import score_by_consistency

        results = [
            AgentResult(agent_name="a1", response_text="Use async/await pattern", confidence_score=0.8),
            AgentResult(agent_name="a2", response_text="Use async await pattern", confidence_score=0.7),
            AgentResult(agent_name="a3", response_text="Completely different approach", confidence_score=0.6),
        ]

        scores = score_by_consistency(results)

        assert len(scores) == 3
        assert all(0.0 <= s <= 1.0 for s in scores.values())

        # Similar responses should have higher consistency
        assert scores["a1"] > scores["a3"] or scores["a2"] > scores["a3"]


# =============================================================================
# Consensus Detection Tests
# =============================================================================


class TestConsensusDetection:
    """Test consensus detection logic."""

    def test_detect_consensus_with_agreement(self):
        """Test detecting consensus when agents agree."""
        from code_puppy.plugins.swarm_consensus.consensus import detect_consensus
        from code_puppy.plugins.swarm_consensus.models import AgentResult

        # Use very similar responses to ensure consensus detection
        results = [
            AgentResult(
                agent_name="a1",
                response_text="Use dependency injection pattern for better testability",
                confidence_score=0.9,
            ),
            AgentResult(
                agent_name="a2",
                response_text="Use dependency injection pattern for better testability",
                confidence_score=0.85,
            ),
            AgentResult(
                agent_name="a3",
                response_text="Use dependency injection pattern for better testability",
                confidence_score=0.8,
            ),
        ]

        consensus_reached, final_answer = detect_consensus(results, threshold=0.7)

        # All identical responses should reach consensus
        assert consensus_reached is True
        assert final_answer is not None
        assert len(final_answer) > 0

    def test_detect_consensus_no_agreement(self):
        """Test detecting consensus when agents disagree."""
        from code_puppy.plugins.swarm_consensus.consensus import detect_consensus
        from code_puppy.plugins.swarm_consensus.models import AgentResult

        results = [
            AgentResult(
                agent_name="a1",
                response_text="Use factory pattern",
                confidence_score=0.7,
            ),
            AgentResult(
                agent_name="a2",
                response_text="Use singleton pattern",
                confidence_score=0.6,
            ),
            AgentResult(
                agent_name="a3",
                response_text="Use observer pattern",
                confidence_score=0.5,
            ),
        ]

        consensus_reached, final_answer = detect_consensus(results, threshold=0.8)

        # With high threshold and disagreement, no consensus
        assert consensus_reached is False

    def test_synthesize_results(self):
        """Test synthesizing results when no consensus."""
        from code_puppy.plugins.swarm_consensus.consensus import synthesize_results
        from code_puppy.plugins.swarm_consensus.models import AgentResult

        results = [
            AgentResult(
                agent_name="a1",
                response_text="Point A is important",
                confidence_score=0.9,
                approach_used="thorough",
            ),
            AgentResult(
                agent_name="a2",
                response_text="Point B is critical",
                confidence_score=0.8,
                approach_used="creative",
            ),
            AgentResult(
                agent_name="a3",
                response_text="Point C should be considered",
                confidence_score=0.7,
                approach_used="pragmatic",
            ),
        ]

        synthesized = synthesize_results(results)

        assert isinstance(synthesized, str)
        assert len(synthesized) > 0
        # Synthesis should incorporate high-confidence points


# =============================================================================
# Swarm Config Tests
# =============================================================================


class TestSwarmConfig:
    """Test SwarmConfig validation."""

    def test_valid_config(self):
        """Test creating valid configuration."""
        from code_puppy.plugins.swarm_consensus.models import SwarmConfig

        config = SwarmConfig(
            swarm_size=5,
            consensus_threshold=0.75,
            timeout_seconds=120,
        )

        assert config.swarm_size == 5
        assert config.consensus_threshold == 0.75
        assert config.timeout_seconds == 120

    def test_invalid_swarm_size(self):
        """Test validation of swarm size."""
        from code_puppy.plugins.swarm_consensus.models import SwarmConfig

        with pytest.raises(ValueError, match="at least 2"):
            SwarmConfig(swarm_size=1)

    def test_invalid_threshold(self):
        """Test validation of consensus threshold."""
        from code_puppy.plugins.swarm_consensus.models import SwarmConfig

        with pytest.raises(ValueError, match="0.0 and 1.0"):
            SwarmConfig(consensus_threshold=1.5)

    def test_invalid_timeout(self):
        """Test validation of timeout."""
        from code_puppy.plugins.swarm_consensus.models import SwarmConfig

        with pytest.raises(ValueError, match="at least 10 seconds"):
            SwarmConfig(timeout_seconds=5)


# =============================================================================
# Orchestrator Tests
# =============================================================================


class TestOrchestrator:
    """Test SwarmOrchestrator functionality."""

    def test_orchestrator_init(self):
        """Test orchestrator initialization."""
        from code_puppy.plugins.swarm_consensus.models import SwarmConfig
        from code_puppy.plugins.swarm_consensus.orchestrator import SwarmOrchestrator

        config = SwarmConfig(swarm_size=3)
        orchestrator = SwarmOrchestrator(config)

        assert orchestrator.config.swarm_size == 3
        assert orchestrator._agents == []

    def test_orchestrator_get_status(self):
        """Test getting orchestrator status."""
        from code_puppy.plugins.swarm_consensus.models import SwarmConfig
        from code_puppy.plugins.swarm_consensus.orchestrator import SwarmOrchestrator

        config = SwarmConfig(swarm_size=4)
        orchestrator = SwarmOrchestrator(config)

        status = orchestrator.get_status()

        assert status["config"]["swarm_size"] == 4
        assert status["active_agents"] == 0
        assert status["parallelism_limit"] == 2

    @pytest.mark.asyncio
    async def test_execute_swarm_empty_config(self):
        """Test swarm execution with minimal config."""
        from code_puppy.plugins.swarm_consensus.models import SwarmConfig
        from code_puppy.plugins.swarm_consensus.orchestrator import SwarmOrchestrator

        config = SwarmConfig(swarm_size=2)
        orchestrator = SwarmOrchestrator(config)

        # Mock the agent spawning to avoid dependencies
        with patch.object(orchestrator, "_spawn_agents") as mock_spawn:
            mock_spawn.return_value = []

            result = await orchestrator.execute_swarm(
                task_prompt="Test task",
                task_type="default",
            )

            assert result.consensus_reached is False
            assert "No agents" in result.final_answer

    @pytest.mark.asyncio
    async def test_orchestrator_with_mock_agents(self):
        """Test orchestrator with mocked agents."""
        from code_puppy.plugins.swarm_consensus.models import SwarmConfig
        from code_puppy.plugins.swarm_consensus.orchestrator import SwarmOrchestrator

        config = SwarmConfig(swarm_size=2)
        orchestrator = SwarmOrchestrator(config)

        # Create mock agents
        mock_agent1 = MagicMock()
        mock_agent1.name = "agent_1"
        mock_agent1.run_with_mcp = AsyncMock(return_value="Response from agent 1")

        mock_agent2 = MagicMock()
        mock_agent2.name = "agent_2"
        mock_agent2.run_with_mcp = AsyncMock(return_value="Response from agent 2")

        with patch.object(orchestrator, "_spawn_agents", return_value=[mock_agent1, mock_agent2]):
            with patch.object(orchestrator, "_cleanup_agents"):
                result = await orchestrator.execute_swarm(
                    task_prompt="Test task",
                    task_type="default",
                )

                assert len(result.individual_results) == 2
                assert result.execution_stats is not None
                assert any("Response from agent" in r.response_text for r in result.individual_results)


# =============================================================================
# Swarm Result Tests
# =============================================================================


class TestSwarmResult:
    """Test SwarmResult helper methods."""

    def test_get_best_result(self):
        """Test getting the best result by confidence."""
        from code_puppy.plugins.swarm_consensus.models import AgentResult, SwarmResult

        result = SwarmResult(
            individual_results=[
                AgentResult(agent_name="a1", response_text="Low", confidence_score=0.5),
                AgentResult(agent_name="a2", response_text="High", confidence_score=0.9),
                AgentResult(agent_name="a3", response_text="Medium", confidence_score=0.7),
            ],
            confidence_scores={"a1": 0.5, "a2": 0.9, "a3": 0.7},
        )

        best = result.get_best_result()
        assert best is not None
        assert best.agent_name == "a2"
        assert best.confidence_score == 0.9

    def test_get_average_confidence(self):
        """Test calculating average confidence."""
        from code_puppy.plugins.swarm_consensus.models import AgentResult, SwarmResult

        result = SwarmResult(
            individual_results=[
                AgentResult(agent_name="a1", response_text="A", confidence_score=0.5),
                AgentResult(agent_name="a2", response_text="B", confidence_score=0.9),
            ],
            confidence_scores={"a1": 0.5, "a2": 0.9},
        )

        avg = result.get_average_confidence()
        assert avg == 0.7

    def test_get_agreement_ratio(self):
        """Test calculating agreement ratio."""
        from code_puppy.plugins.swarm_consensus.models import AgentResult, SwarmResult

        result = SwarmResult(
            individual_results=[
                AgentResult(agent_name="a1", response_text="Same answer"),
                AgentResult(agent_name="a2", response_text="Same answer"),
                AgentResult(agent_name="a3", response_text="Different"),
            ],
            final_answer="Same answer",
            confidence_scores={},
        )

        ratio = result.get_agreement_ratio()
        assert 0.5 <= ratio <= 0.75  # 2/3 or 1/3 depending on similarity check

    def test_empty_result_helpers(self):
        """Test helper methods with empty results."""
        from code_puppy.plugins.swarm_consensus.models import SwarmResult

        result = SwarmResult()

        assert result.get_best_result() is None
        assert result.get_average_confidence() == 0.0
        assert result.get_agreement_ratio() == 0.0


# =============================================================================
# Command Handler Tests
# =============================================================================


class TestCommandHandlers:
    """Test command handler functions."""

    def test_handle_swarm_status(self):
        """Test swarm status command."""
        from code_puppy.command_line.swarm_commands import _show_swarm_status

        # Should not raise and should return True
        result = _show_swarm_status()
        assert result is True

    def test_handle_swarm_enable_disable(self):
        """Test enable/disable commands."""
        from code_puppy.command_line.swarm_commands import _disable_swarm, _enable_swarm
        from code_puppy.plugins.swarm_consensus.config import get_swarm_enabled, set_swarm_enabled

        # Reset to known state first
        set_swarm_enabled(False)

        # Test enable
        result = _enable_swarm()
        assert result is True
        # Config returns string values
        assert get_swarm_enabled() in (True, "true", "True")

        # Test disable
        result = _disable_swarm()
        assert result is True
        assert get_swarm_enabled() in (False, "false", "False")

    def test_handle_swarm_help(self):
        """Test help command."""
        from code_puppy.command_line.swarm_commands import _show_swarm_help

        result = _show_swarm_help()
        assert result is True

    def test_get_swarm_help_entries(self):
        """Test help entries generation."""
        from code_puppy.command_line.swarm_commands import get_swarm_help_entries

        entries = get_swarm_help_entries()
        assert isinstance(entries, list)
        assert len(entries) >= 4

        # Each entry should be a tuple of (command, description)
        for entry in entries:
            assert isinstance(entry, tuple)
            assert len(entry) == 2
            assert isinstance(entry[0], str)
            assert isinstance(entry[1], str)


# =============================================================================
# TUI Screen Tests
# =============================================================================


class TestSwarmScreen:
    """Test SwarmScreen TUI component."""

    def test_screen_init(self):
        """Test screen initialization."""
        from code_puppy.tui.screens.swarm_screen import SwarmScreen

        screen = SwarmScreen(task_prompt="Test prompt", task_type="refactor")

        assert screen._task_prompt == "Test prompt"
        assert screen._task_type == "refactor"
        assert screen.swarm_result is None
        assert screen.is_running is False

    def test_status_emoji_helper(self):
        """Test status emoji helper."""
        from code_puppy.tui.screens.swarm_screen import _get_status_emoji

        assert _get_status_emoji(0.9, False) == "🔥"
        assert _get_status_emoji(0.7, False) == "✅"
        assert _get_status_emoji(0.5, False) == "⚠️"
        assert _get_status_emoji(0.3, False) == "❌"
        assert _get_status_emoji(0.5, True) == "🎯"

    def test_confidence_bar_formatting(self):
        """Test confidence bar formatting."""
        from code_puppy.tui.screens.swarm_screen import _format_confidence_bar

        bar = _format_confidence_bar(0.75, width=10)
        assert "75%" in bar
        assert "█" in bar
        assert "░" in bar


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for the full swarm system."""

    @pytest.mark.asyncio
    async def test_end_to_end_swarm_execution(self):
        """Test complete swarm execution flow."""
        from code_puppy.plugins.swarm_consensus.models import SwarmConfig
        from code_puppy.plugins.swarm_consensus.orchestrator import SwarmOrchestrator

        config = SwarmConfig(
            swarm_size=2,
            consensus_threshold=0.6,
            timeout_seconds=30,
        )

        orchestrator = SwarmOrchestrator(config)

        # Mock the entire execution to avoid external dependencies
        with patch.object(orchestrator, "_spawn_agents") as mock_spawn:
            mock_agent = MagicMock()
            mock_agent.name = "test_agent"
            mock_agent.run_with_mcp = AsyncMock(return_value="Test response")
            mock_spawn.return_value = [mock_agent]

            with patch.object(orchestrator, "_cleanup_agents"):
                result = await orchestrator.execute_swarm(
                    task_prompt="Refactor this code",
                    task_type="refactor",
                )

                # Verify result structure
                assert hasattr(result, "consensus_reached")
                assert hasattr(result, "final_answer")
                assert hasattr(result, "individual_results")
                assert hasattr(result, "execution_stats")

    def test_config_persistence(self):
        """Test that config changes persist."""
        from code_puppy.plugins.swarm_consensus.config import (
            get_swarm_enabled,
            set_swarm_enabled,
        )

        # Save original state
        original = get_swarm_enabled()

        try:
            # Toggle and verify (config may return strings)
            set_swarm_enabled(True)
            enabled_val = get_swarm_enabled()
            assert enabled_val in (True, "true", "True", 1, "1", "yes")

            set_swarm_enabled(False)
            disabled_val = get_swarm_enabled()
            assert disabled_val in (False, "false", "False", 0, "0", "no", "")
        finally:
            # Restore original
            set_swarm_enabled(original)


# =============================================================================
# P1 Regression Tests
# =============================================================================


class TestP1Regressions:
    """Regression tests for P1 swarm bug fixes.

    These tests guard against re-introduction of critical bugs:
    - code_puppy-064: asyncio.run() crash in running event loops
    - code_puppy-krl: deepcopied agents sharing UUIDs
    - code_puppy-36g: spawned agents mutating shared state
    - _agent_identity not returning _swarm_identity
    - _run_agent calling run() instead of run_with_mcp()
    """

    def test_swarm_command_uses_sync_path(self):
        """Regression test for code_puppy-064/6fn: /swarm must use the sync 
        handle_swarm_custom_command path."""
        # Import the swarm plugin to trigger callback registration
        import code_puppy.plugins.swarm_consensus.register_callbacks  # noqa: F401

        from code_puppy.callbacks import get_callbacks
        from code_puppy.command_line.swarm_commands import handle_swarm_custom_command

        custom_cmd_callbacks = get_callbacks("custom_command")
        assert handle_swarm_custom_command in custom_cmd_callbacks, \
            "handle_swarm_custom_command must be registered as a custom_command callback"

    def test_spawn_agents_have_unique_ids(self):
        """Regression test for code_puppy-krl: deepcopied agents must get fresh UUIDs."""
        import uuid
        from unittest.mock import MagicMock, patch

        from code_puppy.plugins.swarm_consensus.models import ApproachConfig, SwarmConfig
        from code_puppy.plugins.swarm_consensus.orchestrator import SwarmOrchestrator

        config = SwarmConfig(swarm_size=3)
        orchestrator = SwarmOrchestrator(config)

        approaches = [
            ApproachConfig(
                name="thorough",
                system_prompt_modifier="Be thorough",
                temperature_override=0.3,
            ),
            ApproachConfig(
                name="creative",
                system_prompt_modifier="Be creative",
                temperature_override=0.9,
            ),
        ]

        with patch(
            "code_puppy.agents.agent_manager.load_agent"
        ) as mock_load, patch(
            "code_puppy.agents.agent_manager.get_current_agent_name",
            return_value="code-puppy",
        ):
            mock_agent = MagicMock()
            mock_agent.id = str(uuid.uuid7())
            mock_agent.name = "test-agent"
            mock_agent.system_prompt = "original prompt"
            mock_agent.temperature = 0.5
            mock_load.return_value = mock_agent

            agents = orchestrator._spawn_agents(approaches)

            # All agents should have unique IDs
            ids = [a.id for a in agents]
            assert len(set(ids)) == len(ids), f"Agent IDs must be unique, got: {ids}"

    def test_spawn_agents_dont_mutate_original(self):
        """Regression test for code_puppy-36g: spawned agents must not share state
        with the original loaded agent."""
        from unittest.mock import MagicMock, patch

        from code_puppy.plugins.swarm_consensus.models import ApproachConfig, SwarmConfig
        from code_puppy.plugins.swarm_consensus.orchestrator import SwarmOrchestrator

        config = SwarmConfig(swarm_size=2)
        orchestrator = SwarmOrchestrator(config)

        approaches = [
            ApproachConfig(
                name="thorough",
                system_prompt_modifier="Be thorough",
                temperature_override=0.3,
            ),
        ]

        with patch(
            "code_puppy.agents.agent_manager.load_agent"
        ) as mock_load, patch(
            "code_puppy.agents.agent_manager.get_current_agent_name",
            return_value="code-puppy",
        ):
            mock_agent = MagicMock()
            mock_agent.name = "original-agent"
            mock_agent.system_prompt = "original prompt"
            mock_agent.temperature = 0.5
            mock_load.return_value = mock_agent

            orchestrator._spawn_agents(approaches)

            # The original agent's attributes should NOT have been changed
            assert mock_agent.system_prompt == "original prompt", (
                "Original agent's system_prompt was mutated!"
            )
            assert mock_agent.temperature == 0.5, (
                "Original agent's temperature was mutated!"
            )

    def test_agent_identity_uses_swarm_identity(self):
        """Regression test: _agent_identity returns _swarm_identity when set."""
        from unittest.mock import MagicMock

        from code_puppy.plugins.swarm_consensus.orchestrator import SwarmOrchestrator

        agent = MagicMock()
        agent.name = "base-name"
        agent._swarm_identity = "swarm_agent_0_thorough"

        assert SwarmOrchestrator._agent_identity(agent) == "swarm_agent_0_thorough"

        # Without _swarm_identity, falls back to name
        agent3 = MagicMock(spec=[])
        agent3.name = "fallback-name"
        assert SwarmOrchestrator._agent_identity(agent3) == "fallback-name"

    @pytest.mark.asyncio
    async def test_run_agent_calls_run_with_mcp(self):
        """Regression test: _run_agent must call run_with_mcp, not run."""
        from unittest.mock import AsyncMock, MagicMock

        from code_puppy.plugins.swarm_consensus.models import SwarmConfig
        from code_puppy.plugins.swarm_consensus.orchestrator import SwarmOrchestrator

        config = SwarmConfig(swarm_size=2)
        orchestrator = SwarmOrchestrator(config)

        agent = MagicMock()
        agent.name = "test-agent"
        agent.run_with_mcp = AsyncMock(return_value="test response")
        agent._swarm_approach = "thorough"
        agent._swarm_identity = "swarm_agent_0"

        result = await orchestrator._run_agent(agent, "test prompt", {}, timeout=30)

        agent.run_with_mcp.assert_called_once()
        assert "test response" in result.response_text


# =============================================================================
# Score By Structure Tests
# =============================================================================


class TestScoreByStructure:
    """Tests for score_by_structure regex fix (code_puppy-38q)."""

    def test_numbered_list_detected(self):
        from code_puppy.plugins.swarm_consensus.scoring import score_by_structure
        score = score_by_structure("1. First item\n2. Second item\n3. Third item")
        assert score > 0, "Numbered list should increase structure score"

    def test_bulleted_list_detected(self):
        from code_puppy.plugins.swarm_consensus.scoring import score_by_structure
        score = score_by_structure("- First bullet\n- Second bullet\n* Third bullet")
        assert score > 0, "Bulleted list should increase structure score"

    def test_multi_digit_numbers_detected(self):
        from code_puppy.plugins.swarm_consensus.scoring import score_by_structure
        score = score_by_structure("10. Tenth item\n11. Eleventh item\n12. Twelfth item")
        assert score > 0, "Multi-digit numbered list should increase structure score"

    def test_plain_text_low_structure(self):
        from code_puppy.plugins.swarm_consensus.scoring import score_by_structure
        score_plain = score_by_structure("This is just plain text without any structure.")
        score_list = score_by_structure("1. First\n2. Second\n3. Third")
        assert score_list > score_plain, "Structured text should score higher than plain"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
