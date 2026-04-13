"""Security tests for OAuth state handling.

These tests specifically verify the security properties of the OAuth state
management, ensuring compliance with RFC 9700 and preventing common
PKCE implementation vulnerabilities.

Key security properties verified:
1. PKCE verifier is NOT exposed in URL (browser history, logs, referrers)
2. State tokens are opaque (not self-contained data)
3. State tokens are single-use (prevents replay attacks)
4. State tokens expire after TTL (prevents stale token attacks)
5. Unknown state tokens are rejected (prevents crafted attacks)
"""

import json
import time
from unittest.mock import patch

import pytest

from code_puppy.plugins.antigravity_oauth.oauth import (
    _CONTEXT_TTL,
    _cleanup_expired_contexts,
    _decode_state,
    _encode_state,
    _pending_contexts,
    _contexts_lock,
    PendingOAuthContext,
)


# ============================================================================
# STATE OPACITY TESTS (Verifier not in URL)
# ============================================================================


def test_state_token_is_opaque():
    """State token must not contain the verifier - prevents URL exposure."""
    verifier = "test_verifier_secret_12345"
    state = _encode_state(verifier, "project-123")
    
    # State should NOT contain the verifier directly
    assert verifier not in state
    
    # State should NOT be decodable as base64 containing verifier
    import base64
    try:
        decoded = base64.urlsafe_b64decode(state + "==")
        data = json.loads(decoded)
        assert "verifier" not in data, "Verifier should not be in state"
    except Exception:
        pass  # Expected - state should be opaque token


def test_state_token_not_json():
    """State token must be an opaque random string, not JSON data."""
    verifier = "test_verifier_123"
    state = _encode_state(verifier, "project-123")
    
    # Try to decode as base64 JSON - should fail
    import base64
    try:
        decoded = base64.urlsafe_b64decode(state + "==")
        json.loads(decoded)
        pytest.fail("State should not be decodable as JSON")
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        pass  # Expected


def test_verifier_not_in_browser_history():
    """SECURITY: Verifier must not appear in browser-accessible locations.
    
    This test ensures the verifier is NEVER in the state parameter that
    appears in URLs, which would expose it in:
    - Browser history
    - Server access logs
    - Referer headers
    - Network traces
    - Browser cache
    """
    verifier = "my_secret_verifier_do_not_expose"
    project_id = "my-sensitive-project-id"
    state = _encode_state(verifier, project_id)
    
    # The state string itself (what goes in URL) must not contain secrets
    assert verifier not in state
    assert project_id not in state
    
    # State should be short random-looking string (token_urlsafe format)
    # URL-safe base64 chars: A-Z, a-z, 0-9, -, _
    allowed_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    assert all(c in allowed_chars for c in state)


# ============================================================================
# STATE LOOKUP SECURITY TESTS
# ============================================================================


def test_unknown_state_rejected():
    """Unknown state tokens must be rejected - prevents crafted attacks."""
    with pytest.raises(ValueError, match="Unknown"):
        _decode_state("completely_fake_token_not_in_storage")


def test_state_cannot_be_reused():
    """State tokens must be one-time use - prevents replay attacks."""
    state = _encode_state("verifier_abc", "project_xyz")
    
    # First use succeeds
    verifier, project = _decode_state(state)
    assert verifier == "verifier_abc"
    assert project == "project_xyz"
    
    # Second use fails - already consumed
    with pytest.raises(ValueError, match="Unknown"):
        _decode_state(state)


def test_expired_state_rejected():
    """Expired state tokens must be rejected."""
    from code_puppy.plugins.antigravity_oauth import oauth as oauth_module
    
    state = _encode_state("verifier_123", "project_456")
    
    # Simulate expiration by patching TTL and time
    with patch.object(oauth_module, '_CONTEXT_TTL', 0):
        with patch('time.time', return_value=time.time() + 1):
            with pytest.raises(ValueError, match="Unknown|expired"):
                _decode_state(state)


# ============================================================================
# CONTEXT STORAGE INTERNALS TESTS
# ============================================================================


def test_pending_context_dataclass():
    """PendingOAuthContext correctly stores and expires data."""
    context = PendingOAuthContext(
        verifier="test_verifier",
        project_id="test_project"
    )
    
    assert context.verifier == "test_verifier"
    assert context.project_id == "test_project"
    assert not context.is_expired()  # Fresh context not expired


