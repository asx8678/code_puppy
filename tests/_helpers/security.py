"""Security test helpers — scan outputs for accidentally leaked credentials.

Inspired by ruflo's ``testing/helpers/assertions.ts:assertNoSensitiveDataLogged``.
Ported to Python with regex-based pattern matching tuned for LLM-agent output.

Usage::

    from tests._helpers.security import assert_no_sensitive_data

    def test_log_output_is_clean(capsys):
        run_my_feature()
        captured = capsys.readouterr()
        assert_no_sensitive_data(captured.out)
        assert_no_sensitive_data(captured.err)

    # Or in bulk:
    assert_no_sensitive_data(log_text, context="agent run #42")
"""

import re
from dataclasses import dataclass

# ── Pattern library ──────────────────────────────────────────────────────────
#
# Each pattern has: compiled regex, human-readable label, and optional notes.
# Patterns are designed to minimize false positives on normal prose while
# catching real credential leaks.


@dataclass(frozen=True)
class _SensitivePattern:
    """A single sensitive-data detection pattern."""

    label: str
    regex: re.Pattern[str]
    notes: str = ""


# Ordered roughly by severity / frequency of occurrence.
_PATTERNS: tuple[_SensitivePattern, ...] = (
    # ── API keys & tokens ────────────────────────────────────────────────
    _SensitivePattern(
        label="AWS Access Key",
        regex=re.compile(r"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])"),
        notes="AWS access key IDs always start with AKIA",
    ),
    _SensitivePattern(
        label="AWS Secret Key",
        regex=re.compile(r"(?<![A-Za-z0-9/+=])[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])"),
        notes="40-char base64 — only flagged near 'aws' context",
    ),
    _SensitivePattern(
        label="OpenAI API Key",
        regex=re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
        notes="OpenAI keys start with sk-",
    ),
    _SensitivePattern(
        label="Anthropic API Key",
        regex=re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
        notes="Anthropic keys start with sk-ant-",
    ),
    _SensitivePattern(
        label="GitHub Token",
        regex=re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,}"),
        notes="GitHub PATs: ghp_, gho_, ghu_, ghs_, ghr_",
    ),
    _SensitivePattern(
        label="Generic Bearer Token",
        regex=re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{20,}", re.IGNORECASE),
        notes="Authorization: Bearer <token>",
    ),
    _SensitivePattern(
        label="Generic API Key Assignment",
        regex=re.compile(
            r"""(?:api[_-]?key|api[_-]?secret|access[_-]?token|secret[_-]?key)"""
            r"""\s*[:=]\s*['"]?[A-Za-z0-9._~+/=-]{16,}['"]?""",
            re.IGNORECASE,
        ),
        notes="key=value patterns for common credential variable names",
    ),
    # ── Passwords ────────────────────────────────────────────────────────
    _SensitivePattern(
        label="Password Assignment",
        regex=re.compile(
            r"""(?:password|passwd|pwd)\s*[:=]\s*['"]?[^\s'"]{8,}['"]?""",
            re.IGNORECASE,
        ),
        notes="password= or password: with a value",
    ),
    # ── Private keys ─────────────────────────────────────────────────────
    _SensitivePattern(
        label="Private Key Header",
        regex=re.compile(r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----"),
        notes="PEM-encoded private key block",
    ),
    # ── Connection strings ───────────────────────────────────────────────
    _SensitivePattern(
        label="Database Connection String",
        regex=re.compile(
            r"(?:postgres|mysql|mongodb|redis)://[^@\s]+:[^@\s]+@",
            re.IGNORECASE,
        ),
        notes="protocol://user:password@host patterns",
    ),
    # ── JWTs ─────────────────────────────────────────────────────────────
    _SensitivePattern(
        label="JSON Web Token",
        regex=re.compile(
            r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
        ),
        notes="Base64-encoded JWT (header.payload.signature)",
    ),
)


class SensitiveDataFound(AssertionError):
    """Raised by :func:`assert_no_sensitive_data` when credentials are detected.

    Attributes:
        findings: List of ``(label, matched_text_snippet)`` tuples.
        context: Optional context string passed by the caller.
    """

    def __init__(
        self,
        findings: list[tuple[str, str]],
        context: str | None = None,
    ) -> None:
        self.findings = findings
        self.context = context
        lines = [f"Sensitive data detected{f' ({context})' if context else ''}:"]
        for label, snippet in findings:
            # Redact the middle of the matched text to avoid leaking in test output
            redacted = snippet[:6] + "..." + snippet[-4:] if len(snippet) > 16 else snippet[:4] + "****"
            lines.append(f"  - {label}: {redacted}")
        super().__init__("\n".join(lines))


def assert_no_sensitive_data(
    text: str,
    *,
    context: str | None = None,
    extra_patterns: list[tuple[str, str]] | None = None,
) -> None:
    """Assert that *text* contains no leaked credentials or secrets.

    Scans *text* against a built-in library of credential patterns.
    Raises :class:`SensitiveDataFound` (an ``AssertionError`` subclass)
    on the first match.

    Args:
        text: The string to scan (log output, HTTP response body, etc.).
        context: Optional label included in the error message for debugging.
        extra_patterns: Additional ``(label, regex_string)`` pairs to check.

    Raises:
        SensitiveDataFound: If any pattern matches.
    """
    if not text:
        return

    findings: list[tuple[str, str]] = []

    for pat in _PATTERNS:
        match = pat.regex.search(text)
        if match:
            findings.append((pat.label, match.group()))

    if extra_patterns:
        for label, regex_str in extra_patterns:
            match = re.search(regex_str, text)
            if match:
                findings.append((label, match.group()))

    if findings:
        raise SensitiveDataFound(findings, context=context)


def scan_for_sensitive_data(
    text: str,
    *,
    extra_patterns: list[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    """Non-throwing variant: return list of ``(label, snippet)`` findings.

    Useful for logging/reporting without halting tests.
    """
    if not text:
        return []

    findings: list[tuple[str, str]] = []

    for pat in _PATTERNS:
        match = pat.regex.search(text)
        if match:
            findings.append((pat.label, match.group()))

    if extra_patterns:
        for label, regex_str in extra_patterns:
            match = re.search(regex_str, text)
            if match:
                findings.append((label, match.group()))

    return findings


__all__ = [
    "assert_no_sensitive_data",
    "scan_for_sensitive_data",
    "SensitiveDataFound",
]
