"""Tests for agent_memory signal safeguards (code-puppy-eed fix).

Tests the memory poisoning fix which adds:
- Caps: Maximum number/weight of preference signals per fact
- Decay: Time-based decay so old signals lose influence
- Rate limiting: Prevents rapid-fire preference signal injection
"""

import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from code_puppy.plugins.agent_memory.signal_safeguards import (
    DEFAULT_DECAY_HOURS,
    DEFAULT_MAX_PREFERENCE_SIGNALS,
    DEFAULT_RATE_LIMIT_SECONDS,
    SafeguardManager,
    SignalApplication,
    SignalTracker,
    clear_all_safeguard_managers,
    clear_safeguard_manager,
    get_safeguard_manager,
)

if TYPE_CHECKING:
    from code_puppy.plugins.agent_memory.signals import Signal


# ============================================================================
# SignalTracker Tests
# ============================================================================


class TestSignalTracker:
    """Tests for SignalTracker class."""

    def test_initial_state(self) -> None:
        """SignalTracker starts with empty applications."""
        tracker = SignalTracker(fact_text="Test fact")
        assert tracker.fact_text == "Test fact"
        assert tracker.applications == []

    def test_record_application(self) -> None:
        """Recording an application adds to the list."""
        tracker = SignalTracker(fact_text="Test fact")

        tracker.record_application(
            signal_type="PREFERENCE",
            session_id="session-1",
            delta_applied=0.15,
        )

        assert len(tracker.applications) == 1
        app = tracker.applications[0]
        assert app.signal_type == "PREFERENCE"
        assert app.session_id == "session-1"
        assert app.delta_applied == 0.15
        assert app.applied_at is not None

    def test_can_apply_preference_allows_first_signal(self) -> None:
        """First preference signal is always allowed."""
        tracker = SignalTracker(fact_text="Test fact")

        allowed, reason = tracker.can_apply_preference(
            session_id="session-1",
            max_signals=10,
            rate_limit_seconds=60,
        )

        assert allowed is True
        assert reason == ""

    def test_can_apply_preference_blocks_at_cap(self) -> None:
        """Preference signals are blocked when cap is reached."""
        tracker = SignalTracker(fact_text="Test fact")

        # Add max_signals preference applications
        for i in range(5):
            tracker.record_application(
                signal_type="PREFERENCE",
                session_id=f"session-{i}",
                delta_applied=0.15,
            )

        # Next signal should be blocked
        allowed, reason = tracker.can_apply_preference(
            session_id="session-new",
            max_signals=5,
            rate_limit_seconds=60,
        )

        assert allowed is False
        assert "cap reached" in reason.lower()

    def test_can_apply_preference_rate_limits_same_session(self) -> None:
        """Rate limiting prevents rapid signals from same session."""
        tracker = SignalTracker(fact_text="Test fact")

        # First signal from session-1
        tracker.record_application(
            signal_type="PREFERENCE",
            session_id="session-1",
            delta_applied=0.15,
        )

        # Immediate second signal from same session should be blocked
        allowed, reason = tracker.can_apply_preference(
            session_id="session-1",
            max_signals=10,
            rate_limit_seconds=60,
        )

        assert allowed is False
        assert "rate limit" in reason.lower()

    def test_can_apply_preference_allows_different_session(self) -> None:
        """Different session can apply signal even with rate limit active."""
        tracker = SignalTracker(fact_text="Test fact")

        # First signal from session-1
        tracker.record_application(
            signal_type="PREFERENCE",
            session_id="session-1",
            delta_applied=0.15,
        )

        # Signal from different session should be allowed
        allowed, reason = tracker.can_apply_preference(
            session_id="session-2",
            max_signals=10,
            rate_limit_seconds=60,
        )

        assert allowed is True
        assert reason == ""

    def test_rate_limit_allows_after_timeout(self) -> None:
        """Rate limit allows signal after timeout period."""
        tracker = SignalTracker(fact_text="Test fact")

        # Create an old application (more than rate_limit_seconds ago)
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        tracker.applications.append(
            SignalApplication(
                signal_type="PREFERENCE",
                applied_at=old_time,
                session_id="session-1",
                delta_applied=0.15,
            )
        )

        # New signal from same session should be allowed after timeout
        allowed, reason = tracker.can_apply_preference(
            session_id="session-1",
            max_signals=10,
            rate_limit_seconds=60,
        )

        assert allowed is True
        assert reason == ""

    def test_corrections_not_counted_toward_cap(self) -> None:
        """Correction signals don't count toward preference cap."""
        tracker = SignalTracker(fact_text="Test fact")

        # Add many correction applications
        for i in range(10):
            tracker.record_application(
                signal_type="CORRECTION",
                session_id=f"session-{i}",
                delta_applied=-0.3,
            )

        # Preference signal should still be allowed
        allowed, reason = tracker.can_apply_preference(
            session_id="session-new",
            max_signals=5,
            rate_limit_seconds=60,
        )

        assert allowed is True
        assert reason == ""

    def test_application_history_cleanup(self) -> None:
        """History is cleaned up when it gets too large."""
        tracker = SignalTracker(fact_text="Test fact")

        # Add many applications
        for i in range(150):
            tracker.record_application(
                signal_type="PREFERENCE",
                session_id=f"session-{i}",
                delta_applied=0.15,
            )

        # Should be trimmed to 50 most recent
        assert len(tracker.applications) == 50


