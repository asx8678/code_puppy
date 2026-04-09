"""LangSmith tracing plugin – observability for agent runs and tool calls.

Auto-enables when LANGSMITH_API_KEY environment variable is present.
Provides distributed tracing with span nesting (agent runs as parent spans,
tool calls as child spans).

Environment Variables:
    LANGSMITH_API_KEY: Required to enable the plugin
    LANGSMITH_PROJECT: Optional project name (defaults to 'default')
    LANGSMITH_BASE_URL: Optional custom API endpoint
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any, Optional

from code_puppy.async_utils import warn_once
from code_puppy.callbacks import register_callback
from code_puppy.reflection import resolve_variable

logger = logging.getLogger(__name__)

# =============================================================================
# Feature Detection & Auto-Enable Logic
# =============================================================================

# Read environment variables at module load time
LANGSMITH_API_KEY = os.environ.get("LANGSMITH_API_KEY")
LANGSMITH_PROJECT = os.environ.get("LANGSMITH_PROJECT", "default")
LANGSMITH_BASE_URL = os.environ.get("LANGSMITH_BASE_URL")

# Module-level state for the LangSmith client and active traces
_langsmith_client: Any = None
_active_traces: dict[str, Any] = {}  # session_id -> trace context
_tool_spans: dict[str, Any] = {}  # run_id -> current tool span
_warned_missing = False
_test_client: Any = None  # For test injection


def _reset_state():
    """Reset module state - useful for testing."""
    global _langsmith_client, _active_traces, _tool_spans, _warned_missing, _test_client
    _langsmith_client = None
    _active_traces = {}
    _tool_spans = {}
    _warned_missing = False
    _test_client = None


def _set_test_client(client: Any | None) -> None:
    """Set a mock client for testing. Pass None to clear."""
    global _test_client
    _test_client = client


def _get_langsmith_client() -> Any | None:
    """Lazy-load the LangSmith client using resolve_variable.

    Returns None if langsmith package is not installed.
    Uses warn_once to hint at installation on first failure.
    """
    global _langsmith_client, _warned_missing, _test_client

    # Test override - use injected mock if available
    if _test_client is not None:
        return _test_client

    if _langsmith_client is not None:
        return _langsmith_client

    # Only try to load if API key is set
    if not LANGSMITH_API_KEY:
        return None

    try:
        # Use reflection to gracefully handle missing langsmith package
        Client = resolve_variable("langsmith:Client")

        # Build client kwargs
        client_kwargs: dict[str, Any] = {
            "api_key": LANGSMITH_API_KEY,
        }
        if LANGSMITH_BASE_URL:
            client_kwargs["api_url"] = LANGSMITH_BASE_URL

        _langsmith_client = Client(**client_kwargs)
        logger.debug("LangSmith client initialized successfully")
        return _langsmith_client

    except ImportError:
        if not _warned_missing:
            warn_once(
                "langsmith_missing",
                "LangSmith tracing enabled (LANGSMITH_API_KEY set) but 'langsmith' package not installed. "
                "Install with: pip install langsmith",
                logger,
            )
            _warned_missing = True
        return None
    except Exception as e:
        logger.warning(f"Failed to initialize LangSmith client: {e}")
        return None


def _is_plugin_active() -> bool:
    """Check if plugin should be active (env var set and client available)."""
    global _test_client

    if not LANGSMITH_API_KEY:
        # Allow test override even without API key
        if _test_client is not None:
            return True
        return False

    # Quick check without triggering client init
    if _test_client is not None:
        return True
    if _langsmith_client is not None:
        return True

    # Need to try loading
    return _get_langsmith_client() is not None


# =============================================================================
# Callback Handlers
# =============================================================================


async def _on_agent_run_start(
    agent_name: str,
    model_name: str,
    session_id: Optional[str] = None,
) -> None:
    """Start a new LangSmith trace for the agent run.

    Creates a root trace/run with the agent_name as the run name.
    Uses session_id as the trace correlation ID.
    """
    if not _is_plugin_active():
        return

    try:
        client = _get_langsmith_client()
        if client is None:
            return

        # Generate trace ID from session_id or create new UUID
        trace_id = session_id or str(uuid.uuid4())
        run_id = str(uuid.uuid4())

        # Create the run/trace
        run_kwargs: dict[str, Any] = {
            "name": agent_name,
            "run_type": "chain",  # LangSmith convention for agent runs
            "id": run_id,
            "session_id": trace_id,
            "project_name": LANGSMITH_PROJECT,
            "inputs": {"model": model_name},
            "start_time": time.time(),
        }

        # Start the trace - use the client's run creation API
        client.create_run(**run_kwargs)

        # Store trace context for this session
        _active_traces[trace_id] = {
            "run_id": run_id,
            "agent_name": agent_name,
            "model_name": model_name,
            "start_time": time.time(),
            "session_id": trace_id,
        }

        logger.debug(f"LangSmith trace started: {agent_name} (run_id={run_id}, session={trace_id})")

    except Exception as e:
        logger.debug(f"LangSmith trace start failed (non-critical): {e}")


async def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: Optional[str] = None,
    success: bool = True,
    error: Optional[Exception] = None,
    response_text: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Close the LangSmith trace for the agent run.

    Updates the run with outputs, end time, and error information.
    """
    if not LANGSMITH_API_KEY:  # Quick check without client init
        return

    trace_id = session_id
    if trace_id is None or trace_id not in _active_traces:
        # Try to find by agent name if session_id not provided
        for tid, ctx in _active_traces.items():
            if ctx["agent_name"] == agent_name:
                trace_id = tid
                break

    if trace_id is None or trace_id not in _active_traces:
        logger.debug(f"No active LangSmith trace found for agent: {agent_name}")
        return

    try:
        client = _get_langsmith_client()
        if client is None:
            return

        trace_ctx = _active_traces.pop(trace_id)
        run_id = trace_ctx["run_id"]
        end_time = time.time()

        # Build outputs and error info
        outputs: dict[str, Any] = {"success": success}
        if response_text is not None:
            # Truncate if too long
            outputs["response_preview"] = response_text[:1000] if len(response_text) > 1000 else response_text
        if metadata:
            outputs.update(metadata)

        error_info: Optional[str] = None
        if error is not None:
            error_info = str(error)
            outputs["error"] = error_info

        # Update the run
        update_kwargs: dict[str, Any] = {
            "run_id": run_id,
            "end_time": end_time,
            "outputs": outputs,
        }
        if error_info:
            update_kwargs["error"] = error_info

        client.update_run(**update_kwargs)

        logger.debug(f"LangSmith trace ended: {agent_name} (run_id={run_id}, success={success})")

    except Exception as e:
        logger.debug(f"LangSmith trace end failed (non-critical): {e}")


