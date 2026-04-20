"""Isolation tests for agent trace storage."""

from pathlib import Path

import pytest

from code_puppy.config_paths import ConfigIsolationViolation
from code_puppy.plugins.agent_trace.schema import TraceEvent
from code_puppy.plugins.agent_trace.store import TraceStore


def test_trace_store_blocks_legacy_base_dir_in_pup_ex(monkeypatch, tmp_path):
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    ex_home = tmp_path / "pup_ex_home"
    ex_home.mkdir()
    monkeypatch.setenv("PUP_EX_HOME", str(ex_home))
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    legacy_traces = fake_home / ".code_puppy" / "traces"

    with pytest.raises(ConfigIsolationViolation):
        TraceStore(base_dir=legacy_traces)


def test_trace_store_default_base_dir_writes_under_active_home(monkeypatch, tmp_path):
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    ex_home = tmp_path / "pup_ex_home"
    ex_home.mkdir()
    monkeypatch.setenv("PUP_EX_HOME", str(ex_home))
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    store = TraceStore()
    event = TraceEvent(trace_id="trace-123")

    assert str(store.base_dir).startswith(str(ex_home))
    assert store.append(event) is True
    assert store.event_count("trace-123") == 1
    assert store.read("trace-123")[0].trace_id == "trace-123"
    assert str(store._trace_path("trace-123")).startswith(str(ex_home))
