"""Tests for dead-singleton detection and auto-restart in get_transport() (bd-206).

When the BEAM process dies between the eager startup probe and the first
real request, get_transport() must detect the stale singleton, discard it,
and attempt to start a fresh transport instead of returning a dead object.
"""

import threading
from unittest.mock import MagicMock, patch

import pytest

import code_puppy.elixir_transport_helpers as helpers


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure the module-level singleton is cleared before and after each test."""
    with helpers._module_transport_lock:
        helpers._module_transport = None
    yield
    with helpers._module_transport_lock:
        if helpers._module_transport is not None:
            try:
                helpers._module_transport.stop()
            except Exception:
                pass
            helpers._module_transport = None


class TestTransportIsAliveHelper:
    """Tests for the _transport_is_alive helper."""

    def test_returns_false_for_none(self):
        assert helpers._transport_is_alive(None) is False

    def test_returns_true_for_alive_transport(self):
        mock = MagicMock()
        mock.is_alive.return_value = True
        assert helpers._transport_is_alive(mock) is True

    def test_returns_false_for_dead_transport(self):
        mock = MagicMock()
        mock.is_alive.return_value = False
        assert helpers._transport_is_alive(mock) is False

    def test_returns_false_when_is_alive_raises(self):
        mock = MagicMock()
        mock.is_alive.side_effect = RuntimeError("boom")
        assert helpers._transport_is_alive(mock) is False


class TestGetTransportDeadSingleton:
    """Tests for get_transport() when the cached singleton is dead (bd-206)."""

    def test_dead_singleton_is_detected_and_restarted(self):
        """When the cached transport's process has died, get_transport()
        should discard it and start a new one."""
        dead_transport = MagicMock()
        dead_transport.is_alive.return_value = False

        # Plant the dead singleton
        with helpers._module_transport_lock:
            helpers._module_transport = dead_transport

        alive_transport = MagicMock()
        alive_transport.is_alive.return_value = True

        with patch(
            "code_puppy.elixir_transport.ElixirTransport",
            return_value=alive_transport,
        ) as MockTransport:
            result = helpers.get_transport()

        # Dead transport should have been stopped
        dead_transport.stop.assert_called_once()
        # New transport should have been started
        alive_transport.start.assert_called_once()
        # Returned transport should be the new one
        assert result is alive_transport

    def test_alive_singleton_is_returned_without_restart(self):
        """When the cached transport is still alive, get_transport() returns
        it immediately without creating a new one."""
        alive_transport = MagicMock()
        alive_transport.is_alive.return_value = True

        with helpers._module_transport_lock:
            helpers._module_transport = alive_transport

        with patch(
            "code_puppy.elixir_transport.ElixirTransport"
        ) as MockTransport:
            result = helpers.get_transport()

        # Should not create a new transport
        MockTransport.assert_not_called()
        # Should return the existing one
        assert result is alive_transport

    def test_none_singleton_creates_new_transport(self):
        """When no singleton exists, get_transport() creates a new one."""
        alive_transport = MagicMock()
        alive_transport.is_alive.return_value = True

        with patch(
            "code_puppy.elixir_transport.ElixirTransport",
            return_value=alive_transport,
        ):
            result = helpers.get_transport()

        alive_transport.start.assert_called_once()
        assert result is alive_transport

    def test_concurrent_calls_during_restart(self):
        """Multiple threads calling get_transport() while the singleton is
        dead should all get the same restarted transport (no double-start)."""
        dead_transport = MagicMock()
        dead_transport.is_alive.return_value = False

        with helpers._module_transport_lock:
            helpers._module_transport = dead_transport

        alive_transport = MagicMock()
        alive_transport.is_alive.return_value = True

        results = []
        barrier = threading.Barrier(4, timeout=5)

        def call_get_transport():
            barrier.wait()
            with patch(
                "code_puppy.elixir_transport.ElixirTransport",
                return_value=alive_transport,
            ):
                results.append(helpers.get_transport())

        threads = [threading.Thread(target=call_get_transport) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # All threads should get the same transport
        assert all(r is alive_transport for r in results)