async def _on_pre_tool_call(
    tool_name: str,
    tool_args: dict,
    context: Any = None,
) -> None:
    """Create a child span for the tool call.

    Nests the tool call under the current agent run trace.
    """
    if not LANGSMITH_API_KEY:
        return

    try:
        client = _get_langsmith_client()
        if client is None:
            return

        # Find active trace - we need to correlate with current agent run
        # The session_id should be in the context or we use the most recent trace
        # For now, we'll use a simple approach: track by thread/context

        # Import run_context to get current trace info
        from code_puppy.run_context import get_current_run_context

        run_ctx = get_current_run_context()
        if run_ctx is None:
            logger.debug("No active run context for tool call tracing")
            return

        # Use run_id from context as correlation
        parent_run_id = run_ctx.run_id

        # Create child run for tool
        tool_run_id = str(uuid.uuid4())
        tool_run_kwargs: dict[str, Any] = {
            "name": tool_name,
            "run_type": "tool",
            "id": tool_run_id,
            "parent_run_id": parent_run_id,
            "project_name": LANGSMITH_PROJECT,
            "inputs": tool_args,
            "start_time": time.time(),
        }

        client.create_run(**tool_run_kwargs)

        # Store tool span info
        _tool_spans[parent_run_id] = {
            "tool_run_id": tool_run_id,
            "tool_name": tool_name,
            "start_time": time.time(),
        }

        logger.debug(f"LangSmith tool span started: {tool_name} (run_id={tool_run_id})")

    except Exception as e:
        logger.debug(f"LangSmith tool span start failed (non-critical): {e}")


