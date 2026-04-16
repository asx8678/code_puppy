"""Integration tests for wiggum token ledger isolation.

Verifies that each wiggum loop iteration has independent token
accounting (design fix for token accumulation issue).
"""

import pytest
from unittest.mock import MagicMock, patch
from code_puppy.token_ledger import TokenAttempt, TokenLedger
from code_puppy.command_line.wiggum_state import (
    start_wiggum,
    stop_wiggum,
    increment_wiggum_count,
)


class TestWiggumTokenIsolation:
    """Test that wiggum loops don't accumulate token costs."""

    def setup_method(self):
        stop_wiggum()

    def teardown_method(self):
        stop_wiggum()

    def test_token_ledger_clear_method_exists(self):
        """Verify TokenLedger has clear() method."""
        ledger = TokenLedger()
        ledger.record(TokenAttempt(model="test", estimated_input_tokens=1000))
        assert len(ledger.attempts) == 1

        ledger.clear()
        assert len(ledger.attempts) == 0
        assert ledger.total_estimated_input == 0

    def test_wiggum_state_resets_for_independent_accounting(self):
        """Simulate the full wiggum loop showing token isolation."""
        from code_puppy.agents.agent_state import AgentRuntimeState

        # Create agent state with token ledger
        state = AgentRuntimeState()

        # Simulate loop 1: record some tokens
        state.get_token_ledger().record(
            TokenAttempt(
                model="gpt-4o",
                estimated_input_tokens=5000,
                estimated_output_tokens=2000,
            )
        )
        assert state.get_token_ledger().total_estimated_input == 5000

        # Simulate wiggum reset (what interactive_loop.py now does)
        state.clear_history()
        state.get_token_ledger().clear()

        # Verify clean slate for loop 2
        assert state.get_token_ledger().total_estimated_input == 0
        assert state.get_token_ledger().total_estimated_output == 0

        # Simulate loop 2: new tokens
        state.get_token_ledger().record(
            TokenAttempt(
                model="gpt-4o",
                estimated_input_tokens=3000,
                estimated_output_tokens=1000,
            )
        )

        # Should be isolated - only loop 2's tokens
        assert state.get_token_ledger().total_estimated_input == 3000
        assert state.get_token_ledger().total_estimated_output == 1000
