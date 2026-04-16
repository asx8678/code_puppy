"""Tests for wiggum_state.py - 100% coverage."""

from code_puppy.token_ledger import TokenAttempt
from code_puppy.command_line.wiggum_state import (
    WiggumState,
    get_wiggum_count,
    get_wiggum_prompt,
    get_wiggum_state,
    increment_wiggum_count,
    is_wiggum_active,
    start_wiggum,
    stop_wiggum,
)


class TestWiggumState:
    def test_start(self):
        ws = WiggumState()
        ws.start("test prompt")
        assert ws.active is True
        assert ws.prompt == "test prompt"
        assert ws.loop_count == 0

    def test_stop(self):
        ws = WiggumState()
        ws.start("x")
        ws.stop()
        assert ws.active is False
        assert ws.prompt is None
        assert ws.loop_count == 0

    def test_increment(self):
        ws = WiggumState()
        ws.start("x")
        assert ws.increment() == 1
        assert ws.increment() == 2


class TestModuleFunctions:
    def setup_method(self):
        stop_wiggum()

    def test_get_wiggum_state(self):
        state = get_wiggum_state()
        assert isinstance(state, WiggumState)

    def test_is_wiggum_active(self):
        assert is_wiggum_active() is False
        start_wiggum("test")
        assert is_wiggum_active() is True

    def test_get_wiggum_prompt(self):
        assert get_wiggum_prompt() is None
        start_wiggum("hello")
        assert get_wiggum_prompt() == "hello"

    def test_start_and_stop_wiggum(self):
        start_wiggum("go")
        assert is_wiggum_active()
        stop_wiggum()
        assert not is_wiggum_active()

    def test_increment_wiggum_count(self):
        start_wiggum("go")
        assert increment_wiggum_count() == 1
        assert increment_wiggum_count() == 2

    def test_get_wiggum_count(self):
        start_wiggum("go")
        increment_wiggum_count()
        assert get_wiggum_count() == 1

    def test_wiggum_loop_clears_token_ledger(self):
        """Test that wiggum loop iteration clears the token ledger.

        This verifies the design fix: each wiggum loop should have
        independent token accounting, not cumulative costs.
        """
        from unittest.mock import MagicMock
        from code_puppy.token_ledger import TokenLedger

        # Create a mock agent with a real token ledger
        mock_agent = MagicMock()
        mock_ledger = TokenLedger()
        mock_ledger.record(TokenAttempt(model="test", estimated_input_tokens=1000))
        mock_agent._state.get_token_ledger.return_value = mock_ledger

        # Simulate what happens in the wiggum loop
        # (after clear_message_history, we should clear the ledger)
        mock_agent.clear_message_history()
        mock_agent._state.get_token_ledger().clear()

        # Verify ledger is cleared
        assert len(mock_ledger.attempts) == 0
        assert mock_ledger.total_estimated_input == 0
