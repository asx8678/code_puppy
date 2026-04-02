"""Tests for the Consensus Planner's council-based model selection.

Tests the council consensus integration in the Consensus Planner Agent:
- Leader and advisor model selection
- Council consensus invocation
- Decision-to-plan mapping
- Model comparison and selection
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from dataclasses import dataclass, field

from code_puppy.plugins.consensus_planner.council_consensus import (
    AdvisorInput,
    CouncilDecision,
)
from code_puppy.agents.consensus_planner import ConsensusPlannerAgent, Plan


# =============================================================================
# Council Model Selection Tests
# =============================================================================


class TestConsensusModelSelection:
    """Test leader and advisor model selection."""

    def test_get_consensus_models_returns_leader_plus_advisors(self):
        """Test _get_consensus_models returns leader + advisors tuple."""
        agent = ConsensusPlannerAgent()

        with patch(
            "code_puppy.plugins.consensus_planner.council_consensus._get_leader_model"
        ) as mock_leader:
            with patch(
                "code_puppy.plugins.consensus_planner.council_consensus._get_advisor_models"
            ) as mock_advisors:
                mock_leader.return_value = "claude-sonnet-4"
                mock_advisors.return_value = ["gpt-4.1", "gemini-2.5-pro"]

                leader, advisors = agent._get_consensus_models()

                assert leader == "claude-sonnet-4"
                assert advisors == ["gpt-4.1", "gemini-2.5-pro"]
                mock_leader.assert_called_once()
                mock_advisors.assert_called_once_with(exclude_leader="claude-sonnet-4")


# =============================================================================
# Council Consensus Invocation Tests
# =============================================================================


class TestCouncilConsensusInvocation:
    """Test council consensus calling patterns."""

    @pytest.mark.asyncio
    async def test_create_plan_with_consensus_calls_run_council_consensus(self):
        """Test _create_plan_with_consensus calls run_council_consensus with skip_safeguards=True."""
        agent = ConsensusPlannerAgent()

        mock_decision = CouncilDecision(
            leader_model="claude-sonnet-4",
            decision="Use async/await pattern",
            synthesis_rationale="Best for I/O bound tasks",
            confidence=0.85,
            advisor_inputs=[],
        )

        with patch(
            "code_puppy.plugins.consensus_planner.council_consensus.run_council_consensus"
        ) as mock_run:
            mock_run.return_value = mock_decision

            plan = await agent._create_plan_with_consensus(
                "Design caching system",
                {"complexity": "high"},
            )

            mock_run.assert_called_once_with("Design caching system", skip_safeguards=True)
            assert plan.used_consensus is True
            assert plan.confidence == 0.85

    @pytest.mark.asyncio
    async def test_plan_with_consensus_force_flag_skips_complexity_check(self):
        """Test that force_consensus=True bypasses should_use_consensus check."""
        agent = ConsensusPlannerAgent()

        mock_decision = CouncilDecision(
            leader_model="claude-sonnet-4",
            decision="Forced consensus plan",
            synthesis_rationale="User requested consensus",
            confidence=0.85,
            advisor_inputs=[],
        )

        with patch(
            "code_puppy.plugins.consensus_planner.council_consensus.run_council_consensus"
        ) as mock_run:
            mock_run.return_value = mock_decision

            plan = await agent.plan_with_consensus("simple task", force_consensus=True)

            # Should use consensus even though "simple task" has 0.00 complexity
            mock_run.assert_called_once()
            assert plan.used_consensus is True


# =============================================================================
# Council Decision Parsing Tests
# =============================================================================


class TestCouncilDecisionParsing:
    """Test parsing CouncilDecision into Plan."""

    def test_parse_council_decision_to_plan_mapping(self):
        """Test _parse_council_decision_to_plan correctly maps CouncilDecision fields."""
        agent = ConsensusPlannerAgent()

        advisor_inputs = [
            AdvisorInput(
                model_name="gpt-4.1",
                response="Use Redis for caching",
                confidence=0.9,
                execution_time_ms=1000.0,
            ),
            AdvisorInput(
                model_name="gemini-2.5-pro",
                response="Consider Memcached instead",
                confidence=0.6,  # Low confidence - becomes alternative
                execution_time_ms=1200.0,
            ),
        ]

        council_decision = CouncilDecision(
            leader_model="claude-sonnet-4",
            decision="Implement Redis caching with fallback",
            synthesis_rationale="Redis offers best balance of features",
            confidence=0.88,
            advisor_inputs=advisor_inputs,
            dissenting_opinions=["Memcached has lower overhead"],
        )

        plan = agent._parse_council_decision_to_plan("Design caching system", council_decision)

        assert plan.recommended_model == "claude-sonnet-4"
        assert plan.confidence == 0.88
        assert plan.used_consensus is True
        assert plan.risks == ["Memcached has lower overhead"]
        assert len(plan.alternative_approaches) == 1
        assert "gemini-2.5-pro" in plan.alternative_approaches[0]


# =============================================================================
# Model Selection Tests
# =============================================================================


class TestModelSelection:
    """Test model selection and comparison functionality."""

    @pytest.mark.asyncio
    async def test_select_best_model_uses_pinned_models(self):
        """Test select_best_model uses pinned models from _get_consensus_models."""
        agent = ConsensusPlannerAgent()

        with patch.object(agent, "_get_consensus_models") as mock_get_models:
            with patch.object(agent, "compare_model_approaches") as mock_compare:
                mock_get_models.return_value = ("claude-sonnet-4", ["gpt-4.1"])

                mock_result = MagicMock()
                mock_result.confidence = 0.9
                mock_result.model_name = "claude-sonnet-4"
                mock_compare.return_value = [mock_result]

                best_model = await agent.select_best_model("Refactor auth system")

                mock_get_models.assert_called_once()
                mock_compare.assert_called_once()
                assert best_model == "claude-sonnet-4"

    @pytest.mark.asyncio
    async def test_compare_model_approaches_defaults_to_pinned_models(self):
        """Test compare_model_approaches uses pinned models when none provided."""
        agent = ConsensusPlannerAgent()

        with patch.object(agent, "_get_consensus_models") as mock_get_models:
            with patch.object(agent, "_run_single_model_comparison") as mock_run:
                mock_get_models.return_value = ("claude-sonnet-4", ["gpt-4.1"])
                mock_run.return_value = MagicMock(
                    model_name="claude-sonnet-4",
                    confidence=0.85,
                )

                results = await agent.compare_model_approaches("Optimize database queries")

                mock_get_models.assert_called_once()
                # Should use leader + advisors as default models
                assert mock_run.call_count >= 1


# =============================================================================
# Configuration Display Tests
# =============================================================================


class TestConfigurationDisplay:
    """Test configuration display functionality."""

    def test_show_consensus_config_shows_leader_and_advisors(self):
        """Test _show_consensus_config displays leader and advisor models."""
        from code_puppy.plugins.consensus_planner.commands import _show_consensus_config

        with patch(
            "code_puppy.plugins.consensus_planner.council_consensus._get_leader_model"
        ) as mock_leader:
            with patch(
                "code_puppy.plugins.consensus_planner.council_consensus._get_advisor_models"
            ) as mock_advisors:
                with patch("code_puppy.plugins.consensus_planner.commands.emit_info") as mock_emit:
                    mock_leader.return_value = "claude-sonnet-4"
                    mock_advisors.return_value = ["gpt-4.1", "gemini-2.5-pro"]

                    _show_consensus_config()

                    # Check that emit_info was called with leader info
                    calls = mock_emit.call_args_list
                    call_texts = [str(c) for c in calls]
                    all_output = " ".join(call_texts)

                    assert any("Leader" in str(c) for c in call_texts)
                    assert any("Advisor" in str(c) for c in call_texts)
                    assert "claude-sonnet-4" in all_output


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_get_consensus_models_handles_empty_advisors(self):
        """Test _get_consensus_models handles empty advisor list."""
        agent = ConsensusPlannerAgent()

        with patch(
            "code_puppy.plugins.consensus_planner.council_consensus._get_leader_model"
        ) as mock_leader:
            with patch(
                "code_puppy.plugins.consensus_planner.council_consensus._get_advisor_models"
            ) as mock_advisors:
                mock_leader.return_value = "claude-sonnet-4"
                mock_advisors.return_value = []

                leader, advisors = agent._get_consensus_models()

                assert leader == "claude-sonnet-4"
                assert advisors == []

    @pytest.mark.asyncio
    async def test_compare_model_approaches_handles_no_models(self):
        """Test compare_model_approaches handles empty model list gracefully."""
        agent = ConsensusPlannerAgent()

        results = await agent.compare_model_approaches("Simple task", models=[])

        assert results == []

    @pytest.mark.asyncio
    async def test_create_plan_single_model_timeout_returns_fallback(self):
        """Test that _create_plan_single_model returns fallback plan on timeout."""
        agent = ConsensusPlannerAgent()

        # Mock _create_simple_agent to return an agent whose run() hangs
        mock_agent_instance = AsyncMock()
        mock_agent_instance.run = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch(
            "code_puppy.plugins.consensus_planner.council_consensus._create_simple_agent",
            new_callable=AsyncMock,
            return_value=mock_agent_instance,
        ):
            plan = await agent._create_plan_single_model("test task")

            assert plan.used_consensus is False
            assert "Fallback" in plan.phases[0]["description"] or "timeout" in plan.phases[0]["description"].lower()


# =============================================================================
# Agent Tool Integration Tests
# =============================================================================


class TestPlanningAgentIntegration:
    """Test Planning Agent has consensus tools and prompt awareness."""

    def test_planning_agent_has_consensus_tools(self):
        """Test PlanningAgent includes consensus tools in available tools."""
        from code_puppy.agents.agent_planning import PlanningAgent

        agent = PlanningAgent()
        tools = agent.get_available_tools()

        assert "get_second_opinion" in tools
        assert "should_i_get_second_opinion" in tools

    def test_planning_agent_prompt_mentions_consensus(self):
        """Test PlanningAgent system prompt includes consensus guidance."""
        from code_puppy.agents.agent_planning import PlanningAgent

        agent = PlanningAgent()
        prompt = agent.get_system_prompt()

        assert "consensus" in prompt.lower()
        assert "consensus-planner" in prompt
        assert "should_i_get_second_opinion" in prompt
        assert "get_second_opinion" in prompt


class TestCodePuppyAgentIntegration:
    """Test Code-Puppy Agent has consensus tools and prompt awareness."""

    def test_code_puppy_has_consensus_tools(self):
        """Test CodePuppyAgent includes consensus tools in available tools."""
        from code_puppy.agents.agent_code_puppy import CodePuppyAgent

        agent = CodePuppyAgent()
        tools = agent.get_available_tools()

        assert "get_second_opinion" in tools
        assert "check_response_confidence" in tools

    def test_code_puppy_prompt_mentions_consensus(self):
        """Test CodePuppyAgent system prompt includes consensus guidance."""
        from code_puppy.agents.agent_code_puppy import CodePuppyAgent

        agent = CodePuppyAgent()
        prompt = agent.get_system_prompt()

        assert "consensus" in prompt.lower()
        assert "check_response_confidence" in prompt
        assert "get_second_opinion" in prompt


# =============================================================================
# Auto-Spawn Suggestion Tests
# =============================================================================


class TestAutoSpawnSuggestion:
    """Test auto-spawn hook emits visible suggestions."""

    @pytest.mark.asyncio
    async def test_auto_spawn_emits_suggestion_on_uncertainty(self):
        """Test _on_agent_run_end emits user-visible suggestion when consensus is needed."""
        from code_puppy.plugins.consensus_planner.register_callbacks import (
            _on_agent_run_end,
        )
        from code_puppy.plugins.consensus_planner.auto_spawn import IssueDetectionResult

        mock_detection = IssueDetectionResult(
            needs_consensus=True,
            confidence_score=0.3,
            trigger_type="uncertainty",
            matched_patterns=["not sure", "unclear"],
            reason="Detected uncertainty markers",
        )

        with patch(
            "code_puppy.plugins.consensus_planner.auto_spawn.get_consensus_auto_spawn_enabled",
            return_value=True,
        ):
            with patch(
                "code_puppy.plugins.consensus_planner.auto_spawn.detect_issue_need_consensus",
                return_value=mock_detection,
            ):
                with patch(
                    "code_puppy.plugins.consensus_planner.register_callbacks.emit_info"
                ) as mock_emit:
                    await _on_agent_run_end(
                        agent_name="code-puppy",
                        model_name="claude-sonnet-4",
                        response_text="I'm not sure about the best approach here, it's unclear",
                        metadata={"task": "Design auth system"},
                    )

                    mock_emit.assert_called_once()
                    call_text = mock_emit.call_args[0][0]
                    assert "uncertainty" in call_text
                    assert "/consensus_plan" in call_text

    @pytest.mark.asyncio
    async def test_auto_spawn_silent_when_confident(self):
        """Test _on_agent_run_end does NOT emit when agent is confident."""
        from code_puppy.plugins.consensus_planner.register_callbacks import (
            _on_agent_run_end,
        )
        from code_puppy.plugins.consensus_planner.auto_spawn import IssueDetectionResult

        mock_detection = IssueDetectionResult(
            needs_consensus=False,
            confidence_score=0.9,
            trigger_type="none",
            matched_patterns=[],
            reason="No uncertainty detected",
        )

        with patch(
            "code_puppy.plugins.consensus_planner.auto_spawn.get_consensus_auto_spawn_enabled",
            return_value=True,
        ):
            with patch(
                "code_puppy.plugins.consensus_planner.auto_spawn.detect_issue_need_consensus",
                return_value=mock_detection,
            ):
                with patch(
                    "code_puppy.plugins.consensus_planner.register_callbacks.emit_info"
                ) as mock_emit:
                    await _on_agent_run_end(
                        agent_name="code-puppy",
                        model_name="claude-sonnet-4",
                        response_text="Here's the definitive solution with high confidence",
                    )

                    mock_emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_spawn_skips_consensus_planner_agent(self):
        """Test _on_agent_run_end skips monitoring the consensus planner itself."""
        from code_puppy.plugins.consensus_planner.register_callbacks import (
            _on_agent_run_end,
        )

        with patch(
            "code_puppy.plugins.consensus_planner.auto_spawn.detect_issue_need_consensus"
        ) as mock_detect:
            await _on_agent_run_end(
                agent_name="consensus-planner",
                model_name="claude-sonnet-4",
                response_text="I'm not sure about this approach",
            )

            # Should NOT have called detect — skipped entirely
            mock_detect.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_spawn_calls_plan_with_force_consensus(self):
        """Test that auto_spawn_consensus_planner passes models through to council."""
        from code_puppy.plugins.consensus_planner.auto_spawn import auto_spawn_consensus_planner
        from code_puppy.plugins.consensus_planner.council_consensus import (
            AdvisorInput,
            CouncilDecision,
        )

        # Create a mock CouncilDecision instead of Plan
        mock_decision = CouncilDecision(
            decision="Test decision",
            synthesis_rationale="Test rationale",
            confidence=0.8,
            leader_model="claude-sonnet-4",
            advisor_inputs=[
                AdvisorInput(
                    model_name="claude-sonnet-4",
                    response="Test response",
                    confidence=0.8,
                    execution_time_ms=100.0,
                ),
            ],
        )

        with patch(
            "code_puppy.plugins.consensus_planner.council_consensus.run_council_consensus",
            new_callable=AsyncMock,
            return_value=mock_decision,
        ) as mock_council:
            # Test without models override
            result = await auto_spawn_consensus_planner("test task", "testing")

            mock_council.assert_called_once()
            call_kwargs = mock_council.call_args.kwargs
            assert call_kwargs.get("skip_safeguards") is True
            assert call_kwargs.get("advisor_models_override") is None
            assert result["success"] is True
            assert result["plan"]["used_consensus"] is True
            assert result["plan"]["confidence"] == 0.8

    @pytest.mark.asyncio
    async def test_auto_spawn_passes_models_override(self):
        """Test that auto_spawn_consensus_planner passes models through to council."""
        from code_puppy.plugins.consensus_planner.auto_spawn import auto_spawn_consensus_planner
        from code_puppy.plugins.consensus_planner.council_consensus import (
            AdvisorInput,
            CouncilDecision,
        )

        mock_decision = CouncilDecision(
            decision="Test decision",
            synthesis_rationale="Test rationale",
            confidence=0.9,
            leader_model="custom-model",
            advisor_inputs=[
                AdvisorInput(
                    model_name="custom-model",
                    response="Test response",
                    confidence=0.9,
                    execution_time_ms=150.0,
                ),
            ],
        )

        with patch(
            "code_puppy.plugins.consensus_planner.council_consensus.run_council_consensus",
            new_callable=AsyncMock,
            return_value=mock_decision,
        ) as mock_council:
            models = ["model1", "model2"]
            result = await auto_spawn_consensus_planner("test task", "testing", models=models)

            call_kwargs = mock_council.call_args.kwargs
            assert call_kwargs.get("advisor_models_override") == models
            assert result["success"] is True


# =============================================================================
# Model Creation & Execution Tests
# =============================================================================


class TestModelCreation:
    """Test that model creation uses correct pydantic-ai patterns."""

    @pytest.mark.asyncio
    async def test_create_simple_agent_uses_correct_pattern(self):
        """Test _create_simple_agent creates proper pydantic-ai Agent."""
        from code_puppy.plugins.consensus_planner.council_consensus import (
            _create_simple_agent,
        )

        with patch("code_puppy.plugins.consensus_planner.council_consensus.ModelFactory") as mock_factory:
            with patch("code_puppy.plugins.consensus_planner.council_consensus.make_model_settings") as mock_settings:
                with patch("pydantic_ai.Agent") as mock_agent_class:
                    mock_factory.load_config.return_value = {"claude-sonnet-4": {"type": "anthropic"}}
                    mock_factory.get_model.return_value = MagicMock()
                    mock_settings.return_value = MagicMock()

                    await _create_simple_agent("claude-sonnet-4", "Be helpful")

                    mock_factory.load_config.assert_called_once()
                    mock_factory.get_model.assert_called_once()
                    mock_agent_class.assert_called_once()
                    # Verify Agent was created with output_type=str
                    call_kwargs = mock_agent_class.call_args
                    assert call_kwargs.kwargs.get("output_type") == str


# =============================================================================
# Confidence Scoring Tests
# =============================================================================


class TestConfidenceScoring:
    """Test improved confidence scoring with structured parsing."""

    def test_structured_confidence_percentage(self):
        """Test parsing CONFIDENCE: 85% format."""
        from code_puppy.plugins.consensus_planner.council_helpers import (
            estimate_confidence,
        )

        assert estimate_confidence("CONFIDENCE: 85%") == 0.85
        assert estimate_confidence("CONFIDENCE: 100%") == 1.0
        assert estimate_confidence("CONFIDENCE: 0%") == 0.0
        assert estimate_confidence("CONFIDENCE: 42%") == 0.42

    def test_structured_confidence_decimal(self):
        """Test parsing CONFIDENCE: 0.85 format."""
        from code_puppy.plugins.consensus_planner.council_helpers import (
            estimate_confidence,
        )

        assert estimate_confidence("CONFIDENCE: 0.85") == 0.85
        assert estimate_confidence("CONFIDENCE: 0.5") == 0.5

    def test_structured_confidence_case_insensitive(self):
        """Test structured parsing is case-insensitive."""
        from code_puppy.plugins.consensus_planner.council_helpers import (
            estimate_confidence,
        )

        assert estimate_confidence("confidence: 75%") == 0.75
        assert estimate_confidence("Confidence: 90%") == 0.9

    def test_keyword_fallback_high(self):
        """Test keyword fallback for high confidence."""
        from code_puppy.plugins.consensus_planner.council_helpers import (
            estimate_confidence,
        )

        assert estimate_confidence("I have high confidence in this approach") == 0.9
        assert estimate_confidence("I am very confident about this") == 0.9

    def test_keyword_fallback_medium(self):
        """Test keyword fallback for medium confidence."""
        from code_puppy.plugins.consensus_planner.council_helpers import (
            estimate_confidence,
        )

        assert estimate_confidence("I have medium confidence here") == 0.7

    def test_keyword_fallback_low(self):
        """Test keyword fallback for low confidence."""
        from code_puppy.plugins.consensus_planner.council_helpers import (
            estimate_confidence,
        )

        assert estimate_confidence("I have low confidence in this") == 0.4

    def test_uncertainty_markers(self):
        """Test uncertainty markers reduce confidence."""
        from code_puppy.plugins.consensus_planner.council_helpers import (
            estimate_confidence,
        )

        assert estimate_confidence("I'm not sure about this approach") == 0.5
        assert estimate_confidence("This might be the right way") == 0.5

    def test_default_confidence(self):
        """Test default confidence when no markers found."""
        from code_puppy.plugins.consensus_planner.council_helpers import (
            estimate_confidence,
        )

        assert estimate_confidence("Use Redis for caching") == 0.7

    def test_structured_takes_priority_over_keywords(self):
        """Test that structured format takes priority over keyword matching."""
        from code_puppy.plugins.consensus_planner.council_helpers import (
            estimate_confidence,
        )

        # Has both "low confidence" keyword AND structured 90%
        result = estimate_confidence("low confidence mention but CONFIDENCE: 90%")
        assert result == 0.9  # Structured wins


# =============================================================================
# Agreement Detection Tests
# =============================================================================


class TestAgreementDetection:
    """Test advisor agreement ratio calculation."""

    def test_identical_responses_high_agreement(self):
        """Test identical advisor responses produce high agreement."""
        from code_puppy.plugins.consensus_planner.council_helpers import (
            calculate_agreement_ratio,
        )
        from code_puppy.plugins.consensus_planner.council_consensus import (
            AdvisorInput,
        )

        inputs = [
            AdvisorInput(model_name="a", response="Use Redis for caching", confidence=0.9, execution_time_ms=100),
            AdvisorInput(model_name="b", response="Use Redis for caching", confidence=0.8, execution_time_ms=100),
        ]

        ratio = calculate_agreement_ratio(inputs)
        assert ratio >= 0.9  # Near-identical responses

    def test_divergent_responses_low_agreement(self):
        """Test completely different responses produce low agreement."""
        from code_puppy.plugins.consensus_planner.council_helpers import (
            calculate_agreement_ratio,
        )
        from code_puppy.plugins.consensus_planner.council_consensus import (
            AdvisorInput,
        )

        inputs = [
            AdvisorInput(model_name="a", response="Use Redis for distributed caching layer", confidence=0.9, execution_time_ms=100),
            AdvisorInput(model_name="b", response="Implement observer pattern with event bus architecture", confidence=0.8, execution_time_ms=100),
            AdvisorInput(model_name="c", response="Database migration strategy for PostgreSQL upgrade", confidence=0.7, execution_time_ms=100),
        ]

        ratio = calculate_agreement_ratio(inputs)
        assert ratio < 0.5  # Very different topics

    def test_single_advisor_full_agreement(self):
        """Test single advisor trivially has full agreement."""
        from code_puppy.plugins.consensus_planner.council_helpers import (
            calculate_agreement_ratio,
        )
        from code_puppy.plugins.consensus_planner.council_consensus import (
            AdvisorInput,
        )

        inputs = [
            AdvisorInput(model_name="a", response="Use Redis", confidence=0.9, execution_time_ms=100),
        ]

        assert calculate_agreement_ratio(inputs) == 1.0

    def test_empty_advisors(self):
        """Test empty advisor list."""
        from code_puppy.plugins.consensus_planner.council_helpers import (
            calculate_agreement_ratio,
        )

        assert calculate_agreement_ratio([]) == 1.0

    def test_agreement_ratio_in_council_decision(self):
        """Test agreement_ratio field exists on CouncilDecision."""
        from code_puppy.plugins.consensus_planner.council_consensus import (
            CouncilDecision,
        )

        decision = CouncilDecision(
            leader_model="claude-sonnet-4",
            decision="Use Redis",
            synthesis_rationale="All agree",
            confidence=0.9,
            advisor_inputs=[],
            agreement_ratio=0.85,
        )

        assert decision.agreement_ratio == 0.85
        assert "85%" in decision.to_markdown()


# =============================================================================
# Tool Registration Pattern Tests
# =============================================================================


class TestToolRegistrationPattern:
    """Test that consensus tools follow the correct TOOL_REGISTRY pattern.
    
    TOOL_REGISTRY expects registration functions: def register_X(agent) that
    use @agent.tool to register the actual handler. NOT the async handler itself.
    """

    def test_register_consensus_tools_returns_registration_functions(self):
        """Test _register_consensus_tools returns proper registration functions, not coroutine functions."""
        import inspect
        from code_puppy.plugins.consensus_planner.register_callbacks import (
            _register_consensus_tools,
        )

        tools = _register_consensus_tools()

        assert len(tools) == 8, f"Expected 8 tools, got {len(tools)}"

        expected_names = {
            "plan_with_consensus",
            "select_model_for_task",
            "compare_model_approaches",
            "get_second_opinion",
            "auto_spawn_consensus",
            "check_response_confidence",
            "run_council_consensus",
            "should_i_get_second_opinion",
        }

        for tool_def in tools:
            assert "name" in tool_def, f"Tool def missing 'name': {tool_def}"
            assert "register_func" in tool_def, f"Tool def missing 'register_func': {tool_def}"
            assert callable(tool_def["register_func"]), (
                f"register_func for '{tool_def['name']}' is not callable"
            )
            # THIS IS THE KEY CHECK: register_func must NOT be a coroutine function.
            # If it is, calling register_func(agent) creates an unawaited coroutine.
            assert not inspect.iscoroutinefunction(tool_def["register_func"]), (
                f"register_func for '{tool_def['name']}' is a coroutine function! "
                f"It should be a plain function that uses @agent.tool to register the handler."
            )

        actual_names = {t["name"] for t in tools}
        assert actual_names == expected_names, (
            f"Tool name mismatch. Missing: {expected_names - actual_names}, "
            f"Extra: {actual_names - expected_names}"
        )


# =============================================================================
# Council Consensus Flow Tests
# =============================================================================


class TestCouncilConsensusFlow:
    """Test the council consensus execution flow including timeouts and progress."""

    @pytest.mark.asyncio
    async def test_gather_advisor_inputs_individual_timeout(self):
        """Test that individual advisor timeouts are handled gracefully."""
        from code_puppy.plugins.consensus_planner.council_consensus import (
            _gather_advisor_inputs,
        )

        # Mock _create_simple_agent to return an agent that times out
        async def slow_agent_run(prompt):
            await asyncio.sleep(100)  # Will be cancelled by timeout

        with patch(
            "code_puppy.plugins.consensus_planner.council_consensus._create_simple_agent"
        ) as mock_create:
            mock_agent = AsyncMock()
            mock_agent.run = slow_agent_run
            mock_create.return_value = mock_agent

            # Short timeout should result in empty results
            results = await _gather_advisor_inputs(
                "test task", ["model1", "model2"], timeout=1.0
            )

            assert len(results) == 0  # All should have timed out

    @pytest.mark.asyncio
    async def test_gather_advisor_inputs_partial_results(self):
        """Test that partial results are returned when some advisors fail."""
        from code_puppy.plugins.consensus_planner.council_consensus import (
            _gather_advisor_inputs,
        )

        call_count = 0

        async def mixed_agent_factory(model_name, instructions=""):
            """Factory that creates agents - first succeeds, second times out."""
            nonlocal call_count
            call_count += 1
            mock_agent = MagicMock()
            if "fast" in model_name:
                result = MagicMock()
                result.output = "ANALYSIS: Good approach\nCONFIDENCE: 80%\nCONCERNS: None"
                mock_agent.run = AsyncMock(return_value=result)
            else:
                async def slow_run(prompt):
                    await asyncio.sleep(100)
                mock_agent.run = slow_run
            return mock_agent

        with patch(
            "code_puppy.plugins.consensus_planner.council_consensus._create_simple_agent",
            side_effect=mixed_agent_factory,
        ):
            results = await _gather_advisor_inputs(
                "test task", ["fast-model", "slow-model"], timeout=5.0
            )

            # Should have at least the fast model's result
            assert len(results) >= 1
            assert results[0].model_name == "fast-model"

    @pytest.mark.asyncio
    async def test_leader_synthesize_timeout(self):
        """Test that leader synthesis timeout is handled gracefully."""
        from code_puppy.plugins.consensus_planner.council_consensus import (
            AdvisorInput,
            _leader_synthesize,
        )

        advisors = [
            AdvisorInput(
                model_name="test-model",
                response="ANALYSIS: Test\nCONFIDENCE: 80%\nCONCERNS: None",
                confidence=0.8,
                execution_time_ms=100.0,
            )
        ]

        async def slow_run(prompt):
            await asyncio.sleep(100)

        with patch(
            "code_puppy.plugins.consensus_planner.council_consensus._create_simple_agent"
        ) as mock_create:
            mock_agent = MagicMock()
            mock_agent.run = slow_run
            mock_create.return_value = mock_agent

            result = await _leader_synthesize(
                "test task", "leader-model", advisors, timeout=1.0
            )

            assert result.confidence == 0.0
            assert "timed out" in result.decision.lower()
            assert result.leader_model == "leader-model"

    @pytest.mark.asyncio
    async def test_run_council_no_advisors(self):
        """Test run_council_consensus with no advisor models."""
        from code_puppy.plugins.consensus_planner.council_consensus import (
            run_council_consensus,
        )

        with patch(
            "code_puppy.plugins.consensus_planner.council_consensus._get_leader_model",
            return_value="test-leader",
        ), patch(
            "code_puppy.plugins.consensus_planner.council_consensus._get_advisor_models",
            return_value=[],
        ), patch(
            "code_puppy.plugins.consensus_planner.council_consensus._create_simple_agent"
        ) as mock_create:
            # Leader should still be called even with no advisors
            result_mock = MagicMock()
            result_mock.output = "FINAL DECISION: Just do it\nSYNTHESIS RATIONALE: No advisors to consult\nCONFIDENCE: 70%"
            mock_agent = MagicMock()
            mock_agent.run = AsyncMock(return_value=result_mock)
            mock_create.return_value = mock_agent

            result = await run_council_consensus(
                "test task", skip_safeguards=True, timeout=30.0
            )

            assert result.leader_model == "test-leader"
            assert len(result.advisor_inputs) == 0

    @pytest.mark.asyncio
    async def test_timeout_budgets_are_calculated_correctly(self):
        """Test that timeout budgets respect the total timeout."""
        from code_puppy.plugins.consensus_planner.council_consensus import (
            run_council_consensus,
        )

        captured_advisor_timeout = None
        captured_leader_timeout = None

        original_gather = None
        original_leader = None

        async def capture_gather(task, models, timeout=100.0):
            nonlocal captured_advisor_timeout
            captured_advisor_timeout = timeout
            return []  # Return empty so leader gets called

        async def capture_leader(task, model, inputs, timeout=80.0):
            nonlocal captured_leader_timeout
            captured_leader_timeout = timeout
            from code_puppy.plugins.consensus_planner.council_consensus import CouncilDecision
            return CouncilDecision(
                leader_model=model,
                decision="test",
                synthesis_rationale="test",
                confidence=0.5,
                advisor_inputs=[],
            )

        with patch(
            "code_puppy.plugins.consensus_planner.council_consensus._get_leader_model",
            return_value="test-leader",
        ), patch(
            "code_puppy.plugins.consensus_planner.council_consensus._get_advisor_models",
            return_value=["m1"],
        ), patch(
            "code_puppy.plugins.consensus_planner.council_consensus._gather_advisor_inputs",
            side_effect=capture_gather,
        ), patch(
            "code_puppy.plugins.consensus_planner.council_consensus._leader_synthesize",
            side_effect=capture_leader,
        ):
            await run_council_consensus("test", skip_safeguards=True, timeout=100.0)

            # 60% of 100 = 60 for advisors
            assert captured_advisor_timeout == pytest.approx(60.0)
            # 35% of 100 = 35 for leader
            assert captured_leader_timeout == pytest.approx(35.0)
            # Total is 95, leaving 5% overhead
