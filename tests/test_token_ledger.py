"""Tests for the central token ledger."""

import time
from code_puppy.token_ledger import TokenAttempt, TokenLedger


class TestTokenAttempt:
    """Tests for TokenAttempt dataclass."""

    def test_defaults(self):
        attempt = TokenAttempt(model="test-model")
        assert attempt.model == "test-model"
        assert attempt.estimated_input_tokens == 0
        assert attempt.provider_input_tokens is None
        assert attempt.success is True
        assert attempt.retry_number == 0
        assert attempt.timestamp > 0

    def test_full_construction(self):
        attempt = TokenAttempt(
            model="claude-sonnet",
            estimated_input_tokens=5000,
            estimated_output_tokens=1000,
            provider_input_tokens=5123,
            provider_output_tokens=987,
            cache_read_tokens=2000,
            retry_number=0,
            success=True,
            agent_name="code-puppy",
        )
        assert attempt.provider_input_tokens == 5123
        assert attempt.agent_name == "code-puppy"


class TestTokenLedger:
    """Tests for TokenLedger."""

    def test_empty_ledger(self):
        ledger = TokenLedger()
        assert ledger.total_estimated_input == 0
        assert ledger.total_provider_input is None
        assert ledger.drift_ratio is None
        assert ledger.successful_attempts == 0

    def test_record_and_totals(self):
        ledger = TokenLedger()
        ledger.record(TokenAttempt(
            model="test", estimated_input_tokens=1000,
            provider_input_tokens=1100, success=True,
        ))
        ledger.record(TokenAttempt(
            model="test", estimated_input_tokens=2000,
            provider_input_tokens=2200, success=True,
        ))
        assert ledger.total_estimated_input == 3000
        assert ledger.total_provider_input == 3300
        assert ledger.successful_attempts == 2

    def test_drift_ratio(self):
        ledger = TokenLedger()
        ledger.record(TokenAttempt(
            model="test", estimated_input_tokens=1000,
            provider_input_tokens=1000,
        ))
        assert ledger.drift_ratio == 1.0

        ledger.record(TokenAttempt(
            model="test", estimated_input_tokens=1000,
            provider_input_tokens=2000,
        ))
        # Total estimated: 2000, total provider: 3000
        assert ledger.drift_ratio is not None
        assert abs(ledger.drift_ratio - 2000 / 3000) < 0.001

    def test_failed_attempts_and_wasted(self):
        ledger = TokenLedger()
        ledger.record(TokenAttempt(
            model="test", estimated_input_tokens=1000,
            estimated_output_tokens=500, success=False,
            error="context overflow",
        ))
        assert ledger.failed_attempts == 1
        assert ledger.wasted_tokens == 1500

    def test_max_attempts_eviction(self):
        ledger = TokenLedger(_max_attempts=5)
        for i in range(10):
            ledger.record(TokenAttempt(model="test", estimated_input_tokens=i))
        assert len(ledger.attempts) == 5
        # Should keep the most recent
        assert ledger.attempts[0].estimated_input_tokens == 5

    def test_serialization_roundtrip(self):
        ledger = TokenLedger()
        ledger.record(TokenAttempt(
            model="test", estimated_input_tokens=1000,
            provider_input_tokens=1100, success=True,
        ))
        data = ledger.to_serializable()
        restored = TokenLedger.from_serializable(data)
        assert len(restored.attempts) == 1
        assert restored.attempts[0].model == "test"
        assert restored.attempts[0].provider_input_tokens == 1100

    def test_summary(self):
        ledger = TokenLedger()
        ledger.record(TokenAttempt(model="test", estimated_input_tokens=1000, success=True))
        ledger.record(TokenAttempt(model="test", estimated_input_tokens=500, success=False, error="err"))
        s = ledger.summary()
        assert s["total_attempts"] == 2
        assert s["successful"] == 1
        assert s["failed"] == 1
        assert s["estimated_input_tokens"] == 1500

    def test_clear(self):
        ledger = TokenLedger()
        ledger.record(TokenAttempt(model="test"))
        ledger.clear()
        assert len(ledger.attempts) == 0

    def test_overflow_count(self):
        ledger = TokenLedger()
        ledger.record(TokenAttempt(model="test", is_overflow=True))
        ledger.record(TokenAttempt(model="test", is_overflow=False))
        assert ledger.overflow_count == 1

    def test_retry_count(self):
        ledger = TokenLedger()
        ledger.record(TokenAttempt(model="test", retry_number=0))  # First attempt
        ledger.record(TokenAttempt(model="test", retry_number=1))  # First retry
        ledger.record(TokenAttempt(model="test", retry_number=2))  # Second retry
        assert ledger.retry_count == 2

    def test_cache_read_tokens(self):
        ledger = TokenLedger()
        ledger.record(TokenAttempt(
            model="test",
            estimated_input_tokens=1000,
            cache_read_tokens=500,
        ))
        ledger.record(TokenAttempt(
            model="test",
            estimated_input_tokens=2000,
            cache_read_tokens=None,
        ))
        assert ledger.total_cache_read == 500

    def test_no_cache_data_returns_none(self):
        ledger = TokenLedger()
        ledger.record(TokenAttempt(model="test", cache_read_tokens=None))
        assert ledger.total_cache_read is None

    def test_partial_provider_data(self):
        """Test when some attempts have provider data and others don't."""
        ledger = TokenLedger()
        ledger.record(TokenAttempt(model="test", provider_input_tokens=1000))
        ledger.record(TokenAttempt(model="test", provider_input_tokens=None))
        assert ledger.total_provider_input == 1000

    def test_drift_ratio_with_zero_provider(self):
        """Test drift_ratio returns None when provider total is 0."""
        ledger = TokenLedger()
        ledger.record(TokenAttempt(
            model="test",
            estimated_input_tokens=1000,
            provider_input_tokens=0,
        ))
        assert ledger.drift_ratio is None

    def test_drift_ratio_with_zero_estimated(self):
        """Test drift_ratio returns None when estimated total is 0."""
        ledger = TokenLedger()
        ledger.record(TokenAttempt(
            model="test",
            estimated_input_tokens=0,
            provider_input_tokens=1000,
        ))
        assert ledger.drift_ratio is None

    def test_serialization_graceful_degradation(self):
        """Test from_serializable handles malformed entries gracefully."""
        ledger = TokenLedger()
        ledger.record(TokenAttempt(model="test", estimated_input_tokens=1000))
        
        data = ledger.to_serializable()
        # Add a malformed entry
        data.append({"invalid_field": "value"})
        
        restored = TokenLedger.from_serializable(data)
        # Should have the valid entry, malformed one skipped
        assert len(restored.attempts) == 1
        assert restored.attempts[0].model == "test"

    def test_token_ledger_repr(self):
        """Test that repr doesn't expose internal _max_attempts by default."""
        ledger = TokenLedger()
        r = repr(ledger)
        assert "_max_attempts" not in r
        assert "attempts" in r

    def test_multiple_wasted_tokens(self):
        """Test wasted tokens with multiple failed attempts."""
        ledger = TokenLedger()
        ledger.record(TokenAttempt(
            model="test",
            estimated_input_tokens=1000,
            estimated_output_tokens=500,
            success=False,
        ))
        ledger.record(TokenAttempt(
            model="test",
            estimated_input_tokens=2000,
            estimated_output_tokens=1000,
            success=False,
        ))
        # Successful attempt shouldn't count
        ledger.record(TokenAttempt(
            model="test",
            estimated_input_tokens=3000,
            estimated_output_tokens=1500,
            success=True,
        ))
        assert ledger.wasted_tokens == (1000 + 500) + (2000 + 1000)

    def test_total_estimated_output(self):
        """Test total_estimated_output property."""
        ledger = TokenLedger()
        ledger.record(TokenAttempt(model="test", estimated_output_tokens=500))
        ledger.record(TokenAttempt(model="test", estimated_output_tokens=1500))
        assert ledger.total_estimated_output == 2000

    def test_total_provider_output(self):
        """Test total_provider_output property."""
        ledger = TokenLedger()
        ledger.record(TokenAttempt(model="test", provider_output_tokens=800))
        ledger.record(TokenAttempt(model="test", provider_output_tokens=1200))
        assert ledger.total_provider_output == 2000

    def test_empty_provider_output_returns_none(self):
        """Test that total_provider_output returns None when no data."""
        ledger = TokenLedger()
        ledger.record(TokenAttempt(model="test", provider_output_tokens=None))
        assert ledger.total_provider_output is None