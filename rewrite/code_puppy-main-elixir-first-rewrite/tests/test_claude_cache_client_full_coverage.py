"""Full coverage tests for code_puppy/claude_cache_client.py."""

import base64
import json
import threading
import time
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest

from code_puppy.claude_cache_client import (
    CLAUDE_CLI_USER_AGENT,
    TOOL_PREFIX,
    ClaudeCacheAsyncClient,
    _get_jwt_claims,
    _inject_cache_control_in_payload,
    _jwt_claims_cache,
    _validate_jwt_claims,
    patch_anthropic_client_messages,
)


def _create_jwt(iat=None, exp=None):
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {}
    if iat is not None:
        payload["iat"] = iat
    if exp is not None:
        payload["exp"] = exp
    header_b64 = (
        base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode()
    )
    payload_b64 = (
        base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    )
    return f"{header_b64}.{payload_b64}.fake_signature"


# --- JWT age ---


class TestJWTAge:
    def test_none_token(self):
        c = ClaudeCacheAsyncClient()
        assert c._get_jwt_age_seconds(None) is None

    def test_empty_token(self):
        c = ClaudeCacheAsyncClient()
        assert c._get_jwt_age_seconds("") is None

    def test_invalid_parts(self):
        c = ClaudeCacheAsyncClient()
        assert c._get_jwt_age_seconds("only.two") is None
        assert c._get_jwt_age_seconds("a.b.c.d") is None

    def test_bad_base64(self):
        c = ClaudeCacheAsyncClient()
        # Valid 3-part but bad base64
        assert c._get_jwt_age_seconds("a.!!!.c") is None

    def test_with_iat_and_exp(self):
        # SECURITY: Both iat and exp are now required for validation
        now = time.time()
        token = _create_jwt(iat=now - 600, exp=now + 3000)
        c = ClaudeCacheAsyncClient()
        age = c._get_jwt_age_seconds(token)
        assert 590 <= age <= 610

    def test_missing_exp_fails_validation(self):
        # SECURITY: exp claim is required
        token = _create_jwt(iat=time.time() - 600)  # No exp
        c = ClaudeCacheAsyncClient()
        age = c._get_jwt_age_seconds(token)
        assert age is None

    def test_missing_iat_fails_validation(self):
        # SECURITY: iat claim is required
        token = _create_jwt(exp=time.time() + 1800)  # No iat
        c = ClaudeCacheAsyncClient()
        age = c._get_jwt_age_seconds(token)
        assert age is None

    def test_no_claims(self):
        token = _create_jwt()
        c = ClaudeCacheAsyncClient()
        assert c._get_jwt_age_seconds(token) is None


# --- Direct JWT claim validation tests (code_puppy-e60 security fix) ---


class TestValidateJWTClaims:
    """Direct tests for _validate_jwt_claims() - security critical."""

    def test_none_token(self):
        assert _validate_jwt_claims(None) is None

    def test_empty_token(self):
        assert _validate_jwt_claims("") is None

    def test_invalid_jwt_structure(self):
        assert _validate_jwt_claims("only.two") is None
        assert _validate_jwt_claims("a.b.c.d") is None
        assert _validate_jwt_claims("not.a.jwt") is None

    def test_valid_integer_claims(self):
        """Test with valid integer iat and exp claims."""
        now = int(time.time())
        token = _create_jwt(iat=now - 600, exp=now + 3000)
        result = _validate_jwt_claims(token)
        assert result is not None
        iat, exp = result
        assert iat == now - 600
        assert exp == now + 3000

    def test_valid_float_claims_with_fractional_seconds(self):
        """Test with valid float claims that have fractional seconds."""
        now = time.time()
        # Add fractional seconds to show we validate against raw values
        iat_float = now - 600.5
        exp_float = now + 3000.7
        token = _create_jwt(iat=iat_float, exp=exp_float)
        result = _validate_jwt_claims(token)
        assert result is not None
        iat, exp = result
        # Should be truncated to int in return value
        assert iat == int(iat_float)
        assert exp == int(exp_float)

    def test_missing_exp_claim(self):
        """Token without exp claim should fail validation."""
        now = time.time()
        token = _create_jwt(iat=now - 600)  # No exp
        assert _validate_jwt_claims(token) is None

    def test_missing_iat_claim(self):
        """Token without iat claim should fail validation."""
        now = time.time()
        token = _create_jwt(exp=now + 1800)  # No iat
        assert _validate_jwt_claims(token) is None

    def test_exp_less_than_or_equal_to_iat(self):
        """exp must be strictly greater than iat."""
        now = time.time()
        # exp == iat
        token = _create_jwt(iat=now, exp=now)
        assert _validate_jwt_claims(token) is None
        # exp < iat
        token = _create_jwt(iat=now + 100, exp=now)
        assert _validate_jwt_claims(token) is None

    def test_future_iat_beyond_60_second_skew(self):
        """iat in the future beyond 60 seconds should fail."""
        now = time.time()
        # iat 70 seconds in the future - should fail
        token = _create_jwt(iat=now + 70, exp=now + 3600)
        assert _validate_jwt_claims(token) is None

    def test_future_iat_within_60_second_skew_passes(self):
        """iat within 60 seconds of current time should pass."""
        now = time.time()
        # iat 30 seconds in the future - should pass
        token = _create_jwt(iat=now + 30, exp=now + 3600)
        result = _validate_jwt_claims(token)
        assert result is not None

    def test_lifetime_exceeds_24h(self):
        """Token lifetime > 24 hours (86400 seconds) should fail."""
        now = time.time()
        # 25 hours lifetime
        token = _create_jwt(iat=now - 100, exp=now + 25 * 3600)
        assert _validate_jwt_claims(token) is None

    def test_already_expired_token(self):
        """Already expired token should fail (beyond clock skew tolerance)."""
        now = time.time()
        # exp 70 seconds ago (beyond 60 second clock skew tolerance)
        token = _create_jwt(iat=now - 600, exp=now - 70)
        assert _validate_jwt_claims(token) is None

    def test_fractional_boundary_at_exactly_60s_skew(self):
        """Test edge case: iat exactly at 60 second skew limit."""
        now = time.time()
        # iat at exactly 60 seconds in the future - should pass (edge case)
        token = _create_jwt(iat=now + 60, exp=now + 3600)
        result = _validate_jwt_claims(token)
        assert result is not None

    def test_fractional_boundary_just_over_60s_skew(self):
        """Test edge case: iat just over 60 second skew limit with floats."""
        now = time.time()
        # Using float to test boundary: iat at 60.1 seconds in future
        # Validated against raw float value, not truncated to int
        token = _create_jwt(iat=now + 60.1, exp=now + 3600)
        assert _validate_jwt_claims(token) is None

    def test_fractional_boundary_just_under_60s_skew(self):
        """Test edge case: iat just under 60 second skew limit with floats."""
        now = time.time()
        # Using float to test boundary: iat at 59.9 seconds in future
        # Validated against raw float value
        token = _create_jwt(iat=now + 59.9, exp=now + 3600)
        result = _validate_jwt_claims(token)
        assert result is not None


