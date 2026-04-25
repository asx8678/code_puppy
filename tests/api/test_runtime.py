"""Tests for code_puppy/api/runtime.py — RuntimeManager."""

from unittest.mock import patch

import pytest

from code_puppy.api.runtime import RuntimeManager, _preview, _now, get_runtime_manager


class TestHelpers:
    """Tests for module-level helper functions."""

    def test_now_returns_iso_string(self) -> None:
        result = _now()
        assert "T" in result  # ISO format
        assert len(result) > 10

    def test_preview_short_text(self) -> None:
        assert _preview("hello") == "hello"

    def test_preview_long_text_truncated(self) -> None:
        long_text = "x" * 500
        result = _preview(long_text, max_length=300)
        assert len(result) == 300
        assert result.endswith("…")

    def test_preview_none_returns_empty(self) -> None:
        assert _preview(None) == ""

    def test_preview_custom_max_length(self) -> None:
        result = _preview("short", max_length=10)
        assert result == "short"


class TestRuntimeManagerInit:
    """Tests for RuntimeManager initial state."""

    def test_initial_status(self) -> None:
        mgr = RuntimeManager()
        status = mgr.get_status()
        assert status["running"] is False
        assert status["current_run"] is None
        assert status["recent_runs"] == []
        assert status["pending_approvals"] == []


class TestRuntimeManagerSubmit:
    """Tests for submit_prompt and cancel_current_run."""

    @pytest.mark.asyncio
    async def test_submit_empty_prompt_raises(self) -> None:
        mgr = RuntimeManager()
        with pytest.raises(ValueError, match="empty"):
            await mgr.submit_prompt("")

    @pytest.mark.asyncio
    async def test_submit_whitespace_prompt_raises(self) -> None:
        mgr = RuntimeManager()
        with pytest.raises(ValueError, match="empty"):
            await mgr.submit_prompt("   ")

    @pytest.mark.asyncio
    async def test_submit_prompt_returns_run_dict(self) -> None:
        mgr = RuntimeManager()
        with patch("code_puppy.api.runtime.emit_event"):
            result = await mgr.submit_prompt("hello", agent="test-agent")
            assert result["status"] == "queued"
            assert result["prompt_preview"] == "hello"
            assert result["agent_name"] == "test-agent"
            assert result["run_id"]
            assert result["created_at"]

    @pytest.mark.asyncio
    async def test_submit_while_running_raises(self) -> None:
        mgr = RuntimeManager()
        with patch("code_puppy.api.runtime.emit_event"):
            await mgr.submit_prompt("first")
            with pytest.raises(RuntimeError, match="already running"):
                await mgr.submit_prompt("second")
            # Clean up the hanging task
            await mgr.cancel_current_run()

    @pytest.mark.asyncio
    async def test_cancel_no_running_prompt(self) -> None:
        mgr = RuntimeManager()
        result = await mgr.cancel_current_run()
        assert result["cancelled"] is False


class TestRuntimeManagerRespondToApproval:
    """Tests for respond_to_approval."""

    def test_respond_to_unknown_approval_raises(self) -> None:
        mgr = RuntimeManager()
        with pytest.raises(ValueError, match="not found"):
            mgr.respond_to_approval("nonexistent", True)


class TestRuntimeManagerRespondToBusRequest:
    """Tests for respond_to_bus_request."""

    def test_unsupported_response_type_raises(self) -> None:
        mgr = RuntimeManager()
        with pytest.raises(ValueError, match="Unsupported"):
            mgr.respond_to_bus_request(prompt_id="p1", response_type="bogus")


class TestGetRuntimeManager:
    """Tests for module-level singleton."""

    def test_singleton(self) -> None:
        mgr1 = get_runtime_manager()
        mgr2 = get_runtime_manager()
        assert mgr1 is mgr2