# ============================================================================
# SafeguardManager Tests
# ============================================================================


class TestSafeguardManager:
    """Tests for SafeguardManager class."""

    def test_initialization_with_defaults(self) -> None:
        """SafeguardManager uses default settings."""
        manager = SafeguardManager()

        assert manager.max_preference_signals == DEFAULT_MAX_PREFERENCE_SIGNALS
        assert manager.decay_hours == DEFAULT_DECAY_HOURS
        assert manager.rate_limit_seconds == DEFAULT_RATE_LIMIT_SECONDS

    def test_initialization_with_custom_values(self) -> None:
        """SafeguardManager accepts custom settings."""
        manager = SafeguardManager(
            max_preference_signals=5,
            decay_hours=24.0,
            rate_limit_seconds=30,
        )

        assert manager.max_preference_signals == 5
        assert manager.decay_hours == 24.0
        assert manager.rate_limit_seconds == 30

    def test_get_tracker_creates_new(self) -> None:
        """get_tracker creates new tracker for unknown fact."""
        manager = SafeguardManager()

        tracker = manager.get_tracker("New fact")

        assert tracker.fact_text == "New fact"
        assert tracker.applications == []

    def test_get_tracker_returns_existing(self) -> None:
        """get_tracker returns existing tracker for known fact."""
        manager = SafeguardManager()

        tracker1 = manager.get_tracker("Fact text")
        tracker1.record_application("PREFERENCE", "session-1", 0.15)

        tracker2 = manager.get_tracker("Fact text")

        assert tracker1 is tracker2
        assert len(tracker2.applications) == 1

    def test_can_apply_signal_allows_corrections(self) -> None:
        """Corrections are always allowed (no safeguard)."""
        manager = SafeguardManager()

        # Create mock correction signal
        mock_signal = MagicMock()
        mock_signal.signal_type.name = "CORRECTION"

        allowed, reason = manager.can_apply_signal(
            fact_text="Test fact",
            signal=mock_signal,
            session_id="session-1",
        )

        assert allowed is True
        assert reason == ""

    def test_can_apply_signal_allows_reinforcements(self) -> None:
        """Reinforcements are always allowed (no safeguard)."""
        manager = SafeguardManager()

        # Create mock reinforcement signal
        mock_signal = MagicMock()
        mock_signal.signal_type.name = "REINFORCEMENT"

        allowed, reason = manager.can_apply_signal(
            fact_text="Test fact",
            signal=mock_signal,
            session_id="session-1",
        )

        assert allowed is True
        assert reason == ""

    def test_can_apply_signal_enforces_preference_cap(self) -> None:
        """Preference signals are capped."""
        manager = SafeguardManager(max_preference_signals=3)

        # Create mock preference signal
        mock_signal = MagicMock()
        mock_signal.signal_type.name = "PREFERENCE"

        # Apply 3 signals
        for i in range(3):
            allowed, _ = manager.can_apply_signal(
                fact_text="Test fact",
                signal=mock_signal,
                session_id=f"session-{i}",
            )
            assert allowed is True
            manager.record_signal_applied("Test fact", mock_signal, f"session-{i}")

        # 4th signal should be blocked
        allowed, reason = manager.can_apply_signal(
            fact_text="Test fact",
            signal=mock_signal,
            session_id="session-4",
        )

        assert allowed is False
        assert "cap" in reason.lower()

    def test_record_signal_applied_tracks_preferences(self) -> None:
        """Recording signal application adds to tracker."""
        manager = SafeguardManager()

        # Create mock preference signal
        mock_signal = MagicMock()
        mock_signal.signal_type.name = "PREFERENCE"
        mock_signal.confidence_delta = 0.15

        manager.record_signal_applied("Test fact", mock_signal, "session-1")

        tracker = manager.get_tracker("Test fact")
        assert len(tracker.applications) == 1
        assert tracker.applications[0].signal_type == "PREFERENCE"

    def test_get_signal_stats_empty(self) -> None:
        """get_signal_stats returns zeros for untracked fact."""
        manager = SafeguardManager()

        stats = manager.get_signal_stats("Untracked fact")

        assert stats["total_signals"] == 0
        assert stats["preference_signals"] == 0
        assert stats["recent_signals"] == 0

    def test_get_signal_stats_with_applications(self) -> None:
        """get_signal_stats returns correct counts."""
        manager = SafeguardManager()

        # Add applications
        for i in range(5):
            manager.get_tracker("Fact 1").record_application("PREFERENCE", f"s{i}", 0.15)
        for i in range(3):
            manager.get_tracker("Fact 1").record_application("CORRECTION", f"s{i}", -0.3)

        stats = manager.get_signal_stats("Fact 1")

        assert stats["total_signals"] == 8
        assert stats["preference_signals"] == 5
        assert stats["recent_signals"] == 5  # All recent

    def test_thread_safety(self) -> None:
        """SafeguardManager is thread-safe."""
        import threading

        manager = SafeguardManager()
        errors = []

        def add_applications(thread_id: int) -> None:
            try:
                for i in range(10):
                    tracker = manager.get_tracker(f"Fact {thread_id}")
                    tracker.record_application("PREFERENCE", f"s{i}", 0.15)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_applications, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # Verify all facts were created
        for i in range(5):
            tracker = manager.get_tracker(f"Fact {i}")
            assert len(tracker.applications) == 10


