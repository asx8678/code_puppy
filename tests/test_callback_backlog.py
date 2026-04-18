"""Tests for the callback event backlog system."""

import os

import pytest
from code_puppy import _backlog
from code_puppy.callbacks import (
    clear_callbacks,
    drain_all_backlogs,
    drain_backlog,
    register_callback,
    _trigger_callbacks_sync,
)


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset backlog and callbacks between tests."""
    # Disable auto-plugin-loading for isolated testing
    os.environ["PUP_DISABLE_CALLBACK_PLUGIN_LOADING"] = "1"
    _backlog.clear()
    clear_callbacks()
    yield
    _backlog.clear()
    clear_callbacks()
    os.environ.pop("PUP_DISABLE_CALLBACK_PLUGIN_LOADING", None)


@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
def test_backlog_buffers_when_no_listeners():
    """Events fired with no listeners should be buffered."""
    _trigger_callbacks_sync("startup")
    assert _backlog.pending_count("startup") == 1


@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
def test_backlog_buffers_args():
    """Buffered events preserve their arguments."""
    _trigger_callbacks_sync("custom_command", "/test", "test")
    events = _backlog.drain_backlog("custom_command")
    assert len(events) == 1
    args, kwargs = events[0]
    assert args == ("/test", "test")
    assert kwargs == {}


@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
def test_backlog_not_used_when_listeners_exist():
    """Events with active listeners should NOT be buffered."""
    called = []
    register_callback("startup", lambda: called.append(True))
    _trigger_callbacks_sync("startup")
    assert _backlog.pending_count("startup") == 0
    assert called == [True]


@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
def test_drain_replays_buffered_events():
    """drain_backlog() should replay events through the callback."""
    # Fire with no listener — gets buffered
    _trigger_callbacks_sync("custom_command", "/hello", "hello")
    assert _backlog.pending_count("custom_command") == 1

    # Now register listener and drain
    received = []
    register_callback("custom_command", lambda cmd, name: received.append((cmd, name)))
    drain_backlog("custom_command")

    assert received == [("/hello", "hello")]
    assert _backlog.pending_count("custom_command") == 0


@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
def test_drain_all_backlogs_processes_all_phases():
    """drain_all_backlogs() should process all phases with buffered events."""
    _trigger_callbacks_sync("startup")
    _trigger_callbacks_sync("shutdown")

    s_called = []
    register_callback("startup", lambda: s_called.append(True))
    register_callback("shutdown", lambda: s_called.append("shut"))

    results = drain_all_backlogs()
    assert "startup" in results or "shutdown" in results
    assert _backlog.pending_count() == 0


@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
def test_backlog_cap_prevents_memory_leak():
    """Backlog should cap at _MAX_BACKLOG_PER_PHASE entries."""
    for i in range(150):
        _backlog.buffer_event("startup", (i,), {})
    assert _backlog.pending_count("startup") == _backlog._MAX_BACKLOG_PER_PHASE


@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
def test_clear_callbacks_also_clears_backlog():
    """clear_callbacks() should also clear the backlog."""
    _trigger_callbacks_sync("startup")
    assert _backlog.pending_count("startup") == 1
    clear_callbacks("startup")
    assert _backlog.pending_count("startup") == 0


@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
def test_clear_all_callbacks_clears_all_backlogs():
    """clear_callbacks(None) should clear all backlogs."""
    _trigger_callbacks_sync("startup")
    _trigger_callbacks_sync("shutdown")
    clear_callbacks()
    assert _backlog.pending_count() == 0