def test_pending_context_expiration_logic():
    """PendingOAuthContext correctly detects expiration."""
    # Create context with old timestamp
    old_time = time.time() - _CONTEXT_TTL - 1
    context = PendingOAuthContext(
        verifier="test",
        project_id="test",
        created_at=old_time
    )
    
    assert context.is_expired()


def test_context_cleanup_removes_expired():
    """_cleanup_expired_contexts removes only expired contexts."""
    # Clear any existing contexts
    with _contexts_lock:
        _pending_contexts.clear()
    
    # Add a fresh context
    fresh_state = _encode_state("fresh_verifier", "fresh_project")
    
    # Add an expired context directly (bypassing normal encode)
    expired_state = "expired_test_state_123"
    expired_time = time.time() - _CONTEXT_TTL - 1
    with _contexts_lock:
        _pending_contexts[expired_state] = PendingOAuthContext(
            verifier="expired_verifier",
            project_id="expired_project",
            created_at=expired_time
        )
    
    # Verify both exist
    with _contexts_lock:
        assert fresh_state in _pending_contexts
        assert expired_state in _pending_contexts
    
    # Run cleanup
    with _contexts_lock:
        _cleanup_expired_contexts()
    
    # Verify only expired was removed
    with _contexts_lock:
        assert fresh_state in _pending_contexts
        assert expired_state not in _pending_contexts
    
    # Cleanup: decode the fresh state to remove it
    _decode_state(fresh_state)


# ============================================================================
# THREAD SAFETY TESTS
# ============================================================================


def test_concurrent_encode_decode():
    """Context storage must be thread-safe for concurrent operations."""
    import threading
    
    errors = []
    states = []
    
    def encode_op():
        try:
            state = _encode_state("concurrent_verifier", "concurrent_project")
            states.append(state)
        except Exception as e:
            errors.append(f"encode: {e}")
    
    def decode_op():
        try:
            # Try to decode a state (may fail if already consumed)
            state = _encode_state("decode_test_verifier", "decode_test_project")
            _decode_state(state)
        except ValueError as e:
            if "Unknown" not in str(e):
                errors.append(f"decode: {e}")
        except Exception as e:
            errors.append(f"decode: {e}")
    
    # Run concurrent operations
    threads = []
    for _ in range(10):
        t = threading.Thread(target=encode_op)
        threads.append(t)
        t = threading.Thread(target=decode_op)
        threads.append(t)
    
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # No errors should occur
    assert not errors, f"Thread errors: {errors}"
    
    # Cleanup: decode all states we created
    for state in states:
        try:
            _decode_state(state)
        except ValueError:
            pass  # May already be consumed by other thread


# ============================================================================
# INTEGRATION SECURITY TESTS
# ============================================================================


def test_full_flow_verifier_never_exposed():
    """Full OAuth flow: verifier never appears in any URL-accessible location."""
    from code_puppy.plugins.antigravity_oauth.oauth import (
        build_authorization_url,
        prepare_oauth_context,
        assign_redirect_uri,
    )
    
    # Prepare context (generates verifier)
    context = prepare_oauth_context()
    assign_redirect_uri(context, 51121)
    
    # Build URL (state token embedded in URL)
    project_id = "my-secret-project-123"
    url = build_authorization_url(context, project_id)
    
    # The verifier must NOT appear in the URL
    assert context.code_verifier not in url
    assert project_id not in url
    
    # The state parameter in URL should be opaque
    from urllib.parse import parse_qs, urlparse
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    state = params["state"][0]
    
    # State should NOT contain the verifier
    assert context.code_verifier not in state
    
    # But decoding the state should give us the verifier
    decoded_verifier, decoded_project = _decode_state(state)
    assert decoded_verifier == context.code_verifier
    assert decoded_project == project_id


def test_state_token_format():
    """State tokens are properly formatted as URL-safe tokens."""
    state = _encode_state("verifier", "project")
    
    # Should be URL-safe base64 (no padding)
    assert "=" not in state
    assert "+" not in state
    assert "/" not in state
    
    # Should only contain URL-safe characters
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    assert all(c in allowed for c in state)


def test_ttl_is_reasonable():
    """Context TTL should be reasonable (not too short, not too long)."""
    # 10 minutes is reasonable for OAuth flow
    assert _CONTEXT_TTL == 600
    # Should be at least 5 minutes
    assert _CONTEXT_TTL >= 300
    # Should be at most 30 minutes (too long increases risk)
    assert _CONTEXT_TTL <= 1800