# ============================================================================
# Global Manager Tests
# ============================================================================


class TestGlobalManager:
    """Tests for global safeguard manager functions."""

    def test_get_safeguard_manager_creates_new(self) -> None:
        """get_safeguard_manager creates manager for new agent."""
        clear_safeguard_manager("test-agent-new")

        manager = get_safeguard_manager("test-agent-new")

        assert isinstance(manager, SafeguardManager)

    def test_get_safeguard_manager_returns_existing(self) -> None:
        """get_safeguard_manager returns same manager for existing agent."""
        clear_safeguard_manager("test-agent-existing")

        manager1 = get_safeguard_manager("test-agent-existing")
        manager1.get_tracker("Fact").record_application("PREFERENCE", "s1", 0.15)

        manager2 = get_safeguard_manager("test-agent-existing")

        assert manager1 is manager2
        assert len(manager2.get_tracker("Fact").applications) == 1

    def test_get_safeguard_manager_with_config(self) -> None:
        """get_safeguard_manager uses config settings."""
        clear_safeguard_manager("test-agent-config")

        mock_config = MagicMock()
        mock_config.max_preference_signals_per_fact = 7
        mock_config.preference_signal_decay_hours = 48.0
        mock_config.preference_rate_limit_seconds = 90

        manager = get_safeguard_manager("test-agent-config", mock_config)

        assert manager.max_preference_signals == 7
        assert manager.decay_hours == 48.0
        assert manager.rate_limit_seconds == 90

    def test_clear_safeguard_manager(self) -> None:
        """clear_safeguard_manager removes manager."""
        manager1 = get_safeguard_manager("test-agent-clear")
        clear_safeguard_manager("test-agent-clear")
        manager2 = get_safeguard_manager("test-agent-clear")

        assert manager1 is not manager2

    def test_clear_all_safeguard_managers(self) -> None:
        """clear_all_safeguard_managers removes all managers."""
        manager1 = get_safeguard_manager("agent-a")
        manager2 = get_safeguard_manager("agent-b")

        clear_all_safeguard_managers()

        new_manager1 = get_safeguard_manager("agent-a")
        new_manager2 = get_safeguard_manager("agent-b")

        assert manager1 is not new_manager1
        assert manager2 is not new_manager2


# ============================================================================
# Integration with Config Tests
# ============================================================================