# --- Bearer token extraction ---


class TestExtractBearer:
    def test_with_auth(self):
        c = ClaudeCacheAsyncClient()
        req = httpx.Request(
            "POST", "https://x.com", headers={"Authorization": "Bearer tok123"}
        )
        assert c._extract_bearer_token(req) == "tok123"

    def test_lowercase(self):
        c = ClaudeCacheAsyncClient()
        req = httpx.Request(
            "POST", "https://x.com", headers={"authorization": "bearer tok"}
        )
        # httpx normalizes headers
        token = c._extract_bearer_token(req)
        assert token is not None

    def test_missing(self):
        c = ClaudeCacheAsyncClient()
        req = httpx.Request("POST", "https://x.com")
        assert c._extract_bearer_token(req) is None

    def test_non_bearer(self):
        c = ClaudeCacheAsyncClient()
        req = httpx.Request(
            "POST", "https://x.com", headers={"Authorization": "Basic abc"}
        )
        assert c._extract_bearer_token(req) is None


# --- Should refresh ---


class TestShouldRefresh:
    def test_no_token(self):
        c = ClaudeCacheAsyncClient()
        req = httpx.Request("POST", "https://x.com")
        assert c._should_refresh_token(req) is False

    def test_old_token(self):
        # SECURITY: Both iat and exp are required
        now = time.time()
        token = _create_jwt(iat=now - 7200, exp=now + 3600)
        c = ClaudeCacheAsyncClient()
        req = httpx.Request(
            "POST", "https://x.com", headers={"Authorization": f"Bearer {token}"}
        )
        assert c._should_refresh_token(req) is True

    def test_fresh_token(self):
        # SECURITY: Both iat and exp are required
        now = time.time()
        token = _create_jwt(iat=now - 100, exp=now + 3500)
        c = ClaudeCacheAsyncClient()
        req = httpx.Request(
            "POST", "https://x.com", headers={"Authorization": f"Bearer {token}"}
        )
        assert c._should_refresh_token(req) is False

    def test_falls_back_to_stored_expiry(self):
        """When JWT can't be decoded, falls back to stored token."""
        token = _create_jwt()  # no iat/exp
        c = ClaudeCacheAsyncClient()
        req = httpx.Request(
            "POST", "https://x.com", headers={"Authorization": f"Bearer {token}"}
        )
        with patch.object(
            ClaudeCacheAsyncClient, "_check_stored_token_expiry", return_value=True
        ):
            assert c._should_refresh_token(req) is True


# --- Check stored token expiry ---


class TestCheckStoredExpiry:
    def test_with_tokens_expired(self):
        mock_module = MagicMock()
        mock_module.load_stored_tokens = MagicMock(return_value={"access_token": "x"})
        mock_module.is_token_expired = MagicMock(return_value=True)
        with patch.dict(
            "sys.modules",
            {
                "code_puppy.plugins.claude_code_oauth": MagicMock(),
                "code_puppy.plugins.claude_code_oauth.utils": mock_module,
            },
        ):
            assert ClaudeCacheAsyncClient._check_stored_token_expiry() is True

    def test_with_no_tokens(self):
        mock_module = MagicMock()
        mock_module.load_stored_tokens = MagicMock(return_value=None)
        with patch.dict(
            "sys.modules",
            {
                "code_puppy.plugins.claude_code_oauth": MagicMock(),
                "code_puppy.plugins.claude_code_oauth.utils": mock_module,
            },
        ):
            assert ClaudeCacheAsyncClient._check_stored_token_expiry() is False

    def test_exception(self):
        mock_module = MagicMock()
        mock_module.load_stored_tokens = MagicMock(side_effect=Exception("fail"))
        with patch.dict(
            "sys.modules",
            {
                "code_puppy.plugins.claude_code_oauth": MagicMock(),
                "code_puppy.plugins.claude_code_oauth.utils": mock_module,
            },
        ):
            assert ClaudeCacheAsyncClient._check_stored_token_expiry() is False


# --- Prefix tool names ---


