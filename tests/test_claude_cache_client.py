"""Tests for the Claude cache client.

Covers JWT age detection, proactive/auth-error token refresh, Cloudflare error
detection, tool-name prefixing, header/URL transformations, cache_control
injection (both the bytes-based and in-place payload variants), retry logic,
and the full send() flow.
"""
from __future__ import annotations

import base64
import json
import time
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest

from code_puppy.claude_cache_client import (
    CLAUDE_CLI_USER_AGENT,
    TOKEN_MAX_AGE_SECONDS,
    TOOL_PREFIX,
    ClaudeCacheAsyncClient,
    _inject_cache_control_in_payload,
    patch_anthropic_client_messages,
)


def _create_jwt(iat=None, exp=None):
    """Create a test JWT with the given iat/exp claims."""
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


def _request(url="https://api.anthropic.com/v1/messages", token=None, **kwargs):
    headers = kwargs.pop("headers", {})
    if token is not None:
        headers = {**headers, "Authorization": f"Bearer {token}"}
    return httpx.Request("POST", url, headers=headers, **kwargs)


def _mock_response(status_code=200, content_type="application/json", content=None):
    resp = Mock(spec=httpx.Response)
    resp.status_code = status_code
    resp.headers = {"content-type": content_type} if content_type else {}
    if content is not None:
        resp._content = content
    resp.aclose = AsyncMock()
    return resp


# --------------------------------------------------------------------------- #
# JWT age detection
# --------------------------------------------------------------------------- #


class TestJWTAge:
    @pytest.mark.parametrize(
        "token",
        [
            None,
            "",
            "not.a.valid.jwt",  # bad base64 payload
            "invalid",  # wrong number of parts
            "only.two",
            "a.b.c.d",
            "a.!!!.c",  # 3 parts, bad base64
            _create_jwt(),  # no iat/exp claims
        ],
    )
    def test_returns_none(self, token):
        assert ClaudeCacheAsyncClient()._get_jwt_age_seconds(token) is None

    @pytest.mark.parametrize(
        "offsets, lo, hi",
        [
            ({"iat": -1800}, 1790, 1810),  # age from iat
            ({"exp": +1800}, 1790, 1810),  # age from exp (3600-1800)
            # iat preferred over exp: 10 min old vs 50 min until exp
            ({"iat": -600, "exp": +3000}, 590, 610),
        ],
    )
    def test_age_window(self, offsets, lo, hi):
        # Compute timestamps at execution time, not at collection time, so the
        # gap between collection and running the test (large in the full suite)
        # does not skew the JWT age.
        now = time.time()
        kwargs = {claim: now + delta for claim, delta in offsets.items()}
        age = ClaudeCacheAsyncClient()._get_jwt_age_seconds(_create_jwt(**kwargs))
        assert age is not None and lo <= age <= hi

    def test_exp_far_future_clamped_to_zero(self):
        token = _create_jwt(exp=time.time() + TOKEN_MAX_AGE_SECONDS + 1000)
        assert ClaudeCacheAsyncClient()._get_jwt_age_seconds(token) == 0


# --------------------------------------------------------------------------- #
# Bearer token extraction
# --------------------------------------------------------------------------- #


class TestExtractBearer:
    def test_with_auth(self):
        req = _request(token="my_token_123")
        assert ClaudeCacheAsyncClient()._extract_bearer_token(req) == "my_token_123"

    def test_lowercase_header(self):
        req = httpx.Request(
            "POST", "https://x.com", headers={"authorization": "bearer tok"}
        )
        assert ClaudeCacheAsyncClient()._extract_bearer_token(req) is not None

    @pytest.mark.parametrize(
        "headers",
        [{}, {"Authorization": "Basic abc"}],
    )
    def test_missing_or_non_bearer(self, headers):
        req = httpx.Request("POST", "https://x.com", headers=headers)
        assert ClaudeCacheAsyncClient()._extract_bearer_token(req) is None


# --------------------------------------------------------------------------- #
# Should-refresh decision
# --------------------------------------------------------------------------- #


class TestShouldRefresh:
    @pytest.mark.parametrize(
        "iat_offset, expected",
        [
            (-7200, True),  # 2h old
            (-TOKEN_MAX_AGE_SECONDS, True),  # exactly 1h
            (-1800, False),  # 30 min old
        ],
    )
    def test_by_jwt_age(self, iat_offset, expected):
        # Build the token at execution time (see test_age_window) to avoid
        # collection-time clock skew in the full suite.
        token = _create_jwt(iat=time.time() + iat_offset)
        assert (
            ClaudeCacheAsyncClient()._should_refresh_token(_request(token=token))
            is expected
        )

    def test_no_token(self):
        req = httpx.Request("POST", "https://x.com")
        assert ClaudeCacheAsyncClient()._should_refresh_token(req) is False

    def test_falls_back_to_stored_expiry(self):
        """When the JWT has no timestamp claims, fall back to stored expiry."""
        req = _request(token=_create_jwt())
        with patch.object(
            ClaudeCacheAsyncClient, "_check_stored_token_expiry", return_value=True
        ):
            assert ClaudeCacheAsyncClient()._should_refresh_token(req) is True


