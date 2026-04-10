"""
Basic tests for ChatGPT OAuth plugin.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from code_puppy.callbacks import get_callbacks
from code_puppy.plugins.chatgpt_oauth import config, utils


def test_config_paths():
    """Test configuration path helpers."""
    token_path = config.get_token_storage_path()
    assert token_path.name == "chatgpt_oauth.json"
    # XDG paths use "code_puppy" (without dot) in ~/.local/share or ~/.config
    assert "code_puppy" in str(token_path)

    config_dir = config.get_config_dir()
    # Default is ~/.code_puppy; XDG paths only used when XDG env vars are set
    assert config_dir.name in ("code_puppy", ".code_puppy")

    chatgpt_models = config.get_chatgpt_models_path()
    assert chatgpt_models.name == "chatgpt_models.json"


def test_oauth_config():
    """Test OAuth configuration values."""
    assert config.CHATGPT_OAUTH_CONFIG["issuer"] == "https://auth.openai.com"
    assert config.CHATGPT_OAUTH_CONFIG["client_id"] == "app_EMoamEEZ73f0CkXaXp7hrann"
    assert config.CHATGPT_OAUTH_CONFIG["prefix"] == "chatgpt-"


def test_jwt_parsing_with_nested_org():
    """Test JWT parsing with nested organization structure like the user's payload."""
    # This simulates the user's JWT payload structure
    mock_claims = {
        "aud": ["app_EMoamEEZ73f0CkXaXp7hrann"],
        "auth_provider": "google",
        "email": "mike.pfaf fenberger@gmail.com",
        "https://api.openai.com/auth": {
            "chatgpt_account_id": "d1844a91-9aac-419b-903e-f6a99c76f163",
            "organizations": [
                {
                    "id": "org-iydWjnSxSr51VuYhDVMDte5",
                    "is_default": True,
                    "role": "owner",
                    "title": "Personal",
                }
            ],
            "groups": ["api-data-sharing-incentives-program", "verified-organization"],
        },
        "sub": "google-oauth2|107692466937587138174",
    }

    # Test the org extraction logic
    auth_claims = mock_claims.get("https://api.openai.com/auth", {})
    organizations = auth_claims.get("organizations", [])

    org_id = None
    if organizations:
        default_org = next(
            (org for org in organizations if org.get("is_default")), organizations[0]
        )
        org_id = default_org.get("id")

    assert org_id == "org-iydWjnSxSr51VuYhDVMDte5"

    # Test fallback to top-level org_id (should not happen in this case)
    if not org_id:
        org_id = mock_claims.get("organization_id")

    assert org_id == "org-iydWjnSxSr51VuYhDVMDte5"
    assert config.CHATGPT_OAUTH_CONFIG["required_port"] == 1455


def test_code_verifier_generation():
    """Test PKCE code verifier generation."""
    verifier = utils._generate_code_verifier()
    assert isinstance(verifier, str)
    assert len(verifier) > 50  # Should be long


def test_code_challenge_computation():
    """Test PKCE code challenge computation."""
    verifier = "test_verifier_string"
    challenge = utils._compute_code_challenge(verifier)
    assert isinstance(challenge, str)
    assert len(challenge) > 0
    # Should be URL-safe base64
    assert all(
        c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        for c in challenge
    )


def test_prepare_oauth_context():
    """Test OAuth context preparation."""
    context = utils.prepare_oauth_context()
    assert context.state
    assert context.code_verifier
    assert context.code_challenge
    assert context.created_at > 0
    assert context.redirect_uri is None


def test_assign_redirect_uri():
    """Test redirect URI assignment."""
    context = utils.prepare_oauth_context()
    redirect_uri = utils.assign_redirect_uri(context, 1455)
    assert redirect_uri == "http://localhost:1455/auth/callback"
    assert context.redirect_uri == redirect_uri


def test_build_authorization_url():
    """Test authorization URL building."""
    context = utils.prepare_oauth_context()
    utils.assign_redirect_uri(context, 1455)
    auth_url = utils.build_authorization_url(context)

    assert auth_url.startswith("https://auth.openai.com/oauth/authorize?")
    assert "response_type=code" in auth_url
    assert "client_id=" in auth_url
    assert "redirect_uri=" in auth_url
    assert "code_challenge=" in auth_url
    assert "code_challenge_method=S256" in auth_url
    assert f"state={context.state}" in auth_url


