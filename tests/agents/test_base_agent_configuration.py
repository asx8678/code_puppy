from unittest.mock import patch

import pytest

from code_puppy.agents.agent_code_puppy import CodePuppyAgent


class TestBaseAgentConfiguration:
    @pytest.fixture
    def agent(self):
        return CodePuppyAgent()


class TestEstimateContextOverheadMemoization:
    """fix #1a: _estimate_context_overhead is memoized on
    (model_name, hash(system_prompt)) so the history processor doesn't
    re-resolve the prompt + re-run prepare_prompt_for_model every request."""

    @pytest.fixture
    def agent(self):
        return CodePuppyAgent()

    def test_repeated_calls_return_same_value(self, agent):
        first = agent._estimate_context_overhead()
        second = agent._estimate_context_overhead()
        assert first == second
        assert first > 0

    def test_cache_hit_skips_prepare_prompt_for_model(self, agent):
        # Prime the cache.
        agent._estimate_context_overhead()
        # A subsequent call with an unchanged key must NOT re-run the model-prep
        # pipeline (that's the whole point of the memo).
        with patch("code_puppy.model_utils.prepare_prompt_for_model") as mock_prepare:
            value = agent._estimate_context_overhead()
        mock_prepare.assert_not_called()
        assert value > 0

    def test_model_switch_invalidates_cache(self, agent):
        agent._estimate_context_overhead()
        cached_key = agent._ctx_overhead_cache[0]
        # Force a different effective model name → key changes → recompute.
        with patch.object(agent, "get_model_name", return_value="some-other-model"):
            agent._estimate_context_overhead()
            new_key = agent._ctx_overhead_cache[0]
        assert new_key != cached_key
        assert new_key[0] == "some-other-model"


class TestCodePuppyDynamicPrompt:
    """Test that the Code-Puppy system prompt no longer references the retired reasoning tool."""

    @pytest.fixture
    def agent(self):
        return CodePuppyAgent()

    def test_prompt_mentions_reasoning_without_tool_name(self, agent):
        """Prompt should still encourage thinking, just not via the retired tool."""
        prompt = agent.get_system_prompt()
        assert "think through your approach" in prompt
        assert "share_your_reasoning" not in prompt

    def test_prompt_loop_rule_uses_reasoning_language(self, agent):
        """The loop rule should refer to reasoning, not the removed tool name."""
        prompt = agent.get_system_prompt()
        assert "loop between reasoning, file tools" in prompt
        assert "loop between share_your_reasoning" not in prompt

    def test_non_reasoning_sections_unchanged(self, agent):
        """Core prompt sections are still present after removing the tool."""
        prompt = agent.get_system_prompt()

        for expected in [
            "a code agent helping",
            "replace_in_file",
            "run_shell_command",
            "Zen of Python",
            "MUST use tools",
            "Continue autonomously",
        ]:
            assert expected in prompt, f"Missing prompt section: {expected}"
