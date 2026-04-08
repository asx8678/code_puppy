"""Cache helpers for Claude Code / Anthropic.

ClaudeCacheAsyncClient: httpx client that tries to patch /v1/messages bodies.

We now also expose `patch_anthropic_client_messages` which monkey-patches
AsyncAnthropic.messages.create() so we can inject cache_control BEFORE
serialization, avoiding httpx/Pydantic internals.

This module also handles:
- Tool name prefixing/unprefixing for Claude Code OAuth compatibility
- Header transformations (anthropic-beta, user-agent)
- URL modifications (adding ?beta=true query param)
"""

import asyncio
import json
import logging
import time
from functools import lru_cache
from typing import Any, Callable, MutableMapping
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
import jwt as _jwt

from .request_cache import RequestCacheMixin

logger = logging.getLogger(__name__)

# Refresh token if it's older than the configured max age (seconds)
TOKEN_MAX_AGE_SECONDS = 3600

# Retry configuration
RETRY_STATUS_CODES = (429, 500, 502, 503, 504)
MAX_RETRIES = 5

# Tool name prefix for Claude Code OAuth compatibility
# Tools are prefixed on outgoing requests and unprefixed on incoming responses
TOOL_PREFIX = "cp_"

# User-Agent to send with Claude Code OAuth requests
CLAUDE_CLI_USER_AGENT = "claude-cli/2.1.2 (external, cli)"

# Required betas for Claude Code OAuth (base set)
REQUIRED_BETAS_BASE = ("oauth-2025-04-20", "interleaved-thinking-2025-05-14")
REQUIRED_BETAS_BASE_SET = frozenset(REQUIRED_BETAS_BASE)

# Optional beta that gets added if present in incoming headers
CLAUDE_CODE_BETA_OPTIONAL = "claude-code-20250219"

# X-API-Key header variants to remove (using Bearer auth instead)
X_API_KEY_VARIANTS = ("x-api-key", "X-API-Key", "X-Api-Key")

try:
    from anthropic import AsyncAnthropic
except ImportError:  # pragma: no cover - optional dep
    AsyncAnthropic = None  # type: ignore


@lru_cache(maxsize=16)
def _get_jwt_iat(token: str) -> int:
    """Decode a JWT and return its 'iat' (issued at) claim.

    Cached with LRU to avoid repeated decoding of the same token.
    Returns 0 if the token can't be decoded or has no valid 'iat' claim.
    Validates that 'iat' is numeric and within reasonable bounds.
    """
    # NOTE: JWT signature is not verified; only used for cache age calculation.
    try:
        payload = _jwt.decode(token, options={"verify_signature": False})
        iat = payload.get("iat")
        # Validate iat is a number
        if not isinstance(iat, (int, float)):
            return 0
        # Validate iat is positive and not absurdly large (max 10 years in future)
        now = time.time()
        if iat <= 0 or iat > now + 86400 * 365 * 10:
            return 0
        return int(iat)
    except Exception:
        return 0