def test_parse_jwt_claims():
    """Test JWT claims parsing."""
    # Valid JWT structure (header.payload.signature)
    import base64

    payload = base64.urlsafe_b64encode(json.dumps({"sub": "user123"}).encode()).decode()
    token = f"header.{payload}.signature"

    claims = utils.parse_jwt_claims(token)
    assert claims is not None
    assert claims["sub"] == "user123"

    # Invalid token
    assert utils.parse_jwt_claims("") is None
    assert utils.parse_jwt_claims("invalid") is None


def test_save_and_load_tokens(tmp_path):
    """Test token storage and retrieval."""
    with patch.object(
        utils, "get_token_storage_path", return_value=tmp_path / "tokens.json"
    ):
        tokens = {
            "access_token": "test_access",
            "refresh_token": "test_refresh",
            "api_key": "sk-test",
        }

        # Save tokens
        assert utils.save_tokens(tokens)

        # Load tokens
        loaded = utils.load_stored_tokens()
        assert loaded == tokens


def test_save_and_load_chatgpt_models(tmp_path):
    """Test ChatGPT models configuration."""
    with patch.object(
        utils, "get_chatgpt_models_path", return_value=tmp_path / "chatgpt_models.json"
    ):
        models = {
            "chatgpt-gpt-5.4": {
                "type": "chatgpt_oauth",
                "name": "gpt-5.4",
                "oauth_source": "chatgpt-oauth-plugin",
            }
        }

        # Save models
        assert utils.save_chatgpt_models(models)

        # Load models
        loaded = utils.load_chatgpt_models()
        assert loaded == models


def test_remove_chatgpt_models(tmp_path):
    """Test removal of ChatGPT models from config."""
    with patch.object(
        utils, "get_chatgpt_models_path", return_value=tmp_path / "chatgpt_models.json"
    ):
        models = {
            "chatgpt-gpt-5.4": {
                "type": "chatgpt_oauth",
                "oauth_source": "chatgpt-oauth-plugin",
            },
            "some-other-model": {
                "type": "other",
                "oauth_source": "other",
            },
        }
        utils.save_chatgpt_models(models)

        # Remove only ChatGPT models
        removed_count = utils.remove_chatgpt_models()
        assert removed_count == 1

        # Verify only ChatGPT model was removed
        remaining = utils.load_chatgpt_models()
        assert "chatgpt-gpt-5.4" not in remaining
        assert "some-other-model" in remaining


@patch("code_puppy.plugins.chatgpt_oauth.utils.requests.post")
def test_exchange_code_for_tokens(mock_post):
    """Test authorization code exchange."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "test_access",
        "refresh_token": "test_refresh",
        "id_token": "test_id",
    }
    mock_post.return_value = mock_response

    context = utils.prepare_oauth_context()
    utils.assign_redirect_uri(context, 1455)

    tokens = utils.exchange_code_for_tokens("test_code", context)
    assert tokens is not None
    assert tokens["access_token"] == "test_access"
    assert "last_refresh" in tokens


@patch("code_puppy.plugins.chatgpt_oauth.utils.requests.get")
def test_fetch_chatgpt_models(mock_get):
    """Test fetching models from ChatGPT Codex API."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    # New response format uses "models" key with "slug" field
    # Note: gpt-4o and gpt-3.5-turbo are blocked models and will be filtered out
    mock_response.json.return_value = {
        "models": [
            {"slug": "gpt-5.4"},
            {"slug": "gpt-5.3-codex"},
            {"slug": "o1-preview"},
            {"slug": "codex-mini"},
        ]
    }
    mock_get.return_value = mock_response

    models = utils.fetch_chatgpt_models("test_access_token", "test_account_id")
    assert models is not None
    # Required models always injected
    assert "gpt-5.4" in models
    assert "gpt-5.3-instant" in models
    # API-returned models present too (blocked models like gpt-4o are filtered)
    assert "gpt-5.4" in models
    assert "gpt-5.3-codex" in models
    assert "o1-preview" in models
    assert "codex-mini" in models
    # Blocked models should NOT be present
    assert "gpt-4o" not in models
    assert "gpt-3.5-turbo" not in models


