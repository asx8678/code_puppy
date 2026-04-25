"""Central redactor for Code Puppy API boundary outputs.

Applies secret-masking and length-truncation to data before it leaves
the process via HTTP, WebSocket, or log boundaries.  Internal agent /
tool data is *not* redacted — only values exposed at the boundary.

Usage::

    from code_puppy.api.redactor import redact, truncate, sanitize_traceback
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Secret-pattern redaction
# ---------------------------------------------------------------------------

# Patterns that look like secrets / credentials.  Order matters: more
# specific patterns first.
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # AWS access-key IDs (AKIA…)
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AKIA***REDACTED***"),
    # AWS secret keys (40-char base64-ish after known key names)
    (
        re.compile(r"(?i)(aws_secret_access_key|secret_key)\s*[=:]\s*\S{20,}"),
        r"\1=***REDACTED***",
    ),
    # Generic API key / token patterns (sk-*, ghp_*, github_pat_*, etc.)
    (re.compile(r"\bsk-[a-zA-Z0-9]{20,}"), "sk-***REDACTED***"),
    (re.compile(r"\bghp_[a-zA-Z0-9]{36,}"), "ghp_***REDACTED***"),
    (re.compile(r"\bgithub_pat_[a-zA-Z0-9_]{20,}"), "github_pat_***REDACTED***"),
    (re.compile(r"\bglpat-[a-zA-Z0-9\-]{20,}"), "glpat-***REDACTED***"),
    (re.compile(r"\bxox[bpsa]-[a-zA-Z0-9\-]{20,}"), "xox-***REDACTED***"),
    # Bearer / Authorization header values
    (
        re.compile(r"(?i)(?:bearer|authorization)\s+[a-zA-Z0-9\-._~+/]+=*"),
        "Bearer ***REDACTED***",
    ),
    # JWT tokens — three base64url segments separated by dots
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
        "***JWT_REDACTED***",
    ),
    # PEM-encoded private keys (RSA, EC, DSA, etc.)
    (
        re.compile(
            r"-----BEGIN\s+(?:RSA\s+)?(?:PRIVATE\s+KEY|EC\s+PRIVATE\s+KEY|DSA\s+PRIVATE\s+KEY|OPENSSH\s+PRIVATE\s+KEY)-----"
        ),
        "-----BEGIN ***REDACTED*** KEY-----",
    ),
    (
        re.compile(
            r"-----END\s+(?:RSA\s+)?(?:PRIVATE\s+KEY|EC\s+PRIVATE\s+KEY|DSA\s+PRIVATE\s+KEY|OPENSSH\s+PRIVATE\s+KEY)-----"
        ),
        "-----END ***REDACTED*** KEY-----",
    ),
    # Generic "api_key=XXX" or "api-key: XXX" patterns
    (
        re.compile(
            r"(?i)(api[_-]?key|apikey|access[_-]?token|secret|password|credential)\s*[=:]\s*\S{8,}"
        ),
        r"\1=***REDACTED***",
    ),
    # Long hex tokens (64+ chars) that look like bearer tokens
    (re.compile(r"\b[0-9a-f]{64,}\b"), "***HEX_TOKEN_REDACTED***"),
]

# Maximum length for redacted output
_DEFAULT_MAX_LENGTH = 500


def redact(text: Any, *, max_length: int = _DEFAULT_MAX_LENGTH) -> str:
    """Redact known secret patterns and truncate *text*.

    Converts *text* to ``str``, applies regex-based secret masking, then
    truncates to *max_length* characters with a trailing ellipsis if
    needed.
    """
    if text is None:
        return ""
    value = str(text)
    for pattern, replacement in _SECRET_PATTERNS:
        value = pattern.sub(replacement, value)
    return truncate(value, max_length=max_length)


def truncate(text: str, *, max_length: int = _DEFAULT_MAX_LENGTH) -> str:
    """Truncate *text* to *max_length* with a trailing ellipsis."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"


# ---------------------------------------------------------------------------
# Traceback sanitization
# ---------------------------------------------------------------------------

_MAX_TRACEBACK_FRAMES = 5
_MAX_FRAME_LINE_LENGTH = 120


