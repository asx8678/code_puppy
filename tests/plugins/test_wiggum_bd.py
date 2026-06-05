"""Tests for the ``/wiggum bd`` beads-draining mode (wiggum plugin extension)."""

from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest

beads = importlib.import_module("code_puppy.plugins.wiggum.beads")


def _fake_bd(*, ready=None, statuses=None, total=0, closed=0):
    """Fake ``_bd`` answering ready/show/count by sub-command."""
    ready, statuses = ready or [], statuses or {}

    def _bd(args):
        if args[0] == "ready":
            return [dict(b) for b in ready]
        if args[0] == "show":
            return [{"id": args[1], "status": statuses.get(args[1], "open")}]
        if args[0] == "count":
            return {"total": total, "groups": [{"group": "closed", "count": closed}]}
        return None

    return _bd


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    beads._current, beads._seen, beads._done = None, set(), 0
    for name in ("emit_info", "emit_success", "emit_warning"):
        monkeypatch.setattr(beads, name, lambda *a, **k: None)
    yield


def test_start_dispatches_top_bead_and_tells_agent_to_claim_and_close():
    ready = [{"id": "bd-1", "title": "First"}, {"id": "bd-2", "title": "Second"}]
    with (
        patch.object(beads, "_bd", _fake_bd(ready=ready, total=2)),
        patch.object(beads.state, "start") as mock_start,
    ):
        result = beads.start()
    assert isinstance(result, str)
    assert "bd-1" in result and "--claim" in result and "bd close bd-1" in result
    mock_start.assert_called_once_with("bd", mode="wiggum_bd")
    assert beads._current == "bd-1" and beads._seen == {"bd-1"}


def test_start_with_no_beads_is_a_noop():
    with (
        patch.object(beads, "_bd", _fake_bd(ready=[])),
        patch.object(beads.state, "start") as mock_start,
    ):
        assert beads.start() is True  # handled, no agent run
    mock_start.assert_not_called()


def test_loop_stops_when_queue_empty_and_counts_closed_bead():
    beads._current, beads._seen = "bd-1", {"bd-1"}
    with (
        patch.object(
            beads, "_bd", _fake_bd(statuses={"bd-1": "closed"}, total=1, closed=1)
        ),
        patch.object(beads.state, "stop") as mock_stop,
    ):
        assert beads.on_turn_end() is None
    assert beads._done == 1
    mock_stop.assert_called_once()


def test_closed_bead_advances_to_next():
    beads._current, beads._seen = "bd-1", {"bd-1"}
    with (
        patch.object(
            beads,
            "_bd",
            _fake_bd(
                ready=[{"id": "bd-2", "title": "Second"}],
                statuses={"bd-1": "closed"},
                total=1,
            ),
        ),
        patch.object(beads.state, "stop"),
    ):
        result = beads.on_turn_end()
    assert isinstance(result, dict) and "bd-2" in result["prompt"]
    assert result["clear_context"] is True and result["reason"] == "wiggum_bd"
    assert beads._done == 1 and beads._current == "bd-2"


def test_left_open_bead_is_reported_and_skipped_not_retried():
    beads._current, beads._seen = (
        "bd-1",
        {"bd-1"},
    )  # bd-1 already dispatched, still open
    ready = [{"id": "bd-1", "title": "First"}, {"id": "bd-2", "title": "Second"}]
    warnings: list[str] = []
    with (
        patch.object(
            beads, "_bd", _fake_bd(ready=ready, statuses={"bd-1": "open"}, total=2)
        ),
        patch.object(
            beads, "emit_warning", side_effect=lambda m, *a, **k: warnings.append(m)
        ),
        patch.object(beads.state, "stop"),
    ):
        result = beads.on_turn_end()
    assert "bd-2" in result["prompt"] and "bd-1" not in result["prompt"]
    assert beads._done == 0 and any("bd-1" in w for w in warnings)