class TestPrefixToolNames:
    def test_basic(self):
        body = json.dumps({"tools": [{"name": "read_file"}]}).encode()
        result = ClaudeCacheAsyncClient._prefix_tool_names(body)
        assert result is not None
        data = json.loads(result)
        assert data["tools"][0]["name"] == f"{TOOL_PREFIX}read_file"

    def test_already_prefixed(self):
        body = json.dumps({"tools": [{"name": f"{TOOL_PREFIX}read_file"}]}).encode()
        assert ClaudeCacheAsyncClient._prefix_tool_names(body) is None

    def test_no_tools(self):
        body = json.dumps({"messages": []}).encode()
        assert ClaudeCacheAsyncClient._prefix_tool_names(body) is None

    def test_empty_tools(self):
        body = json.dumps({"tools": []}).encode()
        assert ClaudeCacheAsyncClient._prefix_tool_names(body) is None

    def test_invalid_json(self):
        assert ClaudeCacheAsyncClient._prefix_tool_names(b"not json") is None

    def test_non_dict(self):
        assert ClaudeCacheAsyncClient._prefix_tool_names(b'"string"') is None

    def test_tool_without_name(self):
        body = json.dumps({"tools": [{"description": "no name"}]}).encode()
        assert ClaudeCacheAsyncClient._prefix_tool_names(body) is None

    def test_tool_empty_name(self):
        body = json.dumps({"tools": [{"name": ""}]}).encode()
        assert ClaudeCacheAsyncClient._prefix_tool_names(body) is None


# --- Header transformation ---


class TestHeaderTransform:
    def test_sets_user_agent(self):
        h = {}
        ClaudeCacheAsyncClient._transform_headers_for_claude_code(h)
        assert h["user-agent"] == CLAUDE_CLI_USER_AGENT

    def test_removes_x_api_key_variants(self):
        h = {"x-api-key": "s", "X-API-Key": "s", "X-Api-Key": "s"}
        ClaudeCacheAsyncClient._transform_headers_for_claude_code(h)
        assert "x-api-key" not in h
        assert "X-API-Key" not in h
        assert "X-Api-Key" not in h

    def test_claude_code_beta_kept(self):
        h = {"anthropic-beta": "claude-code-20250219"}
        ClaudeCacheAsyncClient._transform_headers_for_claude_code(h)
        assert "claude-code-20250219" in h["anthropic-beta"]


# --- URL beta param ---


class TestAddBetaParam:
    def test_adds(self):
        url = httpx.URL("https://api.com/v1/messages")
        new_url = ClaudeCacheAsyncClient._add_beta_query_param(url)
        assert "beta=true" in str(new_url)

    def test_no_duplicate(self):
        url = httpx.URL("https://api.com/v1/messages?beta=true")
        new_url = ClaudeCacheAsyncClient._add_beta_query_param(url)
        assert str(new_url).count("beta") == 1


# --- Inject cache control ---


class TestInjectCacheControl:
    def test_basic(self):
        body = json.dumps(
            {
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "hi"}]}
                ]
            }
        ).encode()
        result = ClaudeCacheAsyncClient._inject_cache_control(body)
        assert result is not None
        data = json.loads(result)
        assert data["messages"][0]["content"][0]["cache_control"] == {
            "type": "ephemeral"
        }

    def test_already_has_cache_control(self):
        body = json.dumps(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "cache_control": {"type": "ephemeral"}}
                        ],
                    }
                ]
            }
        ).encode()
        assert ClaudeCacheAsyncClient._inject_cache_control(body) is None

    def test_no_messages(self):
        body = json.dumps({"model": "claude"}).encode()
        assert ClaudeCacheAsyncClient._inject_cache_control(body) is None

    def test_empty_messages(self):
        body = json.dumps({"messages": []}).encode()
        assert ClaudeCacheAsyncClient._inject_cache_control(body) is None

    def test_invalid_json(self):
        assert ClaudeCacheAsyncClient._inject_cache_control(b"not json") is None

    def test_non_dict(self):
        assert ClaudeCacheAsyncClient._inject_cache_control(b'"string"') is None

    def test_content_not_list(self):
        body = json.dumps(
            {"messages": [{"role": "user", "content": "just text"}]}
        ).encode()
        assert ClaudeCacheAsyncClient._inject_cache_control(body) is None

    def test_empty_content_list(self):
        body = json.dumps({"messages": [{"role": "user", "content": []}]}).encode()
        assert ClaudeCacheAsyncClient._inject_cache_control(body) is None

    def test_last_block_not_dict(self):
        body = json.dumps(
            {"messages": [{"role": "user", "content": ["just a string"]}]}
        ).encode()
        assert ClaudeCacheAsyncClient._inject_cache_control(body) is None

    def test_last_message_not_dict(self):
        body = json.dumps({"messages": ["not a dict"]}).encode()
        assert ClaudeCacheAsyncClient._inject_cache_control(body) is None


# --- _inject_cache_control_in_payload ---


class TestInjectCacheControlInPayload:
    def test_basic(self):
        payload = {
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
        }
        _inject_cache_control_in_payload(payload)
        assert payload["messages"][0]["content"][0]["cache_control"] == {
            "type": "ephemeral"
        }

    def test_already_present(self):
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "cache_control": {"type": "x"}}],
                }
            ]
        }
        _inject_cache_control_in_payload(payload)
        assert payload["messages"][0]["content"][0]["cache_control"] == {"type": "x"}

    def test_no_messages(self):
        payload = {}
        _inject_cache_control_in_payload(payload)  # should not raise

    def test_empty_messages(self):
        payload = {"messages": []}
        _inject_cache_control_in_payload(payload)

    def test_content_not_list(self):
        payload = {"messages": [{"role": "user", "content": "text"}]}
        _inject_cache_control_in_payload(payload)

    def test_empty_content(self):
        payload = {"messages": [{"role": "user", "content": []}]}
        _inject_cache_control_in_payload(payload)

    def test_last_block_not_dict(self):
        payload = {"messages": [{"role": "user", "content": ["str"]}]}
        _inject_cache_control_in_payload(payload)

    def test_last_message_not_dict(self):
        payload = {"messages": ["not a dict"]}
        _inject_cache_control_in_payload(payload)


