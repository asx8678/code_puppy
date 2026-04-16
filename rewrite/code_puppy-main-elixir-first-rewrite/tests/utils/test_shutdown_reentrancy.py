"""Tests for shutdown reentrancy guard in callbacks.py."""

import asyncio

import pytest

from code_puppy.callbacks import (
    clear_callbacks,
    get_shutdown_stage,
    on_shutdown,
    register_callback,
    reset_shutdown_stage,
)


@pytest.fixture(autouse=True)
def _clean():
    """Reset shutdown state and callbacks before each test."""
    reset_shutdown_stage()
    clear_callbacks("shutdown")
    yield
    reset_shutdown_stage()
    clear_callbacks("shutdown")


class TestShutdownReentrancy:
    def test_initial_stage_is_idle(self):
        assert get_shutdown_stage() == "idle"

    def test_shutdown_transitions_to_complete(self):
        asyncio.run(on_shutdown())
        assert get_shutdown_stage() == "complete"

    def test_double_shutdown_returns_empty(self):
        """Second shutdown call should be a no-op."""
        results1 = asyncio.run(on_shutdown())
        results2 = asyncio.run(on_shutdown())
        assert get_shutdown_stage() == "complete"
        assert results2 == []

    def test_shutdown_callbacks_execute(self):
        executed = []

        def _cb():
            executed.append(True)

        register_callback("shutdown", _cb)
        asyncio.run(on_shutdown())
        assert executed == [True]

    def test_shutdown_callbacks_not_reexecuted(self):
        """Callbacks should only run once even if shutdown is called twice."""
        count = []

        def _cb():
            count.append(1)

        register_callback("shutdown", _cb)
        asyncio.run(on_shutdown())
        asyncio.run(on_shutdown())
        assert len(count) == 1

    def test_reset_allows_re_shutdown(self):
        """After reset, shutdown can run again (for testing only)."""
        count = []

        def _cb():
            count.append(1)

        register_callback("shutdown", _cb)
        asyncio.run(on_shutdown())
        reset_shutdown_stage()
        asyncio.run(on_shutdown())
        assert len(count) == 2

    def test_callback_exception_still_completes(self):
        """Shutdown should complete even if a callback raises."""

        def _bad_cb():
            raise RuntimeError("boom")

        register_callback("shutdown", _bad_cb)
        asyncio.run(on_shutdown())
        assert get_shutdown_stage() == "complete"