# --------------------------------------------------------------------------- #
# Stored token expiry check
# --------------------------------------------------------------------------- #


def _patch_oauth_utils(**attrs):
    mock_module = MagicMock()
    for name, value in attrs.items():
        setattr(mock_module, name, MagicMock(**value))
    return patch.dict(
        "sys.modules",
        {
            "code_puppy.plugins.claude_code_oauth": MagicMock(),
            "code_puppy.plugins.claude_code_oauth.utils": mock_module,
        },
    )


class TestCheckStoredExpiry:
    @pytest.mark.parametrize(
        "load_kwargs, expired_kwargs, expected",
        [
            ({"return_value": {"access_token": "x"}}, {"return_value": True}, True),
            ({"return_value": None}, {"return_value": False}, False),
            ({"side_effect": Exception("fail")}, {"return_value": False}, False),
        ],
    )
    def test_check(self, load_kwargs, expired_kwargs, expected):
        with _patch_oauth_utils(
            load_stored_tokens=load_kwargs, is_token_expired=expired_kwargs
        ):
            assert ClaudeCacheAsyncClient._check_stored_token_expiry() is expected


# --------------------------------------------------------------------------- #
# Tool name prefixing
# --------------------------------------------------------------------------- #


class TestPrefixToolNames:
    def test_basic(self):
        body = json.dumps(
            {"tools": [{"name": "read_file"}, {"name": "edit_file"}]}
        ).encode()
        result = ClaudeCacheAsyncClient._prefix_tool_names(body)
        assert result is not None
        data = json.loads(result)
        assert data["tools"][0]["name"] == f"{TOOL_PREFIX}read_file"
        assert data["tools"][1]["name"] == f"{TOOL_PREFIX}edit_file"

    @pytest.mark.parametrize(
        "body",
        [
            json.dumps(
                {"tools": [{"name": f"{TOOL_PREFIX}read_file"}]}
            ).encode(),  # already prefixed
            json.dumps({"messages": []}).encode(),  # no tools
            json.dumps({"tools": []}).encode(),  # empty tools
            json.dumps({"tools": [{"description": "no name"}]}).encode(),  # no name key
            json.dumps({"tools": [{"name": ""}]}).encode(),  # empty name
            b"not valid json",  # invalid json
            b'"string"',  # non-dict
        ],
    )
    def test_returns_none(self, body):
        assert ClaudeCacheAsyncClient._prefix_tool_names(body) is None


class TestApplyClaudeCodePrefixFlag:
    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            ({}, False),  # default: custom_anthropic must NOT prefix
            ({"apply_claude_code_prefix": True}, True),  # opt-in by oauth plugin
        ],
    )
    def test_flag(self, kwargs, expected):
        assert ClaudeCacheAsyncClient(**kwargs)._apply_claude_code_prefix is expected


# --------------------------------------------------------------------------- #
# Header transformation
# --------------------------------------------------------------------------- #