@patch("code_puppy.plugins.chatgpt_oauth.utils.requests.get")
def test_fetch_chatgpt_models_fallback(mock_get):
    """Test that fetch_chatgpt_models returns default list on API failure."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = '{"detail":"Not Found"}'
    mock_get.return_value = mock_response

    models = utils.fetch_chatgpt_models("test_access_token", "test_account_id")
    assert models is not None
    # Should return default models (blocked models like gpt-5.2 are filtered out)
    assert "gpt-5.4" in models
    assert "gpt-5.3-instant" in models
    assert "gpt-5.3-codex-spark" in models
    assert "gpt-5.3-codex" in models
    # Blocked models should NOT be present
    assert "gpt-5.2-codex" not in models
    assert "gpt-5.2" not in models


def test_add_models_to_chatgpt_config(tmp_path):
    """Test adding models to chatgpt_models.json."""
    with patch.object(
        utils, "get_chatgpt_models_path", return_value=tmp_path / "chatgpt_models.json"
    ):
        models = ["gpt-5.4", "gpt-5.3-instant"]

        assert utils.add_models_to_extra_config(models)

        loaded = utils.load_chatgpt_models()
        assert "chatgpt-gpt-5.4" in loaded
        assert "chatgpt-gpt-5.3-instant" in loaded
        assert loaded["chatgpt-gpt-5.4"]["type"] == "chatgpt_oauth"
        assert loaded["chatgpt-gpt-5.4"]["name"] == "gpt-5.4"
        assert loaded["chatgpt-gpt-5.4"]["oauth_source"] == "chatgpt-oauth-plugin"


def test_no_shutdown_refresh_callback_registered():
    """Verify that shutdown callback is NOT registered (code_puppy-1vv).

    The shutdown refresh was removed because it could trigger unconditional
    token refresh attempts during exit, which is unnecessary and potentially
    problematic.
    """
    # Explicitly import to ensure the plugin's register_callbacks is loaded
    # before checking the registry (makes test order-independent)
    import importlib

    importlib.import_module("code_puppy.plugins.chatgpt_oauth.register_callbacks")

    shutdown_callbacks = get_callbacks("shutdown")
    # Get the module paths of registered callbacks
    callback_modules = []
    for cb in shutdown_callbacks:
        if hasattr(cb, "__module__"):
            callback_modules.append(cb.__module__)
        elif hasattr(cb, "__wrapped__") and hasattr(cb.__wrapped__, "__module__"):
            callback_modules.append(cb.__wrapped__.__module__)

    # No chatgpt_oauth callback should be registered for shutdown
    assert not any("chatgpt_oauth" in m for m in callback_modules), (
        "ChatGPT OAuth shutdown callback should not be registered"
    )


@patch("code_puppy.plugins.chatgpt_oauth.utils.requests.post")
def test_refresh_success_syncs_api_key(mock_post, tmp_path):
    """On successful refresh, api_key should be kept in sync with access_token.

    This ensures compatibility with code that expects api_key to be available.
    """
    with patch.object(
        utils, "get_token_storage_path", return_value=tmp_path / "tokens.json"
    ):
        # Pre-populate with tokens
        initial_tokens = {
            "access_token": "old_access_token",
            "refresh_token": "test_refresh",
            "api_key": "old_access_token",
            "account_id": "test_account",
        }
        utils.save_tokens(initial_tokens)

        # Mock successful refresh response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_access_token_123",
            "refresh_token": "new_refresh_token",
        }
        mock_post.return_value = mock_response

        # Refresh
        result = utils.refresh_access_token()

        assert result == "new_access_token_123"

        # Verify saved tokens have api_key synced
        saved = utils.load_stored_tokens()
        assert saved["access_token"] == "new_access_token_123"
        assert saved["api_key"] == "new_access_token_123"
        assert saved["refresh_token"] == "new_refresh_token"
        # account_id should be preserved
        assert saved["account_id"] == "test_account"


@patch("code_puppy.plugins.chatgpt_oauth.utils.requests.post")
def test_fatal_refresh_error_clears_tokens(mock_post, tmp_path):
    """Unrecoverable errors (401, invalid_grant) should clear token cache.

    This prevents the app from pretending the user is authenticated when
    the refresh token is dead.
    """
    with patch.object(
        utils, "get_token_storage_path", return_value=tmp_path / "tokens.json"
    ):
        # Pre-populate with tokens
        initial_tokens = {
            "access_token": "expired_token",
            "refresh_token": "dead_refresh_token",
            "api_key": "expired_token",
        }
        utils.save_tokens(initial_tokens)

        # Mock 401 Unauthorized response
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_post.return_value = mock_response

        # Refresh should fail and clear tokens
        result = utils.refresh_access_token()

        assert result is None
        # Token cache should be cleared
        assert utils.load_stored_tokens() is None
        assert not (tmp_path / "tokens.json").exists()


@patch("code_puppy.plugins.chatgpt_oauth.utils.requests.post")
def test_invalid_grant_clears_tokens(mock_post, tmp_path):
    """OAuth 'invalid_grant' error should clear token cache as unrecoverable."""
    with patch.object(
        utils, "get_token_storage_path", return_value=tmp_path / "tokens.json"
    ):
        # Pre-populate with tokens
        initial_tokens = {
            "access_token": "expired_token",
            "refresh_token": "revoked_token",
        }
        utils.save_tokens(initial_tokens)

        # Mock 400 with invalid_grant error
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "invalid_grant",
            "error_description": "The provided authorization grant is invalid",
        }
        mock_post.return_value = mock_response

        # Refresh should fail and clear tokens
        result = utils.refresh_access_token()

        assert result is None
        assert utils.load_stored_tokens() is None


@patch("code_puppy.plugins.chatgpt_oauth.utils.requests.post")
def test_token_expired_error_clears_tokens(mock_post, tmp_path):
    """OAuth 'token_expired' error should clear token cache as unrecoverable."""
    with patch.object(
        utils, "get_token_storage_path", return_value=tmp_path / "tokens.json"
    ):
        initial_tokens = {
            "access_token": "expired_token",
            "refresh_token": "expired_refresh",
        }
        utils.save_tokens(initial_tokens)

        # Mock 400 with token_expired error in description
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "invalid_request",
            "error_description": "The refresh token has expired",
        }
        mock_post.return_value = mock_response

        result = utils.refresh_access_token()

        assert result is None
        assert utils.load_stored_tokens() is None


@patch("code_puppy.plugins.chatgpt_oauth.utils.requests.post")
def test_transient_error_preserves_tokens(mock_post, tmp_path):
    """Transient errors (500, 502, timeout) should NOT clear token cache.

    These are server/network issues that may resolve on retry.
    """
    with patch.object(
        utils, "get_token_storage_path", return_value=tmp_path / "tokens.json"
    ):
        initial_tokens = {
            "access_token": "valid_token",
            "refresh_token": "valid_refresh",
            "api_key": "valid_token",
        }
        utils.save_tokens(initial_tokens)

        # Mock 500 Server Error
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        # Refresh should fail but NOT clear tokens
        result = utils.refresh_access_token()

        assert result is None
        # Token cache should be preserved for retry
        saved = utils.load_stored_tokens()
        assert saved is not None
        assert saved["access_token"] == "valid_token"
        assert saved["refresh_token"] == "valid_refresh"


@patch("code_puppy.plugins.chatgpt_oauth.utils.requests.post")
def test_rate_limit_error_preserves_tokens(mock_post, tmp_path):
    """HTTP 429 rate limit should NOT clear token cache."""
    with patch.object(
        utils, "get_token_storage_path", return_value=tmp_path / "tokens.json"
    ):
        initial_tokens = {
            "access_token": "valid_token",
            "refresh_token": "valid_refresh",
        }
        utils.save_tokens(initial_tokens)

        # Mock 429 Too Many Requests
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limited"
        mock_post.return_value = mock_response

        result = utils.refresh_access_token()

        assert result is None
        # Tokens should be preserved
        assert utils.load_stored_tokens() is not None


@patch("code_puppy.plugins.chatgpt_oauth.utils.requests.post")
def test_network_timeout_preserves_tokens(mock_post, tmp_path):
    """Network timeout should NOT clear token cache."""
    from requests.exceptions import Timeout

    with patch.object(
        utils, "get_token_storage_path", return_value=tmp_path / "tokens.json"
    ):
        initial_tokens = {
            "access_token": "valid_token",
            "refresh_token": "valid_refresh",
        }
        utils.save_tokens(initial_tokens)

        # Simulate timeout
        mock_post.side_effect = Timeout("Request timed out")

        result = utils.refresh_access_token()

        assert result is None
        # Tokens should be preserved
        saved = utils.load_stored_tokens()
        assert saved is not None
        assert saved["access_token"] == "valid_token"


@patch("code_puppy.plugins.chatgpt_oauth.utils.requests.post")
def test_connection_error_preserves_tokens(mock_post, tmp_path):
    """Connection error should NOT clear token cache."""
    from requests.exceptions import ConnectionError

    with patch.object(
        utils, "get_token_storage_path", return_value=tmp_path / "tokens.json"
    ):
        initial_tokens = {
            "access_token": "valid_token",
            "refresh_token": "valid_refresh",
        }
        utils.save_tokens(initial_tokens)

        # Simulate connection error
        mock_post.side_effect = ConnectionError("No route to host")

        result = utils.refresh_access_token()

        assert result is None
        # Tokens should be preserved
        assert utils.load_stored_tokens() is not None


def test_unrecoverable_error_detection():
    """Test the _is_unrecoverable_token_error helper."""
    # 401 is always unrecoverable
    mock_resp_401 = MagicMock()
    mock_resp_401.status_code = 401
    mock_resp_401.json.return_value = {}
    assert utils._is_unrecoverable_token_error(mock_resp_401) is True

    # 400 with invalid_grant is unrecoverable (OAuth style)
    mock_resp_invalid_grant = MagicMock()
    mock_resp_invalid_grant.status_code = 400
    mock_resp_invalid_grant.json.return_value = {
        "error": "invalid_grant",
        "error_description": "Bad grant",
    }
    assert utils._is_unrecoverable_token_error(mock_resp_invalid_grant) is True

    # 400 with token_expired in description is unrecoverable
    mock_resp_token_expired = MagicMock()
    mock_resp_token_expired.status_code = 400
    mock_resp_token_expired.json.return_value = {
        "error": "invalid_request",
        "error_description": "The token has expired",
    }
    assert utils._is_unrecoverable_token_error(mock_resp_token_expired) is True

    # 400 with nested API style error is unrecoverable
    mock_resp_nested = MagicMock()
    mock_resp_nested.status_code = 400
    mock_resp_nested.json.return_value = {
        "error": {
            "code": "token_expired",
            "message": "Could not validate your token, it may have expired",
        }
    }
    assert utils._is_unrecoverable_token_error(mock_resp_nested) is True

    # 400 with nested API style using invalid_grant code
    mock_resp_nested_grant = MagicMock()
    mock_resp_nested_grant.status_code = 400
    mock_resp_nested_grant.json.return_value = {
        "error": {
            "code": "invalid_grant",
            "message": "The authorization grant is invalid",
        }
    }
    assert utils._is_unrecoverable_token_error(mock_resp_nested_grant) is True

    # 500 is NOT unrecoverable
    mock_resp_500 = MagicMock()
    mock_resp_500.status_code = 500
    mock_resp_500.json.return_value = {"error": "server_error"}
    assert utils._is_unrecoverable_token_error(mock_resp_500) is False

    # 400 with unknown error is NOT unrecoverable
    mock_resp_unknown = MagicMock()
    mock_resp_unknown.status_code = 400
    mock_resp_unknown.json.return_value = {"error": "temporarily_unavailable"}
    assert utils._is_unrecoverable_token_error(mock_resp_unknown) is False

    # 400 with non-JSON body is NOT unrecoverable (unknown)
    mock_resp_nonjson = MagicMock()
    mock_resp_nonjson.status_code = 400
    mock_resp_nonjson.json.side_effect = ValueError("Not JSON")
    assert utils._is_unrecoverable_token_error(mock_resp_nonjson) is False


@patch("code_puppy.plugins.chatgpt_oauth.utils.requests.post")
def test_ambiguous_error_description_preserves_tokens(mock_post, tmp_path):
    """Ambiguous/transient error descriptions should NOT clear tokens.

    Only explicit unrecoverable phrases should trigger token clearing.
    Generic or ambiguous messages should be treated as transient.
    """
    with patch.object(
        utils, "get_token_storage_path", return_value=tmp_path / "tokens.json"
    ):
        # Pre-populate with tokens
        initial_tokens = {
            "access_token": "valid_token",
            "refresh_token": "valid_refresh",
        }
        utils.save_tokens(initial_tokens)

        # Mock 400 with ambiguous error description (not in allowlist)
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "error",
            "error_description": "An error occurred processing the request",
        }
        mock_post.return_value = mock_response

        # Refresh should fail but NOT clear tokens
        result = utils.refresh_access_token()

        assert result is None
        # Token cache should be preserved for retry
        saved = utils.load_stored_tokens()
        assert saved is not None
        assert saved["access_token"] == "valid_token"
        assert saved["refresh_token"] == "valid_refresh"


def test_clear_stored_tokens(tmp_path):
    """Test that clear_stored_tokens safely removes the token file."""
    token_path = tmp_path / "tokens.json"
    with patch.object(utils, "get_token_storage_path", return_value=token_path):
        # Save some tokens first
        utils.save_tokens({"access_token": "test", "refresh_token": "test"})
        assert token_path.exists()

        # Clear them
        assert utils.clear_stored_tokens() is True
        assert not token_path.exists()

        # After clearing, load should return None
        assert utils.load_stored_tokens() is None

        # Clearing when file doesn't exist should still succeed
        assert utils.clear_stored_tokens() is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
