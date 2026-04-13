"""Tests for cost_estimator plugin (ADOPT from Agentless).

Covers:
- Heuristic token counting
- Model pricing lookup
- estimate_cost with and without provider tokens
- Session tracking
- /cost and /estimate slash commands (estimate labeling + ledger augmentation)
- _get_ledger_provider_totals helper
"""

from unittest.mock import MagicMock, patch

from code_puppy.plugins.cost_estimator.estimator import (
    TokenEstimate,
    _count_tokens_heuristic,
    _lookup_pricing,
    count_tokens,
    estimate_cost,
    get_session_summary,
    reset_session,
    track_session_tokens,
)


class TestCountTokensHeuristic:
    """Test token counting (now using accurate tiktoken-based counting)."""

    def test_empty_string(self):
        """Empty string → 0 tokens (accurate tiktoken count)."""
        # With accurate counting, empty string is 0 tokens
        # (previously heuristic returned 1 as minimum)
        assert _count_tokens_heuristic("") == 0

    def test_short_text(self):
        """Short text uses accurate tiktoken encoding."""
        result = _count_tokens_heuristic("Hello, world!")
        # tiktoken tokenizes "Hello, world!" as 4 tokens (not len/4 = 3)
        assert result == 4

    def test_long_text(self):
        """Longer text with accurate counting (repeated chars encode efficiently)."""
        text = "a" * 1000
        result = _count_tokens_heuristic(text)
        # tiktoken encodes repeated chars efficiently (~8 chars per token)
        assert result == 125  # 1000 / 8 = 125, not 250 from old heuristic


class TestLookupPricing:
    """Test model pricing lookup."""

    def test_known_model(self):
        """Known model returns correct pricing."""
        pricing = _lookup_pricing("gpt-4o")
        assert pricing == (2.50, 10.00)

    def test_partial_match(self):
        """Partial model name match works."""
        pricing = _lookup_pricing("gpt-4o-2024-08-06")
        assert pricing == (2.50, 10.00)

    def test_unknown_model_default(self):
        """Unknown model returns conservative default."""
        pricing = _lookup_pricing("totally-unknown-model-xyz")
        assert pricing == (5.00, 15.00)


class TestCountTokens:
    """Test the main count_tokens function."""

    def test_returns_positive_integer(self):
        """Always returns a positive integer."""
        result = count_tokens("Hello, world!")
        assert isinstance(result, int)
        assert result > 0

    def test_longer_text_more_tokens(self):
        """Longer text → more tokens."""
        short = count_tokens("Hi")
        long = count_tokens("This is a much longer piece of text with many words")
        assert long > short