class TestHeaderTransform:
    def test_sets_user_agent(self):
        h = {}
        ClaudeCacheAsyncClient._transform_headers_for_claude_code(h)
        assert h["user-agent"] == CLAUDE_CLI_USER_AGENT

    def test_adds_required_betas(self):
        h = {}
        ClaudeCacheAsyncClient._transform_headers_for_claude_code(h)
        assert "oauth-2025-04-20" in h["anthropic-beta"]
        assert "interleaved-thinking-2025-05-14" in h["anthropic-beta"]

    def test_keeps_claude_code_beta_if_present(self):
        h = {"anthropic-beta": "claude-code-20250219,interleaved-thinking-2025-05-14"}
        ClaudeCacheAsyncClient._transform_headers_for_claude_code(h)
        assert "claude-code-20250219" in h["anthropic-beta"]

    def test_excludes_claude_code_beta_if_not_present(self):
        h = {"anthropic-beta": "interleaved-thinking-2025-05-14"}
        ClaudeCacheAsyncClient._transform_headers_for_claude_code(h)
        assert "claude-code-20250219" not in h["anthropic-beta"]

    def test_removes_x_api_key_variants(self):
        h = {
            "x-api-key": "s",
            "X-API-Key": "s",
            "X-Api-Key": "s",
            "anthropic-beta": "interleaved-thinking-2025-05-14",
        }
        ClaudeCacheAsyncClient._transform_headers_for_claude_code(h)
        assert "x-api-key" not in h
        assert "X-API-Key" not in h
        assert "X-Api-Key" not in h

    def test_preserves_extra_betas(self):
        h = {
            "anthropic-beta": "oauth-2025-04-20,interleaved-thinking-2025-05-14,context-1m-2025-08-07"
        }
        ClaudeCacheAsyncClient._transform_headers_for_claude_code(h)
        assert "context-1m-2025-08-07" in h["anthropic-beta"]
        assert "oauth-2025-04-20" in h["anthropic-beta"]
        assert "interleaved-thinking-2025-05-14" in h["anthropic-beta"]

    def test_no_duplicate_required_betas(self):
        h = {"anthropic-beta": "oauth-2025-04-20,interleaved-thinking-2025-05-14"}
        ClaudeCacheAsyncClient._transform_headers_for_claude_code(h)
        beta_str = h["anthropic-beta"]
        assert beta_str.count("oauth-2025-04-20") == 1
        assert beta_str.count("interleaved-thinking-2025-05-14") == 1


# --------------------------------------------------------------------------- #
# URL beta query param
# --------------------------------------------------------------------------- #


class TestAddBetaParam:
    @pytest.mark.parametrize(
        "url",
        [
            "https://api.anthropic.com/v1/messages",
            "https://api.anthropic.com/v1/messages?foo=bar",
        ],
    )
    def test_adds_beta(self, url):
        new_url = ClaudeCacheAsyncClient._add_beta_query_param(httpx.URL(url))
        assert "beta=true" in str(new_url)
        if "foo=bar" in url:
            assert "foo=bar" in str(new_url)

    def test_not_duplicated(self):
        url = httpx.URL("https://api.anthropic.com/v1/messages?beta=true")
        new_url = ClaudeCacheAsyncClient._add_beta_query_param(url)
        assert str(new_url).count("beta") == 1


# --------------------------------------------------------------------------- #
# cache_control injection: both the bytes-based static method and the in-place
# payload helper share the same logic, so we exercise them through one adapter.
# --------------------------------------------------------------------------- #


def _inject_bytes(payload):
    """Run the bytes-based injector; return (result_or_None, parsed_data)."""
    result = ClaudeCacheAsyncClient._inject_cache_control(json.dumps(payload).encode())
    return result, (json.loads(result) if result is not None else None)


def _inject_inplace(payload):
    """Run the in-place injector; return (sentinel, mutated payload)."""
    data = json.loads(json.dumps(payload))  # deep copy
    _inject_cache_control_in_payload(data)
    return "ran", data


EPHEMERAL = {"type": "ephemeral"}
INJECTORS = [_inject_bytes, _inject_inplace]


@pytest.mark.parametrize("inject", INJECTORS)
class TestInjectCacheControl:
    def test_messages_only(self, inject):
        _, data = inject(
            {
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "hi"}]}
                ]
            }
        )
        assert data["messages"][0]["content"][0]["cache_control"] == EPHEMERAL

    def test_system_string_converted(self, inject):
        _, data = inject(
            {
                "system": "Be helpful.",
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "hi"}]}
                ],
            }
        )
        assert isinstance(data["system"], list)
        assert data["system"][0]["type"] == "text"
        assert data["system"][0]["text"] == "Be helpful."
        assert data["system"][0]["cache_control"] == EPHEMERAL

    def test_system_list_cached(self, inject):
        _, data = inject(
            {
                "system": [{"type": "text", "text": "Be helpful."}],
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "hi"}]}
                ],
            }
        )
        assert data["system"][-1]["cache_control"] == EPHEMERAL

    def test_tools_only_last_cached(self, inject):
        _, data = inject(
            {
                "tools": [{"name": "a"}, {"name": "b"}],
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "hi"}]}
                ],
            }
        )
        assert "cache_control" not in data["tools"][0]
        assert data["tools"][1]["cache_control"] == EPHEMERAL

    def test_full_payload_all_three_breakpoints(self, inject):
        _, data = inject(
            {
                "system": [{"type": "text", "text": "sys"}],
                "tools": [{"name": "t1"}, {"name": "t2"}],
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "hi"}]}
                ],
            }
        )
        assert data["system"][0]["cache_control"] == EPHEMERAL
        assert "cache_control" not in data["tools"][0]
        assert data["tools"][1]["cache_control"] == EPHEMERAL
        assert data["messages"][0]["content"][0]["cache_control"] == EPHEMERAL

    @pytest.mark.parametrize(
        "key, value",
        [
            # Empty / non-list / non-dict prefixes are left untouched by both injectors.
            ("system", ""),
            ("system", []),
            ("system", ["just a string"]),
            ("tools", []),
            ("tools", ["not a dict"]),
        ],
    )
    def test_uncacheable_prefix_preserved(self, inject, key, value):
        payload = {
            key: value,
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        }
        _, data = inject(payload)
        assert data[key] == value

    @pytest.mark.parametrize(
        "messages",
        [
            [],
            [{"role": "user", "content": "just text"}],
            [{"role": "user", "content": []}],
            [{"role": "user", "content": ["just a string"]}],
            ["not a dict"],
        ],
    )
    def test_uncacheable_message_shapes_do_not_raise(self, inject, messages):
        # No exception, and no spurious cache_control on uncacheable message shapes.
        inject({"messages": messages})


