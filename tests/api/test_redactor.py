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

    def test_jwt_redacted(self) -> None:
        """JWT tokens (three base64url segments) are masked."""
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        result = redact(jwt)
        assert "JWT_REDACTED" in result
        assert "eyJ" not in result or "REDACTED" in result

    def test_pem_private_key_redacted(self) -> None:
        """PEM private key blocks are masked."""
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
        result = redact(pem)
        assert "***REDACTED*** KEY" in result

    def test_pem_ec_private_key_redacted(self) -> None:
        """EC private key PEM blocks are masked."""
        pem = (
            "-----BEGIN EC PRIVATE KEY-----\nMHQCAQEEI...\n-----END EC PRIVATE KEY-----"
        )
        result = redact(pem)
        assert "***REDACTED*** KEY" in result

    def test_pem_openssh_private_key_redacted(self) -> None:
        """OpenSSH private key PEM blocks are masked."""
        pem = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1r...\n-----END OPENSSH PRIVATE KEY-----"
        result = redact(pem)
        assert "***REDACTED*** KEY" in result

    def test_uuid_not_redacted(self) -> None:
        """UUIDs should not be matched by the hex-token pattern (they're 32 hex chars, not 64)."""
        uuid_str = "a1b2c3d4e5f67890a1b2c3d4e5f67890"
        result = redact(uuid_str)
        # 32-char hex should NOT match the 64+ char pattern
        assert "HEX_TOKEN_REDACTED" not in result

    def test_hex_token_64_plus_redacted(self) -> None:
        """64+ char hex strings are masked as tokens."""
        hex_token = "a" * 64
        result = redact(hex_token)
        assert "HEX_TOKEN_REDACTED" in result


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
    """Tests for redact_event_data — recursive dict redaction.

    All string leaf values are redacted (except structural ID keys).
    """

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

    def test_id_keys_not_redacted(self) -> None:
        """Structural ID keys keep their values untouched."""
        data = {
            "run_id": "550e8400-e29b-41d4-a716-446655440000",
            "approval_id": "abc-123",
            "type": "test_event",
            "status": "running",
            "agent_name": "max",
            "model_name": "gpt-4",
        }
        result = redact_event_data(data)
        # ID keys should pass through unchanged
        assert result["run_id"] == data["run_id"]
        assert result["approval_id"] == data["approval_id"]
        assert result["type"] == "test_event"
        assert result["status"] == "running"
        assert result["agent_name"] == "max"
        assert result["model_name"] == "gpt-4"

    def test_generic_string_fields_redacted(self) -> None:
        """All non-ID string values get redacted — not just a field allowlist."""
        data = {
            "tool_args": "api_key=supersecretvalue12345",
            "command": "password=hunter2longpasswordvalue",
            "event_data": "sk-abcdefghijklmnopqrstuvwxyz1234567890abc",
            "message": "Bearer abcdefghijklmnopqrstuvwxyz0123456789token",
            "response_preview": "AKIAIOSFODNN7EXAMPLE key here",
        }
        result = redact_event_data(data)
        assert "REDACTED" in result["tool_args"]
        assert "REDACTED" in result["command"]
        assert "REDACTED" in result["event_data"]
        assert "REDACTED" in result["message"]
        assert "REDACTED" in result["response_preview"]

    def test_nested_dict(self) -> None:
        data = {"data": {"content": "api_key=supersecretvalue12345"}}
        result = redact_event_data(data)
        assert "REDACTED" in result["data"]["content"]

    def test_nested_tool_args_dict(self) -> None:
        """Nested dicts with tool_args.command carry redaction through."""
        data = {"tool_args": {"command": "api_key=supersecretvalue12345"}}
        result = redact_event_data(data)
        assert "REDACTED" in result["tool_args"]["command"]

    def test_list_values(self) -> None:
        data = {"items": [{"content": "sk-abcdefghijklmnopqrstuvwxyz1234567890abc"}]}
        result = redact_event_data(data)
        assert "REDACTED" in result["items"][0]["content"]

    def test_non_dict_passthrough(self) -> None:
        assert redact_event_data("plain text") == "plain text"
        assert redact_event_data(42) == 42

    def test_jwt_in_event_data_redacted(self) -> None:
        """JWT tokens in generic event fields are masked."""
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        data = {"token_data": jwt}
        result = redact_event_data(data)
        assert "JWT_REDACTED" in result["token_data"]

    def test_pem_in_event_data_redacted(self) -> None:
        """PEM blocks in generic event fields are masked."""
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----"
        data = {"key_material": pem}
        result = redact_event_data(data)
        assert "REDACTED" in result["key_material"]

    def test_uuid_in_event_data_preserved(self) -> None:
        """UUID values in ID keys should not be altered."""
        uuid_val = "550e8400-e29b-41d4-a716-446655440000"
        data = {"run_id": uuid_val}
        result = redact_event_data(data)
        assert result["run_id"] == uuid_val

    def test_plain_string_in_non_id_field_unchanged_when_no_secrets(self) -> None:
        """Non-ID fields with no secret patterns still get passed through redact()."""
        data = {"description": "A normal description without secrets"}
        result = redact_event_data(data)
        assert result["description"] == "A normal description without secrets"


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