class TestEstimateCost:
    """Test cost estimation."""

    def test_string_prompt(self):
        """String prompt → valid estimate."""
        est = estimate_cost("Hello, world!", model="gpt-4o")
        assert isinstance(est, TokenEstimate)
        assert est.input_tokens > 0
        assert est.estimated_cost_usd > 0
        assert est.model == "gpt-4o"
        assert est.method in ("tiktoken", "heuristic")

    def test_message_list_prompt(self):
        """List of message dicts → valid estimate."""
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello!"},
        ]
        est = estimate_cost(messages, model="gpt-4o")
        assert est.input_tokens > 0

    def test_output_tokens_included(self):
        """Expected output tokens affect cost."""
        est_small = estimate_cost("Hi", expected_output_tokens=100)
        est_large = estimate_cost("Hi", expected_output_tokens=10000)
        assert est_large.estimated_cost_usd > est_small.estimated_cost_usd

    def test_different_models_different_costs(self):
        """Different models have different pricing."""
        est_4o = estimate_cost("Test prompt", model="gpt-4o")
        est_mini = estimate_cost("Test prompt", model="gpt-4o-mini")
        assert est_4o.estimated_cost_usd > est_mini.estimated_cost_usd

    def test_token_estimate_str(self):
        """TokenEstimate.__str__ produces readable output."""
        est = TokenEstimate(
            input_tokens=1000,
            output_tokens=500,
            model="gpt-4o",
            estimated_cost_usd=0.0075,
            method="tiktoken",
        )
        s = str(est)
        assert "1,000" in s
        assert "500" in s
        assert "$0.0075" in s

    def test_provider_input_tokens_overrides_heuristic(self):
        """When provider_input_tokens is given, it's used instead of heuristic."""
        est = estimate_cost(
            "Hello, world!",
            model="gpt-4o",
            provider_input_tokens=5000,
            provider_output_tokens=1000,
        )
        assert est.input_tokens == 5000
        assert est.method == "provider"
        assert est.output_tokens == 1000
        assert est.provider_input_tokens == 5000
        assert est.provider_output_tokens == 1000

    def test_provider_input_only(self):
        """Provider input without output uses expected_output_tokens default."""
        est = estimate_cost(
            "Hello, world!",
            model="gpt-4o",
            provider_input_tokens=3000,
        )
        assert est.input_tokens == 3000
        assert est.method == "provider"
        assert est.output_tokens == 1024  # default expected_output_tokens
        assert est.provider_input_tokens == 3000
        assert est.provider_output_tokens is None

    def test_provider_output_only_still_uses_heuristic_input(self):
        """Provider output without input uses heuristic for input count."""
        est = estimate_cost(
            "Hello, world!",
            model="gpt-4o",
            provider_output_tokens=2000,
        )
        # Input should still come from tiktoken or heuristic
        assert est.input_tokens > 0
        assert est.method in ("tiktoken", "heuristic")  # NOT "provider"
        assert est.output_tokens == 2000
        assert est.provider_output_tokens == 2000
        assert est.provider_input_tokens is None

    def test_estimate_cost_backward_compatible(self):
        """estimate_cost works without new keyword params (backward compat)."""
        est = estimate_cost("Test", model="gpt-4o")
        assert est.provider_input_tokens is None
        assert est.provider_output_tokens is None
        assert est.method in ("tiktoken", "heuristic")

    def test_token_estimate_str_with_provider(self):
        """TokenEstimate.__str__ includes provider data when available."""
        est = TokenEstimate(
            input_tokens=1000,
            output_tokens=500,
            model="gpt-4o",
            estimated_cost_usd=0.0075,
            method="provider",
            provider_input_tokens=5123,
            provider_output_tokens=450,
        )
        s = str(est)
        assert "1,000" in s
        assert "5,123" in s
        assert "450" in s
        assert "provider" in s

    def test_estimate_cost_with_provider_uses_provider_pricing(self):
        """Cost calculation uses provider token counts when provided."""
        est_heuristic = estimate_cost("Hello!", model="gpt-4o")
        est_provider = estimate_cost(
            "Hello!",
            model="gpt-4o",
            provider_input_tokens=10000,
            provider_output_tokens=2000,
        )
        # Provider-based estimate should be more expensive because 10k input > heuristic
        assert est_provider.estimated_cost_usd > est_heuristic.estimated_cost_usd


class TestSessionTracking:
    """Test session-level token accumulation."""

    def setup_method(self):
        """Reset session before each test."""
        reset_session()

    def test_track_and_summarize(self):
        """Track tokens → summary includes them."""
        track_session_tokens("gpt-4o", 1000)
        track_session_tokens("gpt-4o", 500)
        track_session_tokens("gpt-4o-mini", 2000)

        summary = get_session_summary()
        assert len(summary["models"]) == 2
        assert summary["total_estimated_cost_usd"] > 0

        gpt4o = next(m for m in summary["models"] if m["model"] == "gpt-4o")
        assert gpt4o["total_tokens"] == 1500

    def test_empty_session(self):
        """Empty session → no models, zero cost."""
        summary = get_session_summary()
        assert summary["models"] == []
        assert summary["total_estimated_cost_usd"] == 0.0

    def test_reset_clears(self):
        """Reset clears accumulated tokens."""
        track_session_tokens("gpt-4o", 1000)
        reset_session()
        summary = get_session_summary()
        assert summary["models"] == []


class TestGetLedgerProviderTotals:
    """Test the _get_ledger_provider_totals helper function."""

    def test_returns_empty_when_no_agent(self):
        """Returns empty dict when get_current_agent raises."""
        from code_puppy.plugins.cost_estimator.register_callbacks import (
            _get_ledger_provider_totals,
        )

        # get_current_agent may raise in test context
        result = _get_ledger_provider_totals()
        assert isinstance(result, dict)

    def test_returns_empty_when_agent_has_state_with_empty_ledger(self):
        """Returns empty dict when ledger has no provider data."""
        from code_puppy.plugins.cost_estimator.register_callbacks import (
            _get_ledger_provider_totals,
        )
        from code_puppy.token_ledger import TokenLedger

        mock_agent = MagicMock()
        mock_state = MagicMock()
        mock_state.get_token_ledger.return_value = TokenLedger()
        mock_agent._state = mock_state

        with patch(
            "code_puppy.agents.agent_manager.get_current_agent",
            return_value=mock_agent,
        ):
            result = _get_ledger_provider_totals()
        # No provider data → empty dict
        assert result == {}

    def test_returns_provider_totals_when_available(self):
        """Returns provider totals when ledger has provider data."""
        from code_puppy.plugins.cost_estimator.register_callbacks import (
            _get_ledger_provider_totals,
        )
        from code_puppy.token_ledger import TokenAttempt, TokenLedger

        ledger = TokenLedger()
        ledger.record(
            TokenAttempt(
                model="gpt-4o",
                estimated_input_tokens=1000,
                provider_input_tokens=950,
                provider_output_tokens=200,
            )
        )

        mock_agent = MagicMock()
        mock_state = MagicMock()
        mock_state.get_token_ledger.return_value = ledger
        mock_agent._state = mock_state

        with patch(
            "code_puppy.agents.agent_manager.get_current_agent",
            return_value=mock_agent,
        ):
            result = _get_ledger_provider_totals()

        assert result["total_provider_input"] == 950
        assert result["total_provider_output"] == 200

    def test_graceful_fallback_on_exception(self):
        """Returns empty dict on any exception (best-effort)."""
        from code_puppy.plugins.cost_estimator.register_callbacks import (
            _get_ledger_provider_totals,
        )

        with patch(
            "code_puppy.agents.agent_manager.get_current_agent",
            side_effect=RuntimeError("no agent"),
        ):
            result = _get_ledger_provider_totals()
        assert result == {}