async def _on_post_tool_call(
    tool_name: str,
    tool_args: dict,
    result: Any,
    duration_ms: float,
    context: Any = None,
) -> None:
    """Close the tool call child span.

    Updates the tool run with outputs and timing.
    """
    if not LANGSMITH_API_KEY:
        return

    try:
        client = _get_langsmith_client()
        if client is None:
            return

        # Find the parent run context
        from code_puppy.run_context import get_current_run_context

        run_ctx = get_current_run_context()
        if run_ctx is None:
            return

        parent_run_id = run_ctx.run_id

        # Get stored tool span info
        tool_ctx = _tool_spans.pop(parent_run_id, None)
        if tool_ctx is None:
            # Tool span wasn't created or already cleaned up
            return

        tool_run_id = tool_ctx["tool_run_id"]
        end_time = time.time()

        # Serialize result for outputs
        outputs: dict[str, Any] = {"duration_ms": duration_ms}
        try:
            if isinstance(result, (str, int, float, bool, list, dict)):
                outputs["result"] = result
            else:
                outputs["result"] = str(result)
        except Exception:
            outputs["result"] = "<unserializable result>"

        # Update the tool run
        client.update_run(
            run_id=tool_run_id,
            end_time=end_time,
            outputs=outputs,
        )

        logger.debug(f"LangSmith tool span ended: {tool_name} (run_id={tool_run_id})")

    except Exception as e:
        logger.debug(f"LangSmith tool span end failed (non-critical): {e}")


async def _on_stream_event(
    event_type: str,
    event_data: Any,
    agent_session_id: Optional[str] = None,
) -> None:
    """Log stream events to the active trace.

    Adds events to the current run for observability.
    """
    if not LANGSMITH_API_KEY:
        return

    try:
        client = _get_langsmith_client()
        if client is None:
            return

        # Find active trace by session_id
        trace_id = agent_session_id
        if trace_id is None or trace_id not in _active_traces:
            return

        trace_ctx = _active_traces.get(trace_id)
        if trace_ctx is None:
            return

        run_id = trace_ctx["run_id"]

        # Build event data
        event_name = f"stream:{event_type}"
        event_payload: dict[str, Any] = {
            "type": event_type,
            "timestamp": time.time(),
        }

        if isinstance(event_data, dict):
            # Include relevant event data (sanitized)
            safe_data = {k: v for k, v in event_data.items()
                        if k not in ("_run_id", "_component_name", "content", "delta")}
            if "delta" in event_data:
                event_payload["has_delta"] = True
            if "content" in event_data:
                content = event_data["content"]
                if isinstance(content, str):
                    event_payload["content_preview"] = content[:200] if len(content) > 200 else content
            event_payload.update(safe_data)

        # Post event to the run
        # Note: LangSmith API may vary - this is conceptual
        # Some versions use client.post_event or similar
        try:
            # Try to add as feedback/event if available
            if hasattr(client, "create_feedback"):
                client.create_feedback(
                    run_id=run_id,
                    key=event_name,
                    value=event_payload,
                )
        except Exception:
            # Events are best-effort, ignore failures
            pass

        logger.debug(f"LangSmith stream event logged: {event_type} for run {run_id}")

    except Exception as e:
        logger.debug(f"LangSmith stream event logging failed (non-critical): {e}")


# =============================================================================
# Plugin Registration
# =============================================================================

# Only register callbacks if LANGSMITH_API_KEY is set
# This ensures zero overhead when disabled
if LANGSMITH_API_KEY:
    logger.debug("LANGSMITH_API_KEY detected, registering LangSmith tracing callbacks")

    register_callback("agent_run_start", _on_agent_run_start)
    register_callback("agent_run_end", _on_agent_run_end)
    register_callback("pre_tool_call", _on_pre_tool_call)
    register_callback("post_tool_call", _on_post_tool_call)
    register_callback("stream_event", _on_stream_event)

    # Attempt early client initialization to catch config errors
    _ = _get_langsmith_client()
else:
    logger.debug("LANGSMITH_API_KEY not set, LangSmith tracing disabled (zero overhead)")