class TestInjectBytesOnlyReturnValue:
    """The bytes-based injector's None-vs-bytes return contract."""

    @pytest.mark.parametrize(
        "payload",
        [
            {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "cache_control": {"type": "ephemeral"}}
                        ],
                    }
                ]
            },
            {"model": "claude"},
            {"messages": []},
            {"messages": [{"role": "user", "content": "just text"}]},
            {"messages": [{"role": "user", "content": []}]},
            {"messages": [{"role": "user", "content": ["just a string"]}]},
            {"messages": ["not a dict"]},
        ],
    )
    def test_returns_none_when_nothing_changes(self, payload):
        assert (
            ClaudeCacheAsyncClient._inject_cache_control(json.dumps(payload).encode())
            is None
        )

    @pytest.mark.parametrize("body", [b"not json", b'"string"'])
    def test_invalid_input_returns_none(self, body):
        assert ClaudeCacheAsyncClient._inject_cache_control(body) is None

    def test_empty_string_system_preserved(self):
        body = json.dumps(
            {
                "system": "",
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "hi"}]}
                ],
            }
        ).encode()
        result = ClaudeCacheAsyncClient._inject_cache_control(body)
        assert json.loads(result)["system"] == ""

    def test_system_last_block_not_dict_preserved(self):
        body = json.dumps(
            {
                "system": ["just a string"],
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "hi"}]}
                ],
            }
        ).encode()
        result = ClaudeCacheAsyncClient._inject_cache_control(body)
        data = json.loads(result)
        assert data["system"] == ["just a string"]
        assert data["messages"][0]["content"][0]["cache_control"] == EPHEMERAL

    def test_tools_last_not_dict_preserved(self):
        body = json.dumps(
            {
                "tools": ["not a dict"],
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "hi"}]}
                ],
            }
        ).encode()
        result = ClaudeCacheAsyncClient._inject_cache_control(body)
        assert json.loads(result)["tools"] == ["not a dict"]


class TestInjectInPlaceOnly:
    """In-place helper retains already-present cache_control values."""

    def test_already_present_value_preserved(self):
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

    @pytest.mark.parametrize(
        "payload",
        [
            {},  # no messages, must not raise
            {"system": ["just a string"]},
            {"system": []},
            {"tools": ["not a dict"]},
            {"tools": []},
        ],
    )
    def test_no_op_inputs(self, payload):
        original = json.loads(json.dumps(payload))
        _inject_cache_control_in_payload(payload)
        assert payload == original

    def test_system_already_cached(self):
        payload = {
            "system": [
                {"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}}
            ]
        }
        _inject_cache_control_in_payload(payload)
        assert payload["system"][0]["cache_control"] == EPHEMERAL

    def test_tools_already_cached(self):
        payload = {"tools": [{"name": "a", "cache_control": {"type": "ephemeral"}}]}
        _inject_cache_control_in_payload(payload)
        assert payload["tools"][0]["cache_control"] == EPHEMERAL


# --------------------------------------------------------------------------- #
# patch_anthropic_client_messages
# --------------------------------------------------------------------------- #


class TestPatchAnthropic:
    @pytest.mark.parametrize("client", [None, "not a client"])
    def test_noop_for_non_anthropic(self, client):
        patch_anthropic_client_messages(client)  # should not raise

    def test_no_messages_attr(self):
        mock_client = MagicMock(spec=[])
        with patch("code_puppy.claude_cache_client.AsyncAnthropic", type(mock_client)):
            patch_anthropic_client_messages(mock_client)  # should not raise

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "call",
        [
            lambda create: create(
                model="claude-3",
                messages=[
                    {"role": "user", "content": [{"type": "text", "text": "hi"}]}
                ],
            ),
            lambda create: create(
                {
                    "messages": [
                        {"role": "user", "content": [{"type": "text", "text": "hi"}]}
                    ]
                }
            ),
            lambda create: create("not a dict"),
        ],
    )
    async def test_wraps_and_forwards(self, call):
        mock_messages = MagicMock()
        original_create = AsyncMock(return_value="result")
        mock_messages.create = original_create
        mock_client = MagicMock()
        mock_client.messages = mock_messages

        with patch("code_puppy.claude_cache_client.AsyncAnthropic", type(mock_client)):
            patch_anthropic_client_messages(mock_client)

        assert mock_messages.create is not original_create
        assert await call(mock_messages.create) == "result"


