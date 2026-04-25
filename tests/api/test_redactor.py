"""Tests for code_puppy/api/redactor.py — boundary redaction and sanitization."""

from code_puppy.api.redactor import (
    redact,
    redact_approval_dict,
    redact_event_data,
    redact_run_dict,
    redact_status_payload,
    sanitize_traceback,
    truncate,
)


# ---------------------------------------------------------------------------
# Basic redaction
# ---------------------------------------------------------------------------


class TestRedact:
    """Tests for the redact() function — secret masking + truncation."""

    def test_none_returns_empty(self) -> None:
        assert redact(None) == ""

    def test_short_text_unchanged(self) -> None:
        assert redact("hello world") == "hello world"

    def test_long_text_truncated(self) -> None:
        long = "x" * 1000
        result = redact(long)
        assert len(result) == 500
        assert result.endswith("…")

    def test_custom_max_length(self) -> None:
        result = redact("short", max_length=10)
        assert result == "short"

    def test_openai_key_redacted(self) -> None:
        result = redact("key=sk-abcdefghijklmnopqrstuvwxyz1234567890")
        assert "sk-" not in result or "REDACTED" in result

    def test_github_pat_redacted(self) -> None:
        result = redact("token=ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD")
        assert "ghp_" not in result or "REDACTED" in result

    def test_aws_key_redacted(self) -> None:
        result = redact("AKIAIOSFODNN7EXAMPLE")
        assert "AKIA" not in result or "REDACTED" in result

    def test_bearer_redacted(self) -> None:
        result = redact("Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789")
        assert "Bearer ***REDACTED***" in result

    def test_api_key_equals_redacted(self) -> None:
        result = redact("api_key=supersecretvalue1234567890")
        assert "REDACTED" in result

    def test_password_equals_redacted(self) -> None:
        result = redact("password=hunter2longpasswordvalue")
        assert "REDACTED" in result

    def test_normal_text_not_redacted(self) -> None:
        result = redact("Hello, this is a normal prompt with no secrets.")
        assert result == "Hello, this is a normal prompt with no secrets."


class TestTruncate:
    """Tests for the truncate() function."""

    def test_short_text_unchanged(self) -> None:
        assert truncate("hello", max_length=10) == "hello"

    def test_exact_length_unchanged(self) -> None:
        assert truncate("hello", max_length=5) == "hello"

    def test_over_length_truncated(self) -> None:
        result = truncate("hello world!", max_length=5)
        assert len(result) == 5
        assert result.endswith("…")


# ---------------------------------------------------------------------------
# Traceback sanitization
# ---------------------------------------------------------------------------


class TestSanitizeTraceback:
    """Tests for sanitize_traceback — truncation, frame-limiting, redaction."""

    def test_empty_returns_empty(self) -> None:
        assert sanitize_traceback("") == ""

    def test_short_traceback_preserved(self) -> None:
        tb = 'Traceback (most recent call last):\n  File "test.py", line 1\n    x\nError: boom'
        result = sanitize_traceback(tb)
        assert "boom" in result

    def test_long_traceback_truncated_frames(self) -> None:
        lines = ["Traceback (most recent call last):"]
        for i in range(20):
            lines.append(f'  File "module{i}.py", line {i}')
            lines.append(f"    func_{i}()")
        lines.append("Error: bad")
        tb = "\n".join(lines)
        result = sanitize_traceback(tb)
        assert "truncated" in result
        assert "bad" in result

    def test_secrets_in_traceback_redacted(self) -> None:
        tb = '  File "test.py", line 1\n    api_key=sk-abcdefghijklmnopqrstuvwxyz1234567890\nError: fail'
        result = sanitize_traceback(tb)
        assert "REDACTED" in result


# ---------------------------------------------------------------------------
# Event/status/approval boundary helpers
# ---------------------------------------------------------------------------