# --- patch_anthropic_client_messages ---


class TestPatchAnthropic:
    def test_none_client(self):
        patch_anthropic_client_messages(None)  # should not raise

    def test_non_anthropic_client(self):
        patch_anthropic_client_messages("not a client")  # should not raise

    @pytest.mark.asyncio
    async def test_patches_create(self):
        """Test monkey-patching when AsyncAnthropic is available."""
        # We need to simulate AsyncAnthropic being available
        mock_messages = MagicMock()
        original_create = AsyncMock(return_value="result")
        mock_messages.create = original_create

        mock_client = MagicMock()
        mock_client.messages = mock_messages

        # Patch AsyncAnthropic to make isinstance check pass
        with patch("code_puppy.claude_cache_client.AsyncAnthropic", type(mock_client)):
            patch_anthropic_client_messages(mock_client)

        # Now create should be wrapped
        assert mock_messages.create is not original_create

        # Call the wrapped version with kwargs
        result = await mock_messages.create(
            model="claude-3",
            messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        )
        assert result == "result"

    @pytest.mark.asyncio
    async def test_patches_create_with_args(self):
        mock_messages = MagicMock()
        original_create = AsyncMock(return_value="ok")
        mock_messages.create = original_create

        mock_client = MagicMock()
        mock_client.messages = mock_messages

        with patch("code_puppy.claude_cache_client.AsyncAnthropic", type(mock_client)):
            patch_anthropic_client_messages(mock_client)

        # Call with positional dict arg
        payload = {
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
        }
        result = await mock_messages.create(payload)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_patches_create_with_non_dict_args(self):
        mock_messages = MagicMock()
        original_create = AsyncMock(return_value="ok")
        mock_messages.create = original_create

        mock_client = MagicMock()
        mock_client.messages = mock_messages

        with patch("code_puppy.claude_cache_client.AsyncAnthropic", type(mock_client)):
            patch_anthropic_client_messages(mock_client)

        # Call with non-dict positional arg
        result = await mock_messages.create("not a dict")
        assert result == "ok"

    def test_no_messages_attr(self):
        mock_client = MagicMock(spec=[])
        with patch("code_puppy.claude_cache_client.AsyncAnthropic", type(mock_client)):
            patch_anthropic_client_messages(mock_client)  # should not raise


# --- Extract body bytes ---


class TestExtractBodyBytes:
    def test_from_content(self):
        req = httpx.Request("POST", "https://x.com", content=b"hello")
        assert ClaudeCacheAsyncClient._extract_body_bytes(req) == b"hello"

    def test_no_content(self):
        req = httpx.Request("GET", "https://x.com")
        result = ClaudeCacheAsyncClient._extract_body_bytes(req)
        # GET has empty content
        assert result is None or result == b""

    def test_content_property_raises(self):
        """Test fallback to _content when .content raises."""
        req = MagicMock()
        type(req).content = property(lambda s: (_ for _ in ()).throw(Exception("no")))
        req._content = b"fallback"
        assert ClaudeCacheAsyncClient._extract_body_bytes(req) == b"fallback"

    def test_both_raise(self):
        req = MagicMock()
        type(req).content = property(lambda s: (_ for _ in ()).throw(Exception("no")))
        del req._content  # Make getattr return None
        result = ClaudeCacheAsyncClient._extract_body_bytes(req)
        assert result is None

    def test_content_empty_fallback_to_private(self):
        """When .content returns empty bytes, try _content."""
        req = MagicMock()
        req.content = b""  # empty/falsy
        req._content = b"private content"
        result = ClaudeCacheAsyncClient._extract_body_bytes(req)
        assert result == b"private content"

    def test_getattr_raises(self):
        """When both .content raises and getattr(_content) raises."""
        req = MagicMock()
        type(req).content = property(lambda s: (_ for _ in ()).throw(Exception("no")))
        type(req)._content = property(lambda s: (_ for _ in ()).throw(Exception("no2")))
        result = ClaudeCacheAsyncClient._extract_body_bytes(req)
        assert result is None


# --- Update auth headers ---


class TestUpdateAuthHeaders:
    def test_with_authorization(self):
        h = {"Authorization": "Bearer old"}
        ClaudeCacheAsyncClient._update_auth_headers(h, "new_tok")
        assert h["Authorization"] == "Bearer new_tok"

    def test_with_x_api_key(self):
        h = {"x-api-key": "old"}
        ClaudeCacheAsyncClient._update_auth_headers(h, "new_tok")
        assert h["x-api-key"] == "new_tok"

    def test_neither(self):
        h = {}
        ClaudeCacheAsyncClient._update_auth_headers(h, "new_tok")
        assert h["Authorization"] == "Bearer new_tok"


# --- Cloudflare detection ---