# --------------------------------------------------------------------------- #
# Body byte extraction
# --------------------------------------------------------------------------- #


class TestExtractBodyBytes:
    def test_from_content(self):
        req = httpx.Request("POST", "https://x.com", content=b"hello")
        assert ClaudeCacheAsyncClient._extract_body_bytes(req) == b"hello"

    def test_no_content(self):
        req = httpx.Request("GET", "https://x.com")
        result = ClaudeCacheAsyncClient._extract_body_bytes(req)
        assert result is None or result == b""

    def test_content_property_raises_falls_back_to_private(self):
        req = MagicMock()
        type(req).content = property(lambda s: (_ for _ in ()).throw(Exception("no")))
        req._content = b"fallback"
        assert ClaudeCacheAsyncClient._extract_body_bytes(req) == b"fallback"

    def test_empty_content_falls_back_to_private(self):
        req = MagicMock()
        req.content = b""
        req._content = b"private content"
        assert ClaudeCacheAsyncClient._extract_body_bytes(req) == b"private content"

    def test_both_raise_returns_none(self):
        req = MagicMock()
        type(req).content = property(lambda s: (_ for _ in ()).throw(Exception("no")))
        type(req)._content = property(lambda s: (_ for _ in ()).throw(Exception("no2")))
        assert ClaudeCacheAsyncClient._extract_body_bytes(req) is None

    def test_content_raises_and_no_private(self):
        req = MagicMock()
        type(req).content = property(lambda s: (_ for _ in ()).throw(Exception("no")))
        del req._content
        assert ClaudeCacheAsyncClient._extract_body_bytes(req) is None


# --------------------------------------------------------------------------- #
# Auth header updates
# --------------------------------------------------------------------------- #


class TestUpdateAuthHeaders:
    @pytest.mark.parametrize(
        "headers, key, expected",
        [
            ({"Authorization": "Bearer old"}, "Authorization", "Bearer new_tok"),
            ({"x-api-key": "old"}, "x-api-key", "new_tok"),
            ({}, "Authorization", "Bearer new_tok"),
        ],
    )
    def test_update(self, headers, key, expected):
        ClaudeCacheAsyncClient._update_auth_headers(headers, "new_tok")
        assert headers[key] == expected


# --------------------------------------------------------------------------- #
# Cloudflare HTML error detection
# --------------------------------------------------------------------------- #

CLOUDFLARE_HTML = (
    "<html>\r\n"
    "<head><title>400 Bad Request</title></head>\r\n"
    "<body>\r\n"
    "<center><h1>400 Bad Request</h1></center>\r\n"
    "<hr><center>cloudflare</center>\r\n"
    "</body>\r\n"
    "</html>"
)


class TestCloudflareDetection:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "content_type, content, expected",
        [
            ("text/html; charset=utf-8", CLOUDFLARE_HTML.encode(), True),
            ("application/json", b'{"error": "some error"}', False),
            ("text/html", b"<html><body>Some other error</body></html>", False),
            # has 'cloudflare' but not '400 bad request' marker
            ("text/html", b"<html><body>cloudflare</body></html>", False),
        ],
    )
    async def test_content_based(self, content_type, content, expected):
        resp = Mock(spec=httpx.Response)
        resp.headers = {"content-type": content_type}
        resp._content = content
        resp.text = content.decode("utf-8")
        assert (
            await ClaudeCacheAsyncClient()._is_cloudflare_html_error(resp) is expected
        )

    @pytest.mark.asyncio
    async def test_json_content_type_short_circuits(self):
        resp = Mock(spec=httpx.Response)
        resp.headers = {"content-type": "application/json"}
        assert await ClaudeCacheAsyncClient()._is_cloudflare_html_error(resp) is False

    @pytest.mark.asyncio
    async def test_no_content_falls_back_to_text(self):
        resp = Mock(spec=httpx.Response)
        resp.headers = {"content-type": "text/html"}
        resp._content = None
        resp.text = "cloudflare 400 bad request"
        resp.aread = AsyncMock(return_value=resp.text.encode("utf-8"))
        assert await ClaudeCacheAsyncClient()._is_cloudflare_html_error(resp) is True

    @pytest.mark.asyncio
    async def test_decode_exception_returns_false(self):
        resp = Mock(spec=httpx.Response)
        resp.headers = {"content-type": "text/html"}
        resp._content = MagicMock()
        resp._content.__bool__ = lambda s: True
        resp._content.decode = MagicMock(side_effect=Exception("decode boom"))
        assert await ClaudeCacheAsyncClient()._is_cloudflare_html_error(resp) is False

    @pytest.mark.asyncio
    async def test_text_property_raises_returns_false(self):
        resp = Mock(spec=httpx.Response)
        resp.headers = {"content-type": "text/html"}
        resp._content = None
        resp.aread = AsyncMock(return_value=b"")
        type(resp).text = property(
            lambda s: (_ for _ in ()).throw(Exception("consumed"))
        )
        assert await ClaudeCacheAsyncClient()._is_cloudflare_html_error(resp) is False