class ClaudeCacheAsyncClient(RequestCacheMixin, httpx.AsyncClient):
    """Async HTTP client with Claude Code OAuth transformations.

    Handles:
    - Cache control injection for prompt caching
    - Tool name prefixing on outgoing requests
    - Tool name unprefixing on incoming streaming responses
    - Header transformations (anthropic-beta, user-agent)
    - URL modifications (adding ?beta=true)
    - Proactive token refresh
    - Request caching for header-only change optimization
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Initialize request cache with larger capacity for Claude (more diverse requests)
        self._init_request_cache(max_size=256, ttl_seconds=300)
        # Performance tracking
        self._request_build_time_saved_ms = 0.0
        self._requests_optimized = 0
        # JWT age caching: avoid repeated base64+JSON decoding on every request
        self._cached_token: str | None = None
        self._cached_iat: int = 0

    def _get_jwt_age_seconds(self, token: str | None) -> float | None:
        """Decode a JWT and return its age in seconds.

        Returns None if the token can't be decoded or has no timestamp claims.
        Uses cached 'iat' (issued at) value when the same token is passed,
        avoiding repeated base64+JSON decoding on every API request.
        """
        if not token:
            return None

        try:
            # Check instance cache first to avoid repeated decoding
            if self._cached_token == token and self._cached_iat:
                return time.time() - self._cached_iat

            # Cache miss: decode the token
            # Use cached JWT iat extraction function
            iat = _get_jwt_iat(token)
            if iat:
                # Update instance cache
                self._cached_token = token
                self._cached_iat = iat
                return time.time() - iat

            # Fall back to calculating from 'exp' claim
            try:
                payload = _jwt.decode(token, options={"verify_signature": False})
            except Exception:
                return None

            now = time.time()
            if "exp" in payload:
                exp = payload["exp"]
                # Validate exp is a number
                if not isinstance(exp, (int, float)):
                    return None
                exp = float(exp)
                # Validate exp is within reasonable bounds
                if exp <= 0 or exp > now + 86400 * 365 * 100:  # max 100 years in future
                    return None
                # If exp is in the future, calculate how long until expiry
                # and assume the token was issued TOKEN_MAX_AGE_SECONDS before expiry
                time_until_exp = exp - now
                # If token has less than TOKEN_MAX_AGE_SECONDS left, it's "old"
                age = TOKEN_MAX_AGE_SECONDS - time_until_exp
                return max(0, age)

            return None
        except Exception as exc:
            logger.debug("Failed to decode JWT age: %s", exc)
            return None

    def _extract_bearer_token(self, request: httpx.Request) -> str | None:
        """Extract the bearer token from request headers."""
        auth_header = request.headers.get("Authorization") or request.headers.get(
            "authorization"
        )
        if auth_header and auth_header.lower().startswith("bearer "):
            return auth_header[7:]  # Strip "Bearer " prefix
        return None

    def _should_refresh_token(self, request: httpx.Request) -> bool:
        """Check if the token should be refreshed (within the max-age window).

        Uses two strategies:
        1. Decode JWT to check token age (if possible)
        2. Fall back to stored expires_at from token file

        Returns True if token expires within TOKEN_MAX_AGE_SECONDS.
        """
        token = self._extract_bearer_token(request)
        if not token:
            return False

        # Strategy 1: Try to decode JWT age
        age = self._get_jwt_age_seconds(token)
        if age is not None:
            should_refresh = age >= TOKEN_MAX_AGE_SECONDS
            if should_refresh:
                logger.info(
                    "JWT token is %.1f seconds old (>= %d), will refresh proactively",
                    age,
                    TOKEN_MAX_AGE_SECONDS,
                )
            return should_refresh

        # Strategy 2: Fall back to stored expires_at from token file
        should_refresh = self._check_stored_token_expiry()
        if should_refresh:
            logger.info(
                "Stored token expires within %d seconds, will refresh proactively",
                TOKEN_MAX_AGE_SECONDS,
            )
        return should_refresh

    @staticmethod
    def _check_stored_token_expiry() -> bool:
        """Check if the stored token expires within TOKEN_MAX_AGE_SECONDS.

        This is a fallback for when JWT decoding fails or isn't available.
        Uses the expires_at timestamp from the stored token file.
        """
        try:
            from code_puppy.plugins.claude_code_oauth.utils import (
                is_token_expired,
                load_stored_tokens,
            )

            tokens = load_stored_tokens()
            if not tokens:
                return False

            # is_token_expired already uses the configured refresh buffer window
            return is_token_expired(tokens)
        except Exception as exc:
            logger.debug("Error checking stored token expiry: %s", exc)
            return False

    @staticmethod
    def _transform_request_body(body: bytes) -> tuple[bytes | None, bool, bool]:
        """Single-pass transform for tool prefixing and cache_control injection.

        Parses the JSON body once and applies both transformations:
        1. Prefixes tool names with TOOL_PREFIX for Claude Code OAuth compatibility
        2. Injects cache_control into the last message's last content block

        Returns: (transformed_body_or_None, tools_modified, cache_modified)
        """
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            return None, False, False

        if not isinstance(data, dict):
            return None, False, False

        tools_modified = False
        cache_modified = False

        # 1. Prefix tool names
        tools = data.get("tools")
        if isinstance(tools, list) and tools:
            for tool in tools:
                if isinstance(tool, dict) and "name" in tool:
                    name = tool["name"]
                    if name and not name.startswith(TOOL_PREFIX):
                        tool["name"] = f"{TOOL_PREFIX}{name}"
                        tools_modified = True

        # 2. Inject cache_control into last message's last content block
        messages = data.get("messages")
        if isinstance(messages, list) and messages:
            last = messages[-1]
            if isinstance(last, dict):
                content = last.get("content")
                if isinstance(content, list) and content:
                    last_block = content[-1]
                    if (
                        isinstance(last_block, dict)
                        and "cache_control" not in last_block
                    ):
                        last_block["cache_control"] = {"type": "ephemeral"}
                        cache_modified = True

        if not tools_modified and not cache_modified:
            return None, False, False

        return json.dumps(data).encode("utf-8"), tools_modified, cache_modified

    @staticmethod
    def _prefix_tool_names(body: bytes) -> bytes | None:
        """Prefix all tool names in the request body with TOOL_PREFIX.

        This is required for Claude Code OAuth compatibility - tools must be
        prefixed on outgoing requests and unprefixed on incoming responses.
        """
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            return None

        if not isinstance(data, dict):
            return None

        tools = data.get("tools")
        if not isinstance(tools, list) or not tools:
            return None

        modified = False
        for tool in tools:
            if isinstance(tool, dict) and "name" in tool:
                name = tool["name"]
                if name and not name.startswith(TOOL_PREFIX):
                    tool["name"] = f"{TOOL_PREFIX}{name}"
                    modified = True

        if not modified:
            return None

        return json.dumps(data).encode("utf-8")

    @staticmethod
    def _transform_headers_for_claude_code(headers: MutableMapping[str, str]) -> None:
        """Transform headers for Claude Code OAuth compatibility.

        - Sets user-agent to claude-cli
        - Merges anthropic-beta headers appropriately
        - Removes x-api-key (using Bearer auth instead)
        """
        # Set user-agent
        headers["user-agent"] = CLAUDE_CLI_USER_AGENT

        # Handle anthropic-beta header — merge required betas with any
        # extras already present (e.g. context-1m-2025-08-07).
        incoming_beta = headers.get("anthropic-beta", "")
        incoming_betas = [b.strip() for b in incoming_beta.split(",") if b.strip()]

        # Build required set based on base required betas + optional claude-code beta
        required_set = REQUIRED_BETAS_BASE_SET
        if CLAUDE_CODE_BETA_OPTIONAL in incoming_betas:
            required_set = required_set | {CLAUDE_CODE_BETA_OPTIONAL}

        # Merge: start with required base, then optional, then append extras
        merged = list(REQUIRED_BETAS_BASE)
        if CLAUDE_CODE_BETA_OPTIONAL in incoming_betas:
            merged.append(CLAUDE_CODE_BETA_OPTIONAL)
        for beta in incoming_betas:
            if beta not in required_set:
                merged.append(beta)

        headers["anthropic-beta"] = ",".join(merged)

        # Remove x-api-key if present (we use Bearer auth instead)
        for key in X_API_KEY_VARIANTS:
            if key in headers:
                del headers[key]

    @staticmethod
    def _add_beta_query_param(url: httpx.URL) -> httpx.URL:
        """Add ?beta=true query parameter to the URL if not already present."""
        # Parse the URL
        parsed = urlparse(str(url))
        query_params = parse_qs(parsed.query)

        # Only add if not already present
        if "beta" not in query_params:
            query_params["beta"] = ["true"]
            # Rebuild query string
            new_query = urlencode(query_params, doseq=True)
            # Rebuild URL
            new_parsed = parsed._replace(query=new_query)
            return httpx.URL(urlunparse(new_parsed))

        return url

    async def send(
        self, request: httpx.Request, *args: Any, **kwargs: Any
    ) -> httpx.Response:  # type: ignore[override]
        is_messages_endpoint = request.url.path.endswith("/v1/messages")
        rebuild_start = time.perf_counter()
        used_cache = False

        # Proactive token refresh: check JWT age before every request
        if not request.extensions.get("claude_oauth_refresh_attempted"):
            try:
                if self._should_refresh_token(request):
                    refreshed_token = self._refresh_claude_oauth_token()
                    if refreshed_token:
                        logger.info("Proactively refreshed token before request")
                        # Rebuild request with new token - USE CACHE for header-only change
                        headers = dict(request.headers)
                        self._update_auth_headers(headers, refreshed_token)
                        body_bytes = self._extract_body_bytes(request)
                        request = self.cached_or_build_request(
                            method=request.method,
                            url=request.url,
                            headers=headers,
                            content=body_bytes,
                        )
                        used_cache = True
                        request.extensions["claude_oauth_refresh_attempted"] = True
            except Exception as exc:
                logger.debug("Error during proactive token refresh check: %s", exc)

        # Apply Claude Code OAuth transformations for /v1/messages
        if is_messages_endpoint:
            try:
                body_bytes = self._extract_body_bytes(request)
                headers = dict(request.headers)
                url = request.url
                body_modified = False
                headers_modified = False

                # 1. Transform headers for Claude Code OAuth
                self._transform_headers_for_claude_code(headers)
                headers_modified = True

                # 2. Add ?beta=true query param
                url = self._add_beta_query_param(url)

                # 3. Transform request body (tool prefixing + cache_control in one pass)
                if body_bytes:
                    transformed_body, _, _ = self._transform_request_body(body_bytes)
                    if transformed_body is not None:
                        body_bytes = transformed_body
                        body_modified = True

                # Rebuild request if anything changed - USE CACHE for optimization
                if body_modified or headers_modified or url != request.url:
                    try:
                        # Optimization: skip rebuild for header-only changes
                        # Body re-encode is expensive; if only headers changed, mutate directly
                        if not body_modified and url == request.url:
                            # Header-only change: mutate headers directly, skip rebuild
                            for key, value in headers.items():
                                request.headers[key] = value
                            used_cache = True
                        else:
                            # Body or URL changed: need full rebuild
                            rebuilt = self.cached_or_build_request(
                                method=request.method,
                                url=url,
                                headers=headers,
                                content=body_bytes,
                            )
                            used_cache = True

                            # Copy core internals so httpx uses the modified body/stream
                            if hasattr(rebuilt, "_content"):
                                request._content = rebuilt._content  # type: ignore[attr-defined]
                            if hasattr(rebuilt, "stream"):
                                request.stream = rebuilt.stream
                            if hasattr(rebuilt, "extensions"):
                                request.extensions = rebuilt.extensions

                            # Update URL
                            request.url = url

                            # Update headers
                            for key, value in headers.items():
                                request.headers[key] = value

                            # Ensure Content-Length matches the new body
                            if body_bytes:
                                request.headers["Content-Length"] = str(len(body_bytes))

                    except Exception as exc:
                        logger.debug("Error rebuilding request: %s", exc)

            except Exception as exc:
                logger.debug("Error in Claude Code transformations: %s", exc)

        # Track performance metrics
        if used_cache:
            rebuild_time = (time.perf_counter() - rebuild_start) * 1000
            self._requests_optimized += 1
            estimated_saved = max(0, 5.0 - rebuild_time)
            self._request_build_time_saved_ms += estimated_saved
            logger.debug(
                "Request optimized via cache (took %.2fms, saved ~%.2fms)",
                rebuild_time,
                estimated_saved,
            )

        # Send the request with retry logic for transient errors
        response = await self._send_with_retries(request, *args, **kwargs)

        # NOTE: Tool name unprefixing is now handled at the pydantic-ai level
        # in pydantic_patches.py rather than wrapping the HTTP response stream.
        # The response wrapper caused zlib decompression errors due to httpx
        # response lifecycle issues.

        # Handle auth errors with token refresh
        try:
            if response.status_code in (400, 401, 403) and not request.extensions.get(
                "claude_oauth_refresh_attempted"
            ):
                is_auth_error = response.status_code in (401, 403)

                if response.status_code == 400:
                    is_auth_error = await self._is_cloudflare_html_error(response)
                    if is_auth_error:
                        logger.info(
                            "Detected Cloudflare 400 error (likely auth-related), attempting token refresh"
                        )

                if is_auth_error:
                    refreshed_token = self._refresh_claude_oauth_token()
                    if refreshed_token:
                        logger.info("Token refreshed successfully, retrying request")
                        await response.aclose()
                        body_bytes = self._extract_body_bytes(request)
                        headers = dict(request.headers)
                        self._update_auth_headers(headers, refreshed_token)
                        # Use cached request building for retry optimization
                        retry_request = self.cached_or_build_request(
                            method=request.method,
                            url=request.url,
                            headers=headers,
                            content=body_bytes,
                        )
                        retry_request.extensions["claude_oauth_refresh_attempted"] = (
                            True
                        )
                        return await self._send_with_retries(
                            retry_request, *args, **kwargs
                        )
                    else:
                        logger.warning("Token refresh failed, returning original error")
        except Exception as exc:
            logger.debug("Error during token refresh attempt: %s", exc)

        return response

    async def _send_with_retries(
        self, request: httpx.Request, *args: Any, **kwargs: Any
    ) -> httpx.Response:
        """Send request with automatic retries for rate limits and server errors.

        Retries on:
        - 429 (rate limit) - respects Retry-After header
        - 500, 502, 503, 504 (server errors) - exponential backoff
        - Connection errors (ConnectError, ReadTimeout, PoolTimeout)
        """
        last_response = None
        last_exception = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await super().send(request, *args, **kwargs)
                last_response = response

                # Check for retryable status
                if response.status_code not in RETRY_STATUS_CODES:
                    return response

                # Don't retry if this is the last attempt
                if attempt >= MAX_RETRIES:
                    return response

                # Close response before retrying
                await response.aclose()

                # Calculate wait time with exponential backoff
                wait_time = 1.0 * (2**attempt)  # 1s, 2s, 4s, 8s, 16s

                # For 429, respect Retry-After header if present
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            wait_time = float(retry_after)
                        except ValueError:
                            # Try parsing http-date format
                            try:
                                from email.utils import parsedate_to_datetime

                                date = parsedate_to_datetime(retry_after)
                                wait_time = max(0, date.timestamp() - time.time())
                            except Exception:
                                pass

                # Cap wait time between 0.5s and 60s
                wait_time = max(0.5, min(wait_time, 60.0))

                logger.info(
                    "HTTP %d received, retrying in %.1fs (attempt %d/%d)",
                    response.status_code,
                    wait_time,
                    attempt + 1,
                    MAX_RETRIES,
                )
                await asyncio.sleep(wait_time)

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.PoolTimeout) as exc:
                last_exception = exc

                # Don't retry if this is the last attempt
                if attempt >= MAX_RETRIES:
                    raise

                wait_time = 1.0 * (2**attempt)
                wait_time = max(0.5, min(wait_time, 60.0))

                logger.warning(
                    "HTTP connection error: %s. Retrying in %.1fs (attempt %d/%d)",
                    exc,
                    wait_time,
                    attempt + 1,
                    MAX_RETRIES,
                )
                await asyncio.sleep(wait_time)

            except Exception:
                # Don't retry on other exceptions (e.g., validation errors)
                raise

        # Return last response if we have one
        if last_response is not None:
            return last_response

        # Re-raise last exception if we have one
        if last_exception is not None:
            raise last_exception

        # This shouldn't happen, but just in case
        raise RuntimeError("Retry loop completed without response or exception")

    @staticmethod
    def _extract_body_bytes(request: httpx.Request) -> bytes | None:
        # Try public content first
        try:
            content = request.content
            if content:
                return content
        except Exception:
            pass

        # Fallback to private attr if necessary
        try:
            content = getattr(request, "_content", None)
            if content:
                return content
        except Exception:
            pass

        return None

    @staticmethod
    def _update_auth_headers(
        headers: MutableMapping[str, str], access_token: str
    ) -> None:
        bearer_value = f"Bearer {access_token}"
        if "Authorization" in headers or "authorization" in headers:
            headers["Authorization"] = bearer_value
        elif "x-api-key" in headers or "X-API-Key" in headers:
            headers["x-api-key"] = access_token
        else:
            headers["Authorization"] = bearer_value

    @staticmethod
    async def _is_cloudflare_html_error(response: httpx.Response) -> bool:
        """Check if this is a Cloudflare HTML error response.

        Cloudflare often returns HTML error pages with status 400 when
        there are authentication issues.
        """
        # Check content type
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type.lower():
            return False

        # Check if body contains Cloudflare markers
        try:
            # For async httpx, we need to read the body first
            if not hasattr(response, "_content") or not response._content:
                try:
                    await response.aread()
                except Exception as read_exc:
                    logger.debug("Failed to read response body: %s", read_exc)
                    return False

            # Now we can safely access the content
            if hasattr(response, "_content") and response._content:
                body = response._content.decode("utf-8", errors="ignore")
            else:
                # Fallback to text property (should work after aread)
                try:
                    body = response.text
                except Exception:
                    return False

            # Look for Cloudflare and 400 Bad Request markers
            body_lower = body.lower()
            return "cloudflare" in body_lower and "400 bad request" in body_lower
        except Exception as exc:
            logger.debug("Error checking for Cloudflare error: %s", exc)
            return False

    def _refresh_claude_oauth_token(self) -> str | None:
        try:
            from code_puppy.plugins.claude_code_oauth.utils import refresh_access_token

            logger.info("Attempting to refresh Claude Code OAuth token...")
            refreshed_token = refresh_access_token(force=True)
            if refreshed_token:
                self._update_auth_headers(self.headers, refreshed_token)
                # Clear JWT age cache when token changes
                self._cached_token = None
                self._cached_iat = 0
                logger.info("Successfully refreshed Claude Code OAuth token")
            else:
                logger.warning("Token refresh returned None")
            return refreshed_token
        except Exception as exc:
            logger.error("Exception during token refresh: %s", exc)
            return None

    def get_performance_stats(self) -> dict[str, Any]:
        """Get performance statistics for this client.

        Returns:
            Dict with performance metrics including:
            - requests_optimized: Number of requests that used cache
            - time_saved_ms: Estimated time saved from avoiding rebuilds
            - cache_stats: Detailed cache statistics
        """
        cache_stats = self.get_cache_stats()
        return {
            "requests_optimized": self._requests_optimized,
            "estimated_time_saved_ms": self._request_build_time_saved_ms,
            "cache": cache_stats,
        }

    @staticmethod
    def _inject_cache_control(body: bytes) -> bytes | None:
        # Skip if SDK already injected cache_control (fast path avoids JSON parse)
        # Check for the marker: "_cache_control_sdk_injected": true
        # Note: We need to strip the marker even if we skip injection
        if b'"_cache_control_sdk_injected"' in body:
            try:
                data = json.loads(body.decode("utf-8"))
                if isinstance(data, dict) and "_cache_control_sdk_injected" in data:
                    # Strip the marker before sending to Anthropic
                    del data["_cache_control_sdk_injected"]
                    return json.dumps(data).encode("utf-8")
            except Exception:
                pass  # Fall through to normal flow if stripping fails
            return None

        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            return None

        if not isinstance(data, dict):
            return None

        modified = False

        # Minimal, deterministic strategy:
        # Add cache_control only on the single most recent block:
        # the last dict content block of the last message (if any).
        messages = data.get("messages")
        if isinstance(messages, list) and messages:
            last = messages[-1]
            if isinstance(last, dict):
                content = last.get("content")
                if isinstance(content, list) and content:
                    last_block = content[-1]
                    if (
                        isinstance(last_block, dict)
                        and "cache_control" not in last_block
                    ):
                        last_block["cache_control"] = {"type": "ephemeral"}
                        modified = True

        if not modified:
            return None

        return json.dumps(data).encode("utf-8")


def _inject_cache_control_in_payload(payload: dict[str, Any]) -> bool:
    """In-place cache_control injection on Anthropic messages.create payload.

    Returns True if cache_control was injected, False otherwise.
    """
    injected = False
    messages = payload.get("messages")
    if isinstance(messages, list) and messages:
        last = messages[-1]
        if isinstance(last, dict):
            content = last.get("content")
            if isinstance(content, list) and content:
                last_block = content[-1]
                if isinstance(last_block, dict) and "cache_control" not in last_block:
                    last_block["cache_control"] = {"type": "ephemeral"}
                    injected = True

    # Add marker so HTTP-level injection can skip redundant parsing
    if injected:
        payload["_cache_control_sdk_injected"] = True
    return injected


def patch_anthropic_client_messages(client: Any) -> None:
    """Monkey-patch AsyncAnthropic.messages.create to inject cache_control.

    This operates at the highest level: just before Anthropic SDK serializes
    the request into HTTP. That means no httpx / Pydantic shenanigans can
    undo it.
    """

    if AsyncAnthropic is None or not isinstance(client, AsyncAnthropic):  # type: ignore[arg-type]
        return

    try:
        messages_obj = getattr(client, "messages", None)
        if messages_obj is None:
            return
        original_create: Callable[..., Any] = messages_obj.create
    except Exception:  # pragma: no cover - defensive
        return

    async def wrapped_create(*args: Any, **kwargs: Any):
        # Anthropic messages.create takes a mix of positional/kw args.
        # The payload is usually in kwargs for the Python SDK.
        if kwargs:
            _inject_cache_control_in_payload(kwargs)
        elif args:
            maybe_payload = args[-1]
            if isinstance(maybe_payload, dict):
                _inject_cache_control_in_payload(maybe_payload)

        return await original_create(*args, **kwargs)

    messages_obj.create = wrapped_create  # type: ignore[assignment]