class TestConfigIntegration:
    """Tests for integration with MemoryConfig."""

    def test_config_includes_safeguard_defaults(self) -> None:
        """MemoryConfig includes safeguard default values."""
        from code_puppy.plugins.agent_memory import MemoryConfig

        config = MemoryConfig()

        assert hasattr(config, "max_preference_signals_per_fact")
        assert hasattr(config, "preference_signal_decay_hours")
        assert hasattr(config, "preference_rate_limit_seconds")

        assert config.max_preference_signals_per_fact == 10
        assert config.preference_signal_decay_hours == 168.0
        assert config.preference_rate_limit_seconds == 60

    def test_config_custom_safeguard_values(self) -> None:
        """MemoryConfig accepts custom safeguard values."""
        from code_puppy.plugins.agent_memory import MemoryConfig

        config = MemoryConfig(
            max_preference_signals_per_fact=5,
            preference_signal_decay_hours=24.0,
            preference_rate_limit_seconds=30,
        )

        assert config.max_preference_signals_per_fact == 5
        assert config.preference_signal_decay_hours == 24.0
        assert config.preference_rate_limit_seconds == 30


# ============================================================================
# Memory Poisoning Fix Specific Tests
# ============================================================================


class TestMemoryPoisoningFix:
    """Tests specifically for the code-puppy-eed memory poisoning fix."""

    def test_preference_cap_prevents_unbounded_accumulation(self) -> None:
        """Preference cap prevents unbounded signal accumulation."""
        manager = SafeguardManager(max_preference_signals=5)

        mock_signal = MagicMock()
        mock_signal.signal_type.name = "PREFERENCE"
        mock_signal.confidence_delta = 0.15

        fact = "User prefers dark mode"

        # Try to apply 10 preference signals
        applied_count = 0
        for i in range(10):
            allowed, _ = manager.can_apply_signal(fact, mock_signal, f"s{i}")
            if allowed:
                manager.record_signal_applied(fact, mock_signal, f"s{i}")
                applied_count += 1

        # Only 5 should be applied due to cap
        assert applied_count == 5

        # Verify total confidence boost is capped
        # 5 signals * 0.15 = 0.75 (instead of 10 * 0.15 = 1.5)
        tracker = manager.get_tracker(fact)
        total_boost = sum(a.delta_applied for a in tracker.applications)
        assert total_boost == 0.75

    def test_rate_limit_prevents_rapid_fire(self) -> None:
        """Rate limit prevents rapid-fire signal injection."""
        manager = SafeguardManager(rate_limit_seconds=300)  # 5 minute rate limit

        mock_signal = MagicMock()
        mock_signal.signal_type.name = "PREFERENCE"

        fact = "User prefers TypeScript"
        session = "rapid-attack-session"

        # Simulate 10 rapid signals from same session
        allowed_count = 0
        for i in range(10):
            allowed, _ = manager.can_apply_signal(fact, mock_signal, session)
            if allowed:
                allowed_count += 1
                manager.record_signal_applied(fact, mock_signal, session)

        # Only 1 should be allowed due to rate limiting
        assert allowed_count == 1

    def test_different_facts_have_independent_limits(self) -> None:
        """Each fact has independent signal limits."""
        manager = SafeguardManager(max_preference_signals=3)

        mock_signal = MagicMock()
        mock_signal.signal_type.name = "PREFERENCE"

        # Fill up first fact
        for i in range(3):
            manager.record_signal_applied("Fact A", mock_signal, f"s{i}")

        # Second fact should still have full capacity
        allowed, _ = manager.can_apply_signal("Fact B", mock_signal, "s1")
        assert allowed is True

    def test_corrections_unaffected_by_preference_cap(self) -> None:
        """Corrections can still be applied when preference cap reached."""
        manager = SafeguardManager(max_preference_signals=2)

        pref_signal = MagicMock()
        pref_signal.signal_type.name = "PREFERENCE"
        pref_signal.confidence_delta = 0.15

        corr_signal = MagicMock()
        corr_signal.signal_type.name = "CORRECTION"
        corr_signal.confidence_delta = -0.3

        fact = "Some fact"

        # Fill up preference cap
        for i in range(2):
            manager.record_signal_applied(fact, pref_signal, f"s{i}")

        # Preference should be blocked
        allowed, _ = manager.can_apply_signal(fact, pref_signal, "s3")
        assert allowed is False

        # Correction should be allowed
        allowed, _ = manager.can_apply_signal(fact, corr_signal, "s3")
        assert allowed is True