class TestCostCommandDisplay:
    """Test /cost and /estimate command output includes estimate label."""

    def test_cost_shows_estimate_label(self):
        """The /cost command output includes 'estimate' disclaimer."""
        from code_puppy.plugins.cost_estimator.register_callbacks import (
            _handle_cost_command,
        )
        from code_puppy.plugins.cost_estimator.estimator import (
            reset_session,
            track_session_tokens,
        )

        reset_session()
        track_session_tokens("gpt-4o", 1000)

        result = _handle_cost_command("/cost", "cost")
        assert "estimate" in result.lower()
        assert "actual provider usage may differ" in result.lower()
        reset_session()

    def test_cost_empty_session_no_label_crash(self):
        """Empty session returns early message without crashing."""
        from code_puppy.plugins.cost_estimator.register_callbacks import (
            _handle_cost_command,
        )
        from code_puppy.plugins.cost_estimator.estimator import reset_session

        reset_session()
        result = _handle_cost_command("/cost", "cost")
        assert "No token usage tracked" in result

    def test_estimate_shows_estimate_label(self):
        """The /estimate command output includes 'estimate' disclaimer."""
        from code_puppy.plugins.cost_estimator.register_callbacks import (
            _handle_cost_command,
        )

        result = _handle_cost_command("/estimate Hello world", "estimate")
        assert "estimate" in result.lower()
        assert "actual provider usage may differ" in result.lower()

    def test_estimate_no_text_returns_usage(self):
        """/estimate without text returns usage message."""
        from code_puppy.plugins.cost_estimator.register_callbacks import (
            _handle_cost_command,
        )

        result = _handle_cost_command("/estimate", "estimate")
        assert "Usage" in result

    def test_cost_shows_provider_data_when_available(self):
        """/cost shows provider-reported data when ledger has it."""
        from code_puppy.plugins.cost_estimator.register_callbacks import (
            _handle_cost_command,
        )
        from code_puppy.plugins.cost_estimator.estimator import (
            reset_session,
            track_session_tokens,
        )
        from code_puppy.token_ledger import TokenAttempt, TokenLedger

        reset_session()
        track_session_tokens("gpt-4o", 1000)

        ledger = TokenLedger()
        ledger.record(
            TokenAttempt(
                model="gpt-4o",
                estimated_input_tokens=1000,
                provider_input_tokens=950,
                provider_output_tokens=200,
            )
        )

        mock_agent = MagicMock()
        mock_state = MagicMock()
        mock_state.get_token_ledger.return_value = ledger
        mock_agent._state = mock_state

        with patch(
            "code_puppy.agents.agent_manager.get_current_agent",
            return_value=mock_agent,
        ):
            result = _handle_cost_command("/cost", "cost")

        assert "Provider-reported usage" in result
        assert "950" in result  # provider input
        assert "200" in result  # provider output
        reset_session()

    def test_estimate_with_provider_data(self):
        """/estimate shows provider data when available."""
        from code_puppy.plugins.cost_estimator.register_callbacks import (
            _handle_cost_command,
        )
        from code_puppy.token_ledger import TokenAttempt, TokenLedger

        ledger = TokenLedger()
        ledger.record(
            TokenAttempt(
                model="gpt-4o",
                estimated_input_tokens=1000,
                provider_input_tokens=950,
                provider_output_tokens=200,
            )
        )

        mock_agent = MagicMock()
        mock_state = MagicMock()
        mock_state.get_token_ledger.return_value = ledger
        mock_agent._state = mock_state

        with patch(
            "code_puppy.agents.agent_manager.get_current_agent",
            return_value=mock_agent,
        ):
            result = _handle_cost_command("/estimate Hello world", "estimate")

        assert "950" in result  # provider input
        assert "200" in result  # provider output