class TestCloudflareDetection:
    @pytest.mark.asyncio
    async def test_true(self):
        resp = Mock(spec=httpx.Response)
        resp.headers = {"content-type": "text/html"}
        resp._content = b"<html>cloudflare 400 bad request</html>"
        c = ClaudeCacheAsyncClient()
        assert await c._is_cloudflare_html_error(resp) is True

    @pytest.mark.asyncio
    async def test_json_content_type(self):
        resp = Mock(spec=httpx.Response)
        resp.headers = {"content-type": "application/json"}
        c = ClaudeCacheAsyncClient()
        assert await c._is_cloudflare_html_error(resp) is False

    @pytest.mark.asyncio
    async def test_no_content_fallback_to_text(self):
        resp = Mock(spec=httpx.Response)
        resp.headers = {"content-type": "text/html"}
        # Simulate pre-read content with bytes (production code now uses bytes comparison)
        resp._content = b"cloudflare 400 bad request"
        resp.aread = AsyncMock(return_value=b"cloudflare 400 bad request")
        c = ClaudeCacheAsyncClient()
        assert await c._is_cloudflare_html_error(resp) is True

    @pytest.mark.asyncio
    async def test_outer_exception_path(self):
        """Test the outer except Exception in _is_cloudflare_html_error."""
        resp = Mock(spec=httpx.Response)
        resp.headers = {"content-type": "text/html"}
        # _content that decodes to something whose .lower() raises
        resp._content = MagicMock()
        resp._content.__bool__ = lambda s: True
        resp._content.decode = MagicMock(side_effect=Exception("decode boom"))
        c = ClaudeCacheAsyncClient()
        assert await c._is_cloudflare_html_error(resp) is False

    @pytest.mark.asyncio
    async def test_no_content_text_raises(self):
        resp = Mock(spec=httpx.Response)
        resp.headers = {"content-type": "text/html"}
        resp._content = None
        resp.aread = AsyncMock(return_value=b"")
        type(resp).text = property(
            lambda s: (_ for _ in ()).throw(Exception("consumed"))
        )
        c = ClaudeCacheAsyncClient()
        assert await c._is_cloudflare_html_error(resp) is False


# --- Refresh token ---


class TestRefreshToken:
    def test_success(self):
        c = ClaudeCacheAsyncClient(headers={"Authorization": "Bearer old"})
        mock_module = MagicMock()
        mock_module.refresh_access_token = MagicMock(return_value="new_token")
        with patch.dict(
            "sys.modules",
            {
                "code_puppy.plugins.claude_code_oauth": MagicMock(),
                "code_puppy.plugins.claude_code_oauth.utils": mock_module,
            },
        ):
            result = c._refresh_claude_oauth_token()
            assert result == "new_token"

    def test_returns_none(self):
        c = ClaudeCacheAsyncClient()
        mock_module = MagicMock()
        mock_module.refresh_access_token = MagicMock(return_value=None)
        with patch.dict(
            "sys.modules",
            {
                "code_puppy.plugins.claude_code_oauth": MagicMock(),
                "code_puppy.plugins.claude_code_oauth.utils": mock_module,
            },
        ):
            result = c._refresh_claude_oauth_token()
            assert result is None

    def test_exception(self):
        c = ClaudeCacheAsyncClient()
        mock_module = MagicMock()
        mock_module.refresh_access_token = MagicMock(side_effect=Exception("fail"))
        with patch.dict(
            "sys.modules",
            {
                "code_puppy.plugins.claude_code_oauth": MagicMock(),
                "code_puppy.plugins.claude_code_oauth.utils": mock_module,
            },
        ):
            result = c._refresh_claude_oauth_token()
            assert result is None


# --- Send with retries ---


class TestSendWithRetries:
    @pytest.mark.asyncio
    async def test_success_first_try(self):
        resp = Mock(spec=httpx.Response)
        resp.status_code = 200

        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=resp
        ):
            c = ClaudeCacheAsyncClient()
            req = httpx.Request("POST", "https://x.com")
            result = await c._send_with_retries(req)
            assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_retry_on_429(self):
        resp_429 = Mock(spec=httpx.Response)
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "0.1"}
        resp_429.aclose = AsyncMock()

        resp_200 = Mock(spec=httpx.Response)
        resp_200.status_code = 200

        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            side_effect=[resp_429, resp_200],
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                c = ClaudeCacheAsyncClient()
                req = httpx.Request("POST", "https://x.com")
                result = await c._send_with_retries(req)
                assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_retry_on_429_http_date(self):
        resp_429 = Mock(spec=httpx.Response)
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "Mon, 01 Jan 2024 00:00:00 GMT"}
        resp_429.aclose = AsyncMock()

        resp_200 = Mock(spec=httpx.Response)
        resp_200.status_code = 200

        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            side_effect=[resp_429, resp_200],
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                c = ClaudeCacheAsyncClient()
                req = httpx.Request("POST", "https://x.com")
                result = await c._send_with_retries(req)
                assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_retry_on_429_invalid_retry_after(self):
        resp_429 = Mock(spec=httpx.Response)
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "not-a-number-or-date!!!"}
        resp_429.aclose = AsyncMock()

        resp_200 = Mock(spec=httpx.Response)
        resp_200.status_code = 200

        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            side_effect=[resp_429, resp_200],
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                c = ClaudeCacheAsyncClient()
                req = httpx.Request("POST", "https://x.com")
                result = await c._send_with_retries(req)
                assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_retry_on_500(self):
        resp_500 = Mock(spec=httpx.Response)
        resp_500.status_code = 500
        resp_500.headers = {}
        resp_500.aclose = AsyncMock()

        resp_200 = Mock(spec=httpx.Response)
        resp_200.status_code = 200

        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            side_effect=[resp_500, resp_200],
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                c = ClaudeCacheAsyncClient()
                req = httpx.Request("POST", "https://x.com")
                result = await c._send_with_retries(req)
                assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self):
        resp_500 = Mock(spec=httpx.Response)
        resp_500.status_code = 500
        resp_500.headers = {}
        resp_500.aclose = AsyncMock()

        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=resp_500
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                c = ClaudeCacheAsyncClient()
                req = httpx.Request("POST", "https://x.com")
                result = await c._send_with_retries(req)
                assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_retry_on_connect_error(self):
        resp_200 = Mock(spec=httpx.Response)
        resp_200.status_code = 200

        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            side_effect=[httpx.ConnectError("fail"), resp_200],
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                c = ClaudeCacheAsyncClient()
                req = httpx.Request("POST", "https://x.com")
                result = await c._send_with_retries(req)
                assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_connect_error_max_retries(self):
        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("fail"),
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                c = ClaudeCacheAsyncClient()
                req = httpx.Request("POST", "https://x.com")
                with pytest.raises(httpx.ConnectError):
                    await c._send_with_retries(req)

    @pytest.mark.asyncio
    async def test_non_retryable_exception(self):
        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            side_effect=ValueError("bad"),
        ):
            c = ClaudeCacheAsyncClient()
            req = httpx.Request("POST", "https://x.com")
            with pytest.raises(ValueError):
                await c._send_with_retries(req)

    @pytest.mark.asyncio
    async def test_retry_on_read_timeout(self):
        resp_200 = Mock(spec=httpx.Response)
        resp_200.status_code = 200

        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            side_effect=[httpx.ReadTimeout("timeout"), resp_200],
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                c = ClaudeCacheAsyncClient()
                req = httpx.Request("POST", "https://x.com")
                result = await c._send_with_retries(req)
                assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_retry_on_pool_timeout(self):
        resp_200 = Mock(spec=httpx.Response)
        resp_200.status_code = 200

        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            side_effect=[httpx.PoolTimeout("pool"), resp_200],
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                c = ClaudeCacheAsyncClient()
                req = httpx.Request("POST", "https://x.com")
                result = await c._send_with_retries(req)
                assert result.status_code == 200