class TestRedactEventData:
    """Tests for redact_event_data — recursive dict redaction."""

    def test_dict_with_sensitive_fields(self) -> None:
        data = {
            "prompt_preview": "sk-abcdefghijklmnopqrstuvwxyz1234567890abc",
            "run_id": "abc-123",
            "type": "test",
        }
        result = redact_event_data(data)
        assert result["run_id"] == "abc-123"
        assert result["type"] == "test"
        assert "REDACTED" in result["prompt_preview"]

    def test_non_sensitive_fields_preserved(self) -> None:
        data = {"run_id": "abc", "status": "running"}
        result = redact_event_data(data)
        assert result == data

    def test_nested_dict(self) -> None:
        data = {"data": {"content": "api_key=supersecretvalue12345"}}
        result = redact_event_data(data)
        assert "REDACTED" in result["data"]["content"]

    def test_list_values(self) -> None:
        data = {"items": [{"content": "sk-abcdefghijklmnopqrstuvwxyz1234567890abc"}]}
        result = redact_event_data(data)
        assert "REDACTED" in result["items"][0]["content"]

    def test_non_dict_passthrough(self) -> None:
        assert redact_event_data("plain text") == "plain text"
        assert redact_event_data(42) == 42


class TestRedactApprovalDict:
    """Tests for redact_approval_dict."""

    def test_content_preview_feedback_redacted(self) -> None:
        approval = {
            "approval_id": "abc",
            "title": "Edit file?",
            "content": "api_key=supersecretvalue12345" + "x" * 600,
            "preview": "--- a/secret\npassword=hunter2longpasswordvalue",
            "feedback": None,
        }
        result = redact_approval_dict(approval)
        assert result["approval_id"] == "abc"
        assert result["title"] == "Edit file?"  # not a sensitive field
        assert "REDACTED" in result["content"]
        assert "REDACTED" in result["preview"]
        assert result["feedback"] is None

    def test_short_content_preserved(self) -> None:
        approval = {"approval_id": "x", "content": "short text", "preview": "diff"}
        result = redact_approval_dict(approval)
        assert result["content"] == "short text"
        assert result["preview"] == "diff"


class TestRedactRunDict:
    """Tests for redact_run_dict."""

    def test_sensitive_fields_redacted(self) -> None:
        run = {
            "run_id": "abc",
            "status": "completed",
            "prompt_preview": "sk-abcdefghijklmnopqrstuvwxyz1234567890abc",
            "output_preview": "Here is your Bearer abcdefghijklmnopqrstuvwxyz0123456789token",
            "error": None,
        }
        result = redact_run_dict(run)
        assert result["run_id"] == "abc"
        assert result["status"] == "completed"
        assert "REDACTED" in result["prompt_preview"]
        assert "REDACTED" in result["output_preview"]

    def test_none_error_preserved(self) -> None:
        run = {"error": None, "run_id": "x"}
        result = redact_run_dict(run)
        assert result["error"] is None


class TestRedactStatusPayload:
    """Tests for redact_status_payload — full status boundary redaction."""

    def test_current_run_redacted(self) -> None:
        status = {
            "running": True,
            "current_run": {
                "prompt_preview": "sk-abcdefghijklmnopqrstuvwxyz1234567890abc",
                "output_preview": None,
                "error": None,
            },
            "recent_runs": [],
            "pending_approvals": [],
        }
        result = redact_status_payload(status)
        assert "REDACTED" in result["current_run"]["prompt_preview"]

    def test_recent_runs_redacted(self) -> None:
        status = {
            "running": False,
            "current_run": None,
            "recent_runs": [
                {
                    "prompt_preview": "api_key=supersecretvalue12345",
                    "output_preview": "data",
                    "error": None,
                }
            ],
            "pending_approvals": [],
        }
        result = redact_status_payload(status)
        assert "REDACTED" in result["recent_runs"][0]["prompt_preview"]

    def test_pending_approvals_redacted(self) -> None:
        status = {
            "running": False,
            "current_run": None,
            "recent_runs": [],
            "pending_approvals": [
                {
                    "approval_id": "a1",
                    "content": "api_key=supersecretvalue12345",
                    "preview": "diff",
                    "feedback": None,
                }
            ],
        }
        result = redact_status_payload(status)
        assert "REDACTED" in result["pending_approvals"][0]["content"]

    def test_non_dict_values_preserved(self) -> None:
        status = {
            "running": True,
            "current_run": None,
            "recent_runs": [],
            "pending_approvals": [],
            "pending_bus_requests": 5,
        }
        result = redact_status_payload(status)
        assert result["pending_bus_requests"] == 5