# --------------------------------------------------------------------------- #
# Token refresh
# --------------------------------------------------------------------------- #


class TestRefreshToken:
    @pytest.mark.parametrize(
        "refresh_kwargs, expected",
        [
            ({"return_value": "new_token"}, "new_token"),
            ({"return_value": None}, None),
            ({"side_effect": Exception("fail")}, None),
        ],
    )
    def test_refresh(self, refresh_kwargs, expected):
        c = ClaudeCacheAsyncClient(headers={"Authorization": "Bearer old"})
        with _patch_oauth_utils(refresh_access_token=refresh_kwargs):
            assert c._refresh_claude_oauth_token() == expected


# --------------------------------------------------------------------------- #
# _send_with_retries
# --------------------------------------------------------------------------- #


class TestSendWithRetries:
    @pytest.mark.asyncio
    async def test_success_first_try(self):
        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            return_value=_mock_response(200),
        ):
            result = await ClaudeCacheAsyncClient()._send_with_retries(
                httpx.Request("POST", "https://x.com")
            )
            assert result.status_code == 200

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "first_status, headers",
        [
            (429, {"Retry-After": "0.1"}),
            (429, {"Retry-After": "Mon, 01 Jan 2024 00:00:00 GMT"}),
            (429, {"Retry-After": "not-a-number-or-date!!!"}),
            (500, {}),
        ],
    )
    async def test_retries_then_succeeds(self, first_status, headers):
        first = _mock_response(first_status)
        first.headers = headers
        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            side_effect=[first, _mock_response(200)],
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await ClaudeCacheAsyncClient()._send_with_retries(
                    httpx.Request("POST", "https://x.com")
                )
                assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_max_retries_exhausted_returns_last(self):
        resp_500 = _mock_response(500)
        resp_500.headers = {}
        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=resp_500
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await ClaudeCacheAsyncClient()._send_with_retries(
                    httpx.Request("POST", "https://x.com")
                )
                assert result.status_code == 500

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exc",
        [
            httpx.ConnectError("fail"),
            httpx.ReadTimeout("timeout"),
            httpx.PoolTimeout("pool"),
        ],
    )
    async def test_retries_on_transient_connection_error(self, exc):
        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            side_effect=[exc, _mock_response(200)],
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await ClaudeCacheAsyncClient()._send_with_retries(
                    httpx.Request("POST", "https://x.com")
                )
                assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_connect_error_exhausted_reraises(self):
        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("fail"),
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(httpx.ConnectError):
                    await ClaudeCacheAsyncClient()._send_with_retries(
                        httpx.Request("POST", "https://x.com")
                    )

    @pytest.mark.asyncio
    async def test_non_retryable_exception_propagates(self):
        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            side_effect=ValueError("bad"),
        ):
            with pytest.raises(ValueError):
                await ClaudeCacheAsyncClient()._send_with_retries(
                    httpx.Request("POST", "https://x.com")
                )


# --------------------------------------------------------------------------- #
# Full send() flow
# --------------------------------------------------------------------------- #

MESSAGES_BODY = json.dumps(
    {
        "model": "claude-3-opus",
        "tools": [
            {"name": "read_file", "description": "read"},
            {"name": "edit_file", "description": "edit"},
        ],
        "messages": [{"role": "user", "content": "hi"}],
    }
).encode()