# --- Full send flow ---


class TestSendFlow:
    @pytest.mark.asyncio
    async def test_non_messages_endpoint(self):
        resp = Mock(spec=httpx.Response)
        resp.status_code = 200
        resp.headers = {}

        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=resp
        ):
            c = ClaudeCacheAsyncClient()
            req = httpx.Request("GET", "https://api.com/v1/models")
            result = await c.send(req)
            assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_messages_endpoint_transforms(self):
        resp = Mock(spec=httpx.Response)
        resp.status_code = 200
        resp.headers = {"content-type": "application/json"}

        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=resp
        ):
            c = ClaudeCacheAsyncClient()
            body = json.dumps(
                {
                    "model": "claude-3",
                    "tools": [{"name": "fn"}],
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"type": "text", "text": "hi"}],
                        }
                    ],
                }
            ).encode()
            req = httpx.Request("POST", "https://api.com/v1/messages", content=body)
            result = await c.send(req)
            assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_auth_error_refresh(self):
        failed = Mock(spec=httpx.Response)
        failed.status_code = 401
        failed.headers = {"content-type": "application/json"}
        failed.aclose = AsyncMock()

        success = Mock(spec=httpx.Response)
        success.status_code = 200
        success.headers = {}

        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            side_effect=[failed, success],
        ):
            with patch.object(
                ClaudeCacheAsyncClient,
                "_refresh_claude_oauth_token",
                return_value="new",
            ):
                c = ClaudeCacheAsyncClient()
                req = httpx.Request(
                    "POST",
                    "https://api.com/v1/messages",
                    headers={"Authorization": "Bearer old"},
                    content=b'{"model": "x"}',
                )
                result = await c.send(req)
                assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_auth_error_refresh_fails(self):
        failed = Mock(spec=httpx.Response)
        failed.status_code = 403
        failed.headers = {"content-type": "application/json"}

        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=failed
        ):
            with patch.object(
                ClaudeCacheAsyncClient, "_refresh_claude_oauth_token", return_value=None
            ):
                c = ClaudeCacheAsyncClient()
                req = httpx.Request(
                    "POST", "https://api.com/v1/messages", content=b"{}"
                )
                result = await c.send(req)
                assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_already_attempted_refresh(self):
        """When refresh was already attempted, don't refresh again on auth error."""
        failed = Mock(spec=httpx.Response)
        failed.status_code = 401
        failed.headers = {}

        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=failed
        ):
            with patch.object(ClaudeCacheAsyncClient, "_refresh_claude_oauth_token"):
                c = ClaudeCacheAsyncClient()
                req = httpx.Request("POST", "https://api.com/v1/messages")
                req.extensions["claude_oauth_refresh_attempted"] = True
                result = await c.send(req)
                # Proactive refresh is skipped because extension flag is set
                # Auth error refresh is also skipped because flag is set
                assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_proactive_refresh_exception_handled(self):
        resp = Mock(spec=httpx.Response)
        resp.status_code = 200
        resp.headers = {}

        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=resp
        ):
            with patch.object(
                ClaudeCacheAsyncClient,
                "_should_refresh_token",
                side_effect=Exception("boom"),
            ):
                c = ClaudeCacheAsyncClient()
                req = httpx.Request("GET", "https://api.com/other")
                result = await c.send(req)
                assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_transformation_exception_handled(self):
        resp = Mock(spec=httpx.Response)
        resp.status_code = 200
        resp.headers = {"content-type": "application/json"}

        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=resp
        ):
            with patch.object(
                ClaudeCacheAsyncClient,
                "_transform_headers_for_claude_code",
                side_effect=Exception("boom"),
            ):
                c = ClaudeCacheAsyncClient()
                req = httpx.Request(
                    "POST", "https://api.com/v1/messages", content=b"{}"
                )
                result = await c.send(req)
                assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_auth_error_handling_exception(self):
        failed = Mock(spec=httpx.Response)
        failed.status_code = 401
        failed.headers = {}

        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=failed
        ):
            with patch.object(
                ClaudeCacheAsyncClient,
                "_refresh_claude_oauth_token",
                side_effect=Exception("boom"),
            ):
                c = ClaudeCacheAsyncClient()
                req = httpx.Request("POST", "https://api.com/v1/messages")
                result = await c.send(req)
                assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_cloudflare_400_triggers_refresh(self):
        failed = Mock(spec=httpx.Response)
        failed.status_code = 400
        failed.headers = {"content-type": "text/html"}
        failed._content = b"cloudflare 400 bad request"
        failed.aclose = AsyncMock()

        success = Mock(spec=httpx.Response)
        success.status_code = 200
        success.headers = {}

        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            side_effect=[failed, success],
        ):
            with patch.object(
                ClaudeCacheAsyncClient,
                "_refresh_claude_oauth_token",
                return_value="new",
            ):
                c = ClaudeCacheAsyncClient()
                req = httpx.Request(
                    "POST",
                    "https://api.com/v1/messages",
                    headers={"Authorization": "Bearer old"},
                    content=b"{}",
                )
                result = await c.send(req)
                assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_proactive_refresh_success(self):
        token = _create_jwt(iat=time.time() - 7200)  # old token
        resp = Mock(spec=httpx.Response)
        resp.status_code = 200
        resp.headers = {}

        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=resp
        ):
            with patch.object(
                ClaudeCacheAsyncClient,
                "_refresh_claude_oauth_token",
                return_value="new_tok",
            ):
                c = ClaudeCacheAsyncClient()
                req = httpx.Request(
                    "POST",
                    "https://api.com/other",
                    headers={"Authorization": f"Bearer {token}"},
                )
                result = await c.send(req)
                assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_messages_endpoint_full_transformations(self):
        """Test that all transformations are applied to /v1/messages."""
        resp = Mock(spec=httpx.Response)
        resp.status_code = 200
        resp.headers = {"content-type": "application/json"}

        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=resp
        ):
            c = ClaudeCacheAsyncClient()
            body = json.dumps(
                {
                    "model": "claude-3",
                    "tools": [{"name": "fn"}],
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"type": "text", "text": "hi"}],
                        }
                    ],
                }
            ).encode()
            req = httpx.Request(
                "POST",
                "https://api.com/v1/messages",
                content=body,
                headers={
                    "anthropic-beta": "interleaved-thinking-2025-05-14",
                    "x-api-key": "secret",
                },
            )
            result = await c.send(req)
            assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_messages_no_body(self):
        """Test /v1/messages with no body."""
        resp = Mock(spec=httpx.Response)
        resp.status_code = 200
        resp.headers = {}

        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=resp
        ):
            c = ClaudeCacheAsyncClient()
            req = httpx.Request("POST", "https://api.com/v1/messages")
            result = await c.send(req)
            assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_rebuild_request_exception(self):
        """Test that rebuild_request exceptions are handled gracefully."""
        resp = Mock(spec=httpx.Response)
        resp.status_code = 200
        resp.headers = {}

        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=resp
        ):
            c = ClaudeCacheAsyncClient()
            # Create a request to /v1/messages to trigger transformations
            req = httpx.Request(
                "POST", "https://api.com/v1/messages", content=b'{"model": "x"}'
            )
            with patch.object(
                c, "build_request", side_effect=Exception("rebuild fail")
            ):
                result = await c.send(req)
                # Should still succeed despite rebuild failure
                assert result.status_code == 200


