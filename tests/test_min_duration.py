"""Comprehensive tests for code_puppy/utils/min_duration.py.

Covers:
- ensure_min_duration (sync): basic pacing, already-elapsed, zero/negative
- ensure_min_duration_async (async): same cases via asyncio
- MinDurationContext: context manager timing
- Constants: correct values
"""

from __future__ import annotations

import asyncio
import time

import pytest

from code_puppy.utils.min_duration import (
    SPINNER_MIN_DURATION_NO_MSG,
    SPINNER_MIN_DURATION_WITH_MSG,
    MinDurationContext,
    ensure_min_duration,
    ensure_min_duration_async,
)


# ===========================================================================
# ensure_min_duration (sync)
# ===========================================================================


class TestEnsureMinDuration:
    """Tests for the synchronous variant."""

    def test_pads_short_operation(self) -> None:
        """Operation completing in ~0 s with 0.15 s min → total ≥ 0.15 s."""
        start = time.monotonic()
        ensure_min_duration(start, 0.15)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.14, f"Expected ≥0.14 s, got {elapsed:.4f} s"

    def test_no_sleep_when_already_elapsed(self) -> None:
        """If enough time already passed, no additional sleep."""
        start = time.monotonic() - 1.0  # pretend we started 1 s ago
        before = time.monotonic()
        ensure_min_duration(start, 0.5)
        after = time.monotonic()
        assert (after - before) < 0.05, "Should not have slept"

    def test_zero_min_seconds(self) -> None:
        """min_seconds=0 → immediate return, no sleep."""
        start = time.monotonic()
        before = time.monotonic()
        ensure_min_duration(start, 0)
        after = time.monotonic()
        assert (after - before) < 0.05

    def test_negative_min_seconds(self) -> None:
        """Negative min_seconds → immediate return."""
        start = time.monotonic()
        before = time.monotonic()
        ensure_min_duration(start, -1.0)
        after = time.monotonic()
        assert (after - before) < 0.05

    def test_exact_elapsed_no_sleep(self) -> None:
        """When elapsed == min_seconds, remaining ≤ 0 → no sleep."""
        start = time.monotonic() - 0.5
        before = time.monotonic()
        ensure_min_duration(start, 0.5)
        after = time.monotonic()
        assert (after - before) < 0.05


# ===========================================================================
# ensure_min_duration_async
# ===========================================================================


class TestEnsureMinDurationAsync:
    """Tests for the async variant."""

    @pytest.mark.asyncio
    async def test_pads_short_operation(self) -> None:
        start = time.monotonic()
        await ensure_min_duration_async(start, 0.15)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.14

    @pytest.mark.asyncio
    async def test_no_sleep_when_already_elapsed(self) -> None:
        start = time.monotonic() - 1.0
        before = time.monotonic()
        await ensure_min_duration_async(start, 0.5)
        after = time.monotonic()
        assert (after - before) < 0.05

    @pytest.mark.asyncio
    async def test_zero_min_seconds(self) -> None:
        start = time.monotonic()
        before = time.monotonic()
        await ensure_min_duration_async(start, 0)
        after = time.monotonic()
        assert (after - before) < 0.05

    @pytest.mark.asyncio
    async def test_negative_min_seconds(self) -> None:
        start = time.monotonic()
        before = time.monotonic()
        await ensure_min_duration_async(start, -1.0)
        after = time.monotonic()
        assert (after - before) < 0.05


# ===========================================================================
# MinDurationContext
# ===========================================================================


class TestMinDurationContext:
    """Tests for the async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager_pads_fast_operation(self) -> None:
        start = time.monotonic()
        async with MinDurationContext(0.15):
            pass  # instant operation
        elapsed = time.monotonic() - start
        assert elapsed >= 0.14

    @pytest.mark.asyncio
    async def test_context_manager_no_extra_sleep_for_slow_op(self) -> None:
        start = time.monotonic()
        async with MinDurationContext(0.05):
            await asyncio.sleep(0.10)  # operation takes longer than minimum
        elapsed = time.monotonic() - start
        # Should be ~0.10 s (the operation time), not 0.10 + 0.05
        assert elapsed < 0.20, f"Should not have added extra sleep, got {elapsed:.4f} s"


# ===========================================================================
# Constants
# ===========================================================================


class TestConstants:
    """Verify default timing constants match plandex spinner values."""

    def test_with_msg_is_700ms(self) -> None:
        assert SPINNER_MIN_DURATION_WITH_MSG == 0.70

    def test_no_msg_is_350ms(self) -> None:
        assert SPINNER_MIN_DURATION_NO_MSG == 0.35