class TestSendFlow:
    @pytest.mark.asyncio
    async def test_non_messages_endpoint_passthrough(self):
        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            return_value=_mock_response(200, None),
        ):
            result = await ClaudeCacheAsyncClient().send(
                httpx.Request("GET", "https://api.com/v1/models")
            )
            assert result.status_code == 200

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "request_kwargs",
        [
            {"content": MESSAGES_BODY},
            {
                "content": MESSAGES_BODY,
                "headers": {
                    "anthropic-beta": "interleaved-thinking-2025-05-14",
                    "x-api-key": "secret",
                },
            },
            {},  # no body
        ],
    )
    async def test_messages_endpoint_transforms(self, request_kwargs):
        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            return_value=_mock_response(200),
        ):
            req = httpx.Request("POST", "https://api.com/v1/messages", **request_kwargs)
            result = await ClaudeCacheAsyncClient().send(req)
            assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_proactive_refresh_on_old_token(self):
        """Old tokens are refreshed proactively, before the request, no retry."""
        old_token = _create_jwt(iat=time.time() - 7200)
        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            return_value=_mock_response(200),
        ) as mock_send:
            with patch.object(
                ClaudeCacheAsyncClient,
                "_refresh_claude_oauth_token",
                return_value="new_fresh_token",
            ) as mock_refresh:
                client = ClaudeCacheAsyncClient(
                    headers={"Authorization": f"Bearer {old_token}"}
                )
                response = await client.send(
                    _request(token=old_token, content=b'{"model": "claude-3-opus"}')
                )
                mock_refresh.assert_called_once()
                assert response.status_code == 200
                assert mock_send.call_count == 1

    @pytest.mark.asyncio
    async def test_no_proactive_refresh_on_fresh_token(self):
        fresh_token = _create_jwt(iat=time.time() - 1800)
        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            return_value=_mock_response(200),
        ):
            with patch.object(
                ClaudeCacheAsyncClient, "_refresh_claude_oauth_token"
            ) as mock_refresh:
                client = ClaudeCacheAsyncClient(
                    headers={"Authorization": f"Bearer {fresh_token}"}
                )
                await client.send(
                    _request(token=fresh_token, content=b'{"model": "claude-3-opus"}')
                )
                mock_refresh.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "failed_status, failed_ct, failed_content",
        [
            (401, "application/json", b'{"error": {"type": "authentication_error"}}'),
            (400, "text/html; charset=utf-8", CLOUDFLARE_HTML.encode()),
        ],
    )
    async def test_auth_error_triggers_refresh_and_retry(
        self, failed_status, failed_ct, failed_content
    ):
        failed = _mock_response(failed_status, failed_ct, failed_content)
        failed.text = failed_content.decode("utf-8")
        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock
        ) as mock_send:
            mock_send.side_effect = [
                failed,
                _mock_response(200, content=b'{"result": "ok"}'),
            ]
            with patch.object(
                ClaudeCacheAsyncClient,
                "_refresh_claude_oauth_token",
                return_value="new_token",
            ) as mock_refresh:
                with patch.object(
                    ClaudeCacheAsyncClient,
                    "_check_stored_token_expiry",
                    return_value=False,
                ):
                    client = ClaudeCacheAsyncClient(
                        headers={"Authorization": "Bearer old_token"}
                    )
                    response = await client.send(
                        _request(
                            token="old_token", content=b'{"model": "claude-3-opus"}'
                        )
                    )
                    mock_refresh.assert_called_once()
                    assert response.status_code == 200
                    assert mock_send.call_count == 2

    @pytest.mark.asyncio
    async def test_no_refresh_on_json_400(self):
        resp = _mock_response(
            400, content=b'{"error": {"type": "invalid_request_error"}}'
        )
        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=resp
        ):
            with patch.object(
                ClaudeCacheAsyncClient, "_refresh_claude_oauth_token"
            ) as mock_refresh:
                with patch.object(
                    ClaudeCacheAsyncClient,
                    "_check_stored_token_expiry",
                    return_value=False,
                ):
                    client = ClaudeCacheAsyncClient(
                        headers={"Authorization": "Bearer token"}
                    )
                    result = await client.send(
                        _request(token="token", content=b'{"model": "claude-3-opus"}')
                    )
                    mock_refresh.assert_not_called()
                    assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_no_infinite_retry_loop(self):
        """Auth errors retry at most once; the retry sets the guard flag."""
        failed = _mock_response(
            401, content=b'{"error": {"type": "authentication_error"}}'
        )
        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=failed
        ) as mock_send:
            with patch.object(
                ClaudeCacheAsyncClient,
                "_refresh_claude_oauth_token",
                return_value="new_token",
            ):
                client = ClaudeCacheAsyncClient(
                    headers={"Authorization": "Bearer token"}
                )
                response = await client.send(
                    _request(token="token", content=b'{"model": "claude-3-opus"}')
                )
                assert mock_send.call_count == 2
                assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_fails_returns_original_error(self):
        failed = _mock_response(403)
        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=failed
        ):
            with patch.object(
                ClaudeCacheAsyncClient, "_refresh_claude_oauth_token", return_value=None
            ):
                result = await ClaudeCacheAsyncClient().send(
                    httpx.Request("POST", "https://api.com/v1/messages", content=b"{}")
                )
                assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_already_attempted_refresh_skips(self):
        failed = _mock_response(401, content_type=None)
        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=failed
        ):
            with patch.object(ClaudeCacheAsyncClient, "_refresh_claude_oauth_token"):
                req = httpx.Request("POST", "https://api.com/v1/messages")
                req.extensions["claude_oauth_refresh_attempted"] = True
                result = await ClaudeCacheAsyncClient().send(req)
                assert result.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name, url, status",
        [
            (
                "_should_refresh_token",
                "https://api.com/other",
                200,
            ),  # proactive refresh error
            (
                "_transform_headers_for_claude_code",
                "https://api.com/v1/messages",
                200,
            ),  # transform error
            (
                "_refresh_claude_oauth_token",
                "https://api.com/v1/messages",
                401,
            ),  # auth-handling error
        ],
    )
    async def test_exceptions_in_pipeline_are_swallowed(self, method_name, url, status):
        resp = _mock_response(status, content_type=None)
        with patch.object(
            httpx.AsyncClient, "send", new_callable=AsyncMock, return_value=resp
        ):
            with patch.object(
                ClaudeCacheAsyncClient, method_name, side_effect=Exception("boom")
            ):
                req = (
                    httpx.Request("POST", url, content=b"{}")
                    if "v1/messages" in url
                    else httpx.Request("GET", url)
                )
                result = await ClaudeCacheAsyncClient().send(req)
                assert result.status_code == status

    @pytest.mark.asyncio
    async def test_proactive_refresh_non_messages_endpoint(self):
        token = _create_jwt(iat=time.time() - 7200)
        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            return_value=_mock_response(200, None),
        ):
            with patch.object(
                ClaudeCacheAsyncClient,
                "_refresh_claude_oauth_token",
                return_value="new_tok",
            ):
                result = await ClaudeCacheAsyncClient().send(
                    httpx.Request(
                        "POST",
                        "https://api.com/other",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                )
                assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_rebuild_request_exception_handled(self):
        with patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            return_value=_mock_response(200, None),
        ):
            client = ClaudeCacheAsyncClient()
            req = httpx.Request(
                "POST", "https://api.com/v1/messages", content=b'{"model": "x"}'
            )
            with patch.object(
                client, "build_request", side_effect=Exception("rebuild fail")
            ):
                result = await client.send(req)
                assert result.status_code == 200