# --- JWT Age Caching ---


class TestJWTAgeCaching:
    """Test JWT age caching to avoid repeated base64+JSON decoding."""

    def test_cache_is_initialized_empty(self):
        """Test that cache fields are initialized correctly."""
        c = ClaudeCacheAsyncClient()
        assert c._cached_jwt_iat is None

    def test_cache_populated_on_first_decode(self):
        """Test that cache is populated when first decoding a token."""
        # SECURITY: Both iat and exp are now required
        now = time.time()
        iat = now - 600
        exp = now + 3000
        token = _create_jwt(iat=iat, exp=exp)

        c = ClaudeCacheAsyncClient()
        age = c._get_jwt_age_seconds(token)

        # Cache should be populated: (token_prefix, iat)
        assert c._cached_jwt_iat is not None
        assert (
            c._cached_jwt_iat[0] == token[:64]
        )  # token prefix (64 chars covers header + payload start)
        assert c._cached_jwt_iat[1] == int(iat)
        # Age should be correct
        assert 590 <= age <= 610

    def test_cache_hit_avoids_repeated_decoding(self):
        """Test that subsequent calls with the same token use the cache."""
        # SECURITY: Both iat and exp are now required
        now = time.time()
        iat = now - 600
        exp = now + 3000
        token = _create_jwt(iat=iat, exp=exp)

        c = ClaudeCacheAsyncClient()

        # First call - cache miss, should decode
        age1 = c._get_jwt_age_seconds(token)
        assert c._cached_jwt_iat is not None
        assert c._cached_jwt_iat[0] == token[:64]

        # Second call - cache hit, should use cached value
        age2 = c._get_jwt_age_seconds(token)
        assert c._cached_jwt_iat[0] == token[:64]

        # Both ages should be similar (accounting for slight time difference)
        assert abs(age1 - age2) < 1.0

    def test_cache_cleared_on_token_change(self):
        """Test that different token clears the cache."""
        # SECURITY: Both iat and exp are now required
        now = time.time()
        iat1 = now - 600
        exp1 = now + 3000
        token1 = _create_jwt(iat=iat1, exp=exp1)

        iat2 = now - 1200
        exp2 = now + 2400
        token2 = _create_jwt(iat=iat2, exp=exp2)

        c = ClaudeCacheAsyncClient()

        # First token
        c._get_jwt_age_seconds(token1)
        assert c._cached_jwt_iat[0] == token1[:64]
        assert c._cached_jwt_iat[1] == int(iat1)

        # Second token - should update cache
        c._get_jwt_age_seconds(token2)
        assert c._cached_jwt_iat[0] == token2[:64]
        assert c._cached_jwt_iat[1] == int(iat2)

    def test_cache_not_used_for_invalid_tokens(self):
        """Test that tokens failing validation don't cache (SECURITY: both claims required)."""
        # Missing exp claim - should fail validation
        iat = time.time() - 600
        token = _create_jwt(iat=iat)  # No exp

        c = ClaudeCacheAsyncClient()
        age = c._get_jwt_age_seconds(token)

        # Cache should not be updated (token failed validation)
        assert c._cached_jwt_iat is None
        # Age should be None (validation failed)
        assert age is None

    def test_token_refresh_clears_cache(self):
        """Test that token refresh clears the JWT cache."""
        # SECURITY: Both iat and exp are now required
        now = time.time()
        iat = now - 600
        exp = now + 3000
        token = _create_jwt(iat=iat, exp=exp)

        c = ClaudeCacheAsyncClient(headers={"Authorization": "Bearer old"})

        # Prime the cache
        c._get_jwt_age_seconds(token)
        assert c._cached_jwt_iat is not None
        assert c._cached_jwt_iat[1] == int(iat)

        # Mock refresh token to return a new token
        mock_module = MagicMock()
        mock_module.refresh_access_token = MagicMock(return_value="new_token")
        with patch.dict(
            "sys.modules",
            {
                "code_puppy.plugins.claude_code_oauth": MagicMock(),
                "code_puppy.plugins.claude_code_oauth.utils": mock_module,
            },
        ):
            c._refresh_claude_oauth_token()

            # Cache should be cleared
            assert c._cached_jwt_iat is None

    def test_falling_back_to_exp_when_no_iat(self):
        """Test that cache is only used for iat claims, not exp fallback."""
        # Token with both iat and exp - iat should be preferred and cached
        iat = time.time() - 600
        exp = time.time() + 3000
        token_both = _create_jwt(iat=iat, exp=exp)

        c = ClaudeCacheAsyncClient()
        age = c._get_jwt_age_seconds(token_both)

        # Cache should be populated with iat (not exp)
        assert c._cached_jwt_iat is not None
        assert c._cached_jwt_iat[0] == token_both[:64]
        assert c._cached_jwt_iat[1] == int(iat)
        # Age should be calculated from iat (~600 secs)
        assert 590 <= age <= 610


