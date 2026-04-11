"""Tests for the security test helper itself."""

import pytest

from tests._helpers.security import (
    SensitiveDataFound,
    assert_no_sensitive_data,
    scan_for_sensitive_data,
)


class TestAssertNoSensitiveData:
    """Positive and negative tests for the credential scanner."""

    def test_clean_text_passes(self):
        assert_no_sensitive_data("This is a normal log message with no secrets.")

    def test_empty_string_passes(self):
        assert_no_sensitive_data("")

    def test_none_like_empty_passes(self):
        # Empty string should pass (no content to scan)
        assert_no_sensitive_data("")

    def test_openai_key_detected(self):
        text = "Using API key: sk-abc123def456ghi789jkl012mno345pqr678stu"
        with pytest.raises(SensitiveDataFound, match="OpenAI API Key"):
            assert_no_sensitive_data(text)

    def test_anthropic_key_detected(self):
        text = "Key: sk-ant-abc123def456ghi789jkl012mno345pqr678stu901vwx"
        with pytest.raises(SensitiveDataFound, match="Anthropic API Key"):
            assert_no_sensitive_data(text)

    def test_github_token_detected(self):
        text = "token=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklm"
        with pytest.raises(SensitiveDataFound, match="GitHub Token"):
            assert_no_sensitive_data(text)

    def test_bearer_token_detected(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig"
        with pytest.raises(SensitiveDataFound, match="Bearer Token|JSON Web Token"):
            assert_no_sensitive_data(text)

    def test_password_assignment_detected(self):
        text = 'password="SuperSecret123!"'
        with pytest.raises(SensitiveDataFound, match="Password Assignment"):
            assert_no_sensitive_data(text)

    def test_private_key_header_detected(self):
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAK..."
        with pytest.raises(SensitiveDataFound, match="Private Key"):
            assert_no_sensitive_data(text)

    def test_aws_access_key_detected(self):
        text = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
        with pytest.raises(SensitiveDataFound, match="AWS Access Key"):
            assert_no_sensitive_data(text)

    def test_database_connection_string_detected(self):
        text = "DATABASE_URL=postgres://admin:s3cret@db.example.com:5432/mydb"
        with pytest.raises(SensitiveDataFound, match="Database Connection"):
            assert_no_sensitive_data(text)

    def test_jwt_detected(self):
        text = "token: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        with pytest.raises(SensitiveDataFound, match="JSON Web Token"):
            assert_no_sensitive_data(text)

    def test_generic_api_key_assignment_detected(self):
        text = 'api_key = "abcdef1234567890abcdef"'
        with pytest.raises(SensitiveDataFound, match="Generic API Key"):
            assert_no_sensitive_data(text)

    def test_context_in_error_message(self):
        text = "sk-abc123def456ghi789jkl012mno345pqr678stu"
        with pytest.raises(SensitiveDataFound, match="agent run #42") as exc_info:
            assert_no_sensitive_data(text, context="agent run #42")
        assert exc_info.value.context == "agent run #42"

    def test_extra_patterns(self):
        text = "my-custom-secret-XYZ123ABC456"
        # Clean without extra pattern
        assert_no_sensitive_data(text)
        # Detected with extra pattern
        with pytest.raises(SensitiveDataFound, match="Custom Secret"):
            assert_no_sensitive_data(
                text,
                extra_patterns=[("Custom Secret", r"my-custom-secret-[A-Z0-9]+")],
            )

    def test_findings_attribute(self):
        text = "sk-abc123def456ghi789jkl012mno345pqr678stu"
        with pytest.raises(SensitiveDataFound) as exc_info:
            assert_no_sensitive_data(text)
        assert len(exc_info.value.findings) >= 1
        labels = [f[0] for f in exc_info.value.findings]
        assert "OpenAI API Key" in labels


class TestScanForSensitiveData:
    """Tests for the non-throwing scan variant."""

    def test_clean_returns_empty(self):
        assert scan_for_sensitive_data("Normal log output") == []

    def test_empty_returns_empty(self):
        assert scan_for_sensitive_data("") == []

    def test_finds_openai_key(self):
        findings = scan_for_sensitive_data(
            "key: sk-abc123def456ghi789jkl012mno345pqr678stu"
        )
        assert len(findings) >= 1
        labels = [f[0] for f in findings]
        assert "OpenAI API Key" in labels

    def test_multiple_findings(self):
        text = (
            "api_key=sk-abc123def456ghi789jkl012mno345pqr678stu\n"
            "password=MySuperSecret123"
        )
        findings = scan_for_sensitive_data(text)
        assert len(findings) >= 2

    def test_extra_patterns_work(self):
        findings = scan_for_sensitive_data(
            "CUSTOM_TOKEN_abc123",
            extra_patterns=[("Custom", r"CUSTOM_TOKEN_\w+")],
        )
        assert len(findings) == 1
        assert findings[0][0] == "Custom"


class TestSensitiveDataFoundError:
    """Tests for the exception class itself."""

    def test_is_assertion_error(self):
        err = SensitiveDataFound([("Test", "value")], context="ctx")
        assert isinstance(err, AssertionError)

    def test_redacts_long_matches(self):
        err = SensitiveDataFound(
            [("Key", "sk-abc123def456ghi789jkl012mno345pqr678stu")]
        )
        msg = str(err)
        # Should NOT contain the full key
        assert "sk-abc123def456ghi789jkl012mno345pqr678stu" not in msg
        # Should contain partial redaction
        assert "..." in msg

    def test_short_match_redaction(self):
        err = SensitiveDataFound([("Short", "abc123")])
        msg = str(err)
        assert "abc1****" in msg
