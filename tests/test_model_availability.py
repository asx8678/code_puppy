"""Tests for ModelAvailabilityService circuit breaker."""

import threading
import pytest
from code_puppy.model_availability import (
    ModelAvailabilityService,
    ModelAvailabilitySnapshot,
)


@pytest.fixture
def svc():
    return ModelAvailabilityService()


def test_initially_all_healthy(svc):
    snap = svc.snapshot("gpt-4")
    assert snap.available is True
    assert snap.reason is None


def test_mark_terminal_makes_unavailable(svc):
    svc.mark_terminal("gpt-4", "quota")
    snap = svc.snapshot("gpt-4")
    assert snap.available is False
    assert snap.reason == "quota"


def test_mark_healthy_clears_terminal(svc):
    svc.mark_terminal("gpt-4", "quota")
    svc.mark_healthy("gpt-4")
    snap = svc.snapshot("gpt-4")
    assert snap.available is True


def test_sticky_retry_available_until_consumed(svc):
    svc.mark_sticky_retry("gpt-4")
    assert svc.snapshot("gpt-4").available is True

    svc.consume_sticky_attempt("gpt-4")
    assert svc.snapshot("gpt-4").available is False


def test_terminal_not_downgraded_to_sticky(svc):
    svc.mark_terminal("gpt-4", "quota")
    svc.mark_sticky_retry("gpt-4")  # should be no-op
    assert svc.snapshot("gpt-4").available is False
    assert svc.snapshot("gpt-4").reason == "quota"


def test_select_first_available_skips_terminal(svc):
    svc.mark_terminal("model-a", "quota")
    result = svc.select_first_available(["model-a", "model-b", "model-c"])
    assert result.selected_model == "model-b"
    assert len(result.skipped) == 1
    assert result.skipped[0] == ("model-a", "quota")


def test_select_first_available_all_down(svc):
    svc.mark_terminal("a", "quota")
    svc.mark_terminal("b", "capacity")
    result = svc.select_first_available(["a", "b"])
    assert result.selected_model is None
    assert len(result.skipped) == 2


def test_reset_turn_restores_sticky(svc):
    svc.mark_sticky_retry("gpt-4")
    svc.consume_sticky_attempt("gpt-4")
    assert svc.snapshot("gpt-4").available is False

    svc.reset_turn()
    assert svc.snapshot("gpt-4").available is True


def test_reset_turn_does_not_restore_terminal(svc):
    svc.mark_terminal("gpt-4", "quota")
    svc.reset_turn()
    assert svc.snapshot("gpt-4").available is False


def test_reset_clears_all(svc):
    svc.mark_terminal("a", "quota")
    svc.mark_sticky_retry("b")
    svc.reset()
    assert svc.snapshot("a").available is True
    assert svc.snapshot("b").available is True


def test_thread_safety(svc):
    """Concurrent marks from multiple threads should not corrupt state."""
    errors = []

    def mark_and_check(model_id: str):
        try:
            for _ in range(100):
                svc.mark_terminal(model_id, "quota")
                svc.snapshot(model_id)
                svc.mark_healthy(model_id)
                svc.mark_sticky_retry(model_id)
                svc.consume_sticky_attempt(model_id)
                svc.reset_turn()
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=mark_and_check, args=(f"m-{i}",)) for i in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Thread safety errors: {errors}"