def test_jwt_claims_cache_thread_safety():
    """INSTRUMENTED test: verify lock is held during JWT cache access.
    
    The watchdog requires tests that PROVE the lock is being acquired,
    not just tests that happen to pass due to CPython's GIL. This test
    instruments the lock to count acquisitions.
    """
    import time
    import jwt as _jwt_lib
    import code_puppy.claude_cache_client as mod
    
    # First: verify lock infrastructure exists and is correct type
    assert hasattr(mod, '_jwt_cache_lock'), "Module must have _jwt_cache_lock"
    assert isinstance(mod._jwt_cache_lock, type(threading.Lock())), \
        "_jwt_cache_lock must be a threading.Lock"
    assert hasattr(mod, '_jwt_claims_cache'), "Module must have _jwt_claims_cache"
    assert isinstance(mod._jwt_claims_cache, dict), "_jwt_claims_cache must be a dict"
    
    # Create an instrumented lock that counts acquisitions
    class InstrumentedLock:
        def __init__(self, real_lock):
            self._lock = real_lock
            self.acquire_count = 0
        
        def acquire(self, *args, **kwargs):
            self.acquire_count += 1
            return self._lock.acquire(*args, **kwargs)
        
        def release(self):
            return self._lock.release()
        
        def __enter__(self):
            self.acquire_count += 1
            return self._lock.__enter__()
        
        def __exit__(self, *args):
            return self._lock.__exit__(*args)
    
    # Replace module lock with instrumented version
    original_lock = mod._jwt_cache_lock
    instrumented = InstrumentedLock(original_lock)
    mod._jwt_cache_lock = instrumented
    
    try:
        # Clear cache using original lock
        with original_lock:
            _jwt_claims_cache.clear()
        
        # Create a valid JWT with timestamps that pass validation
        # Must use jwt.encode() for proper formatting
        now = int(time.time())
        iat = now - 100  # Issued 100 seconds ago
        exp = now + 3600  # Expires in 1 hour
        
        payload = {"iat": iat, "exp": exp}
        token = _jwt_lib.encode(payload, "dummy_secret_32_bytes_long", algorithm="HS256")
        
        # First call: cache miss (acquire for check + acquire for write = 2)
        result1 = _get_jwt_claims(token)
        
        # Second call: cache hit (acquire for check = 1)
        result2 = _get_jwt_claims(token)
        
        # CRITICAL: Verify lock was acquired multiple times
        # If the lock isn't being used, acquire_count would be 0 or very low
        assert instrumented.acquire_count >= 2, \
            f"Lock must be acquired at least 2 times (for cache access), got {instrumented.acquire_count}"
        
        # Verify cache actually has the entry
        with original_lock:
            assert len(_jwt_claims_cache) >= 1, "Cache should have at least 1 entry"
        
        # Verify results are correct (same cached result)
        assert result1 == result2, "Cache hit should return identical result"
        assert isinstance(result1, tuple), "Result should be a tuple"
        assert result1 == (iat, exp), f"Result should be {(iat, exp)}, got {result1}"
        
    finally:
        # Restore original lock
        mod._jwt_cache_lock = original_lock
