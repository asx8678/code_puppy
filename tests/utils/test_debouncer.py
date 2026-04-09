import threading
import time

import pytest

from code_puppy.utils.debouncer import Debouncer


def test_first_call_always_passes():
    d = Debouncer(min_interval_s=1.0)
    assert d.should_update() is True


def test_immediate_second_call_rejected():
    d = Debouncer(min_interval_s=1.0)
    d.should_update()  # consume the first
    assert d.should_update() is False


def test_after_interval_passes(monkeypatch):
    d = Debouncer(min_interval_s=0.5)
    fake_time = [1000.0]
    monkeypatch.setattr(
        "code_puppy.utils.debouncer.time.monotonic", lambda: fake_time[0]
    )
    assert d.should_update() is True  # t=1000.0
    fake_time[0] = 1000.4
    assert d.should_update() is False  # t=1000.4, delta=0.4 < 0.5
    fake_time[0] = 1000.6
    assert d.should_update() is True  # t=1000.6, delta=0.6 >= 0.5


def test_has_pending_flag(monkeypatch):
    d = Debouncer(min_interval_s=1.0)
    fake_time = [0.0]
    monkeypatch.setattr(
        "code_puppy.utils.debouncer.time.monotonic", lambda: fake_time[0]
    )
    d.should_update()  # approved, pending=False
    assert d.has_pending() is False
    d.should_update()  # rejected, pending=True
    assert d.has_pending() is True
    fake_time[0] = 2.0
    d.should_update()  # approved again, pending=False
    assert d.has_pending() is False


def test_reset(monkeypatch):
    d = Debouncer(min_interval_s=1.0)
    fake_time = [0.0]
    monkeypatch.setattr(
        "code_puppy.utils.debouncer.time.monotonic", lambda: fake_time[0]
    )
    d.should_update()  # t=0, approved
    assert d.should_update() is False  # rejected
    d.reset()
    assert d.should_update() is True  # reset made us eligible again


def test_negative_interval_raises():
    with pytest.raises(ValueError):
        Debouncer(min_interval_s=-1)


def test_zero_interval_always_passes():
    d = Debouncer(min_interval_s=0.0)
    for _ in range(10):
        assert d.should_update() is True


def test_thread_safety():
    """Many threads hammering should_update; only one should succeed at a time."""
    d = Debouncer(min_interval_s=0.1)
    approvals = []
    lock = threading.Lock()

    def hammer():
        for _ in range(100):
            if d.should_update():
                with lock:
                    approvals.append(time.monotonic())
            time.sleep(0.001)

    threads = [threading.Thread(target=hammer) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Verify no two approvals are < 0.1s apart
    approvals.sort()
    for i in range(1, len(approvals)):
        assert approvals[i] - approvals[i - 1] >= 0.09  # small slack
