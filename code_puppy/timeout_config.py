"""Unified HTTP timeout strategy for Code Puppy.

This module defines a single source of truth for all HTTP timeouts
used across the codebase. Import these constants instead of hardcoding
timeout values.

Timeout strategy:
- HTTP_CONNECT_TIMEOUT: Time to establish a TCP/TLS connection (30s)
- HTTP_READ_TIMEOUT: Time to wait for response data (180s) - default for most HTTP clients
- HTTP_LLM_STREAMING_TIMEOUT: Extended timeout for LLM streaming responses (300s)

Usage:
    from code_puppy.timeout_config import (
        HTTP_CONNECT_TIMEOUT,
        HTTP_READ_TIMEOUT,
        HTTP_LLM_STREAMING_TIMEOUT,
        get_timeout_config,
    )

    # For standard HTTP clients
    client = httpx.AsyncClient(timeout=HTTP_READ_TIMEOUT)

    # For LLM streaming clients (with separate connect/read)
    client = httpx.AsyncClient(timeout=get_timeout_config("llm_streaming"))
"""

from typing import Final

import httpx

# Connect timeout: maximum time to establish a TCP/TLS connection
HTTP_CONNECT_TIMEOUT: Final[float] = 30.0

# Read timeout: maximum time to wait for response data after connection
HTTP_READ_TIMEOUT: Final[float] = 180.0

# LLM streaming timeout: extended timeout for long-running streaming responses
HTTP_LLM_STREAMING_TIMEOUT: Final[float] = 300.0


def get_timeout_config(preset: str = "default") -> httpx.Timeout:
    """Get a pre-configured httpx.Timeout object for common use cases.

    Args:
        preset: One of "default", "llm_streaming", or "quick".

    Returns:
        An httpx.Timeout instance with the appropriate settings.

    Examples:
        >>> timeout = get_timeout_config("default")
        >>> client = httpx.AsyncClient(timeout=timeout)

        >>> timeout = get_timeout_config("llm_streaming")
        >>> client = httpx.AsyncClient(timeout=timeout)
    """
    if preset == "llm_streaming":
        # LLM streaming: long read timeout, standard connect timeout
        return httpx.Timeout(HTTP_LLM_STREAMING_TIMEOUT, connect=HTTP_CONNECT_TIMEOUT)
    elif preset == "quick":
        # Quick requests: short timeouts for health checks, etc.
        return httpx.Timeout(10.0, connect=5.0)
    else:
        # Default: standard read timeout (single value for connect and read)
        return httpx.Timeout(HTTP_READ_TIMEOUT, connect=HTTP_CONNECT_TIMEOUT)