def sanitize_traceback(tb_str: str) -> str:
    """Sanitize a full traceback string for safe emission.

    Keeps only the last ``_MAX_TRACEBACK_FRAMES`` stack frames, strips
    local variable reprs, and redacts any secret patterns.
    """
    if not tb_str:
        return ""

    lines = tb_str.strip().splitlines()
    # Find stack-frame lines (starting with "  File ")
    frame_indices = [i for i, line in enumerate(lines) if line.startswith("  File ")]

    # Keep only the last N frames
    if len(frame_indices) > _MAX_TRACEBACK_FRAMES:
        keep_from = frame_indices[-_MAX_TRACEBACK_FRAMES]
        kept_lines = ["  ... (truncated) ..."]
        kept_lines.extend(lines[keep_from:])
    else:
        kept_lines = lines

    # Truncate long lines within frames
    sanitized = []
    for line in kept_lines:
        if len(line) > _MAX_FRAME_LINE_LENGTH:
            sanitized.append(line[: _MAX_FRAME_LINE_LENGTH - 1] + "…")
        else:
            sanitized.append(line)

    result = "\n".join(sanitized)
    return redact(result, max_length=2000)


# ---------------------------------------------------------------------------
# Event/status/approval boundary helpers
# ---------------------------------------------------------------------------

# Structural keys that are identifiers / metadata — never redacted.
_ID_KEYS = frozenset(
    {
        "run_id",
        "approval_id",
        "prompt_id",
        "id",
        "type",
        "status",
        "agent_name",
        "model_name",
        "created_at",
        "started_at",
        "ended_at",
        "border_style",
        "puppy_name",
    }
)


def redact_event_data(data: Any) -> Any:
    """Redact event data before emitting over WebSocket / HTTP.

    Applies :func:`redact` to **all** string leaf values traversed in
    nested dicts and lists, except for structural identifier keys in
    ``_ID_KEYS`` (UUIDs, timestamps, type tags, etc.) which are left
    untouched.  This ensures that secret-like content in *any* field —
    not just a small allowlist — is masked at the boundary.
    """
    if isinstance(data, str):
        return redact(data)
    if not isinstance(data, dict):
        if isinstance(data, list):
            return [redact_event_data(item) for item in data]
        return data

    result = {}
    for key, val in data.items():
        if key in _ID_KEYS:
            # Identifier / metadata keys are structural — keep as-is.
            result[key] = val
        elif isinstance(val, str):
            result[key] = redact(val)
        elif isinstance(val, dict):
            result[key] = redact_event_data(val)
        elif isinstance(val, list):
            result[key] = [redact_event_data(item) for item in val]
        else:
            result[key] = val
    return result


def redact_approval_dict(approval: dict) -> dict:
    """Redact an approval dict for API/WebSocket emission."""
    _fields = ("content", "preview", "feedback")
    result = dict(approval)
    for field in _fields:
        if field in result and isinstance(result[field], str):
            result[field] = redact(result[field], max_length=200)
    return result


def redact_status_payload(status: dict) -> dict:
    """Redact a runtime status payload for API emission.

    Redacts:
    - current_run sensitive fields
    - recent_runs sensitive fields
    - pending_approvals content/preview/feedback
    """
    result = dict(status)

    # Redact current_run
    if result.get("current_run") and isinstance(result["current_run"], dict):
        result["current_run"] = redact_run_dict(result["current_run"])

    # Redact recent_runs
    if isinstance(result.get("recent_runs"), list):
        result["recent_runs"] = [
            redact_run_dict(r) if isinstance(r, dict) else r
            for r in result["recent_runs"]
        ]

    # Redact pending_approvals
    if isinstance(result.get("pending_approvals"), list):
        result["pending_approvals"] = [
            redact_approval_dict(a) if isinstance(a, dict) else a
            for a in result["pending_approvals"]
        ]

    return result


def redact_run_dict(run: dict) -> dict:
    """Redact sensitive fields in a run dict."""
    _fields = ("prompt_preview", "output_preview", "error")
    result = dict(run)
    for field in _fields:
        if field in result and result[field] is not None:
            result[field] = redact(result[field], max_length=300)
    return result