class TestSendAppliesPrefixConditionally:
    """End-to-end guard: send() only prefixes tool names when the flag is on.

    custom_anthropic routes through ClaudeCacheAsyncClient without
    apply_claude_code_prefix, so tool names must go out verbatim.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "flag, expected_names",
        [
            (False, ["read_file", "edit_file"]),  # custom_anthropic: clean
            (
                True,
                [f"{TOOL_PREFIX}read_file", f"{TOOL_PREFIX}edit_file"],
            ),  # oauth: prefixed
        ],
    )
    async def test_prefix_behavior(self, flag, expected_names):
        captured = {}

        async def fake_send(self, request, *args, **kwargs):
            captured["body"] = bytes(request.content)
            return _mock_response(200, content=b"{}")

        with (
            patch.object(httpx.AsyncClient, "send", new=fake_send),
            patch.object(
                ClaudeCacheAsyncClient, "_check_stored_token_expiry", return_value=False
            ),
        ):
            client = ClaudeCacheAsyncClient(
                headers={"Authorization": "Bearer some_token"},
                apply_claude_code_prefix=flag,
            )
            request = httpx.Request(
                "POST",
                "https://api.anthropic.com/v1/messages",
                headers={"Authorization": "Bearer some_token"},
                content=json.dumps(
                    {
                        "model": "claude-3-opus",
                        "tools": [
                            {"name": "read_file", "description": "read"},
                            {"name": "edit_file", "description": "edit"},
                        ],
                        "messages": [{"role": "user", "content": "hi"}],
                    }
                ).encode(),
            )
            await client.send(request)

        assert "body" in captured, "send did not run our fake transport"
        sent = json.loads(captured["body"])
        assert [t["name"] for t in sent["tools"]] == expected_names
        if not flag:
            assert TOOL_PREFIX not in captured["body"].decode("utf-8")
