"""LangFuse tracing plugin – observability for agent runs and tool calls.

Auto-enables when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY environment
variables are present. Provides distributed tracing with span nesting
(agent runs as parent traces, tool calls as child spans).

Environment Variables:
    LANGFUSE_PUBLIC_KEY: Required to enable the plugin
    LANGFUSE_SECRET_KEY: Required to enable the plugin
    LANGFUSE_HOST: Optional custom API endpoint (defaults to https://cloud.langfuse.com)
    LANGFUSE_PROJECT: Optional project name
"""

import logging
import os
import time
import uuid
from typing import Any

from code_puppy.async_utils import warn_once
from code_puppy.callbacks import register_callback
from code_puppy.reflection import resolve_variable

logger = logging.getLogger(__name__)

# =============================================================================
# Feature Detection & Auto-Enable Logic
# =============================================================================

# Read environment variables at module load time
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY")
LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
LANGFUSE_PROJECT = os.environ.get("LANGFUSE_PROJECT")

# Module-level state for the LangFuse client and active traces
_langfuse_client: Any = None
_active_traces: dict[str, Any] = {}  # session_id -> trace context
_tool_spans: dict[str, Any] = {}  # parent_run_id -> current tool span
_warned_missing = False
_test_client: Any = None  # For test injection


def _reset_state():
    """Reset module state - useful for testing."""
    global _langfuse_client, _active_traces, _tool_spans, _warned_missing, _test_client
    _langfuse_client = None
    _active_traces = {}
    _tool_spans = {}
    _warned_missing = False
    _test_client = None


def _set_test_client(client: Any | None) -> None:
    """Set a mock client for testing. Pass None to clear."""
    global _test_client
    _test_client = client


def _get_langfuse_client() -> Any | None:
    """Lazy-load the LangFuse client using resolve_variable.

    Returns None if langfuse package is not installed.
    Uses warn_once to hint at installation on first failure.
    """
    global _langfuse_client, _warned_missing, _test_client

    # Test override - use injected mock if available
    if _test_client is not None:
        return _test_client

    if _langfuse_client is not None:
        return _langfuse_client

    # Only try to load if both keys are set
    if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:
        return None

    try:
        # Use reflection to gracefully handle missing langfuse package
        Langfuse = resolve_variable("langfuse:Langfuse")

        # Build client kwargs
        client_kwargs: dict[str, Any] = {
            "public_key": LANGFUSE_PUBLIC_KEY,
            "secret_key": LANGFUSE_SECRET_KEY,
            "host": LANGFUSE_HOST,
        }

        _langfuse_client = Langfuse(**client_kwargs)
        logger.debug("LangFuse client initialized successfully")
        return _langfuse_client

    except ImportError:
        if not _warned_missing:
            warn_once(
                "langfuse_missing",
                "LangFuse tracing enabled (LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY set) "
                "but 'langfuse' package not installed. "
                "Install with: pip install langfuse",
                logger,
            )
            _warned_missing = True
        return None
    except Exception as e:
        logger.warning(f"Failed to initialize LangFuse client: {e}")
        return None


def _is_plugin_active() -> bool:
    """Check if plugin should be active (env vars set and client available)."""
    global _test_client

    if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:
        # Allow test override even without env vars
        if _test_client is not None:
            return True
        return False

    # Quick check without triggering client init
    if _test_client is not None:
        return True
    if _langfuse_client is not None:
        return True

    # Need to try loading
    return _get_langfuse_client() is not None


# =============================================================================
# Callback Handlers
# =============================================================================


async def _on_agent_run_start(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
) -> None:
    """Start a new LangFuse trace for the agent run.

    Creates a root trace with the agent_name as the trace name.
    Uses session_id as the trace correlation ID.
    """
    if not _is_plugin_active():
        return

    try:
        client = _get_langfuse_client()
        if client is None:
            return

        # Generate trace ID from session_id or create new UUID
        trace_id = session_id or str(uuid.uuid4())

        # Create the trace using LangFuse API
        # LangFuse uses trace() method to create traces
        trace = client.trace(
            id=trace_id,
            name=agent_name,
            metadata={"model": model_name},
            session_id=trace_id,
        )

        # Store trace context for this session
        _active_traces[trace_id] = {
            "trace": trace,
            "agent_name": agent_name,
            "model_name": model_name,
            "start_time": time.time(),
            "session_id": trace_id,
            "generation": None,  # Will hold the generation object
        }

        # Create a generation for the LLM call within this trace
        generation = trace.generation(
            name=f"{agent_name}-generation",
            model=model_name,
            start_time=time.time(),
        )
        _active_traces[trace_id]["generation"] = generation

        logger.debug(f"LangFuse trace started: {agent_name} (trace_id={trace_id})")

    except Exception as e:
        logger.debug(f"LangFuse trace start failed (non-critical): {e}")


async def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: Exception | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
    **kwargs,
) -> None:
    """Close the LangFuse trace for the agent run.

    Updates the trace with outputs, end time, and error information.
    Flushes the LangFuse client to ensure data is sent.
    """
    if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:  # Quick check without client init
        return

    trace_id = session_id
    if trace_id is None or trace_id not in _active_traces:
        # Try to find by agent name if session_id not provided
        for tid, ctx in _active_traces.items():
            if ctx["agent_name"] == agent_name:
                trace_id = tid
                break

    if trace_id is None or trace_id not in _active_traces:
        logger.debug(f"No active LangFuse trace found for agent: {agent_name}")
        return

    try:
        client = _get_langfuse_client()
        if client is None:
            return

        trace_ctx = _active_traces.pop(trace_id)
        trace = trace_ctx["trace"]
        generation = trace_ctx.get("generation")

        # End the generation if it exists
        if generation is not None:
            try:
                gen_outputs: dict[str, Any] = {"success": success}
                if response_text is not None:
                    # Truncate if too long
                    gen_outputs["response_preview"] = (
                        response_text[:1000] if len(response_text) > 1000 else response_text
                    )
                if metadata:
                    gen_outputs.update(metadata)

                generation.end(
                    output=gen_outputs,
                    end_time=time.time(),
                    status="success" if success else "error",
                )
            except Exception:
                pass  # Best effort

        # Update the trace with final status
        trace_outputs: dict[str, Any] = {"success": success}
        if response_text is not None:
            trace_outputs["response_preview"] = (
                response_text[:1000] if len(response_text) > 1000 else response_text
            )
        if metadata:
            trace_outputs.update(metadata)

        # Mark trace as complete
        trace.update(output=trace_outputs)

        # Flush to ensure data is sent to LangFuse
        try:
            client.flush()
        except Exception:
            pass  # Best effort on flush

        logger.debug(f"LangFuse trace ended: {agent_name} (trace_id={trace_id}, success={success})")

    except Exception as e:
        logger.debug(f"LangFuse trace end failed (non-critical): {e}")


async def _on_pre_tool_call(
    tool_name: str,
    tool_args: dict,
    context: Any = None,
) -> None:
    """Create a child span for the tool call.

    Nests the tool call under the current agent run trace.
    """
    if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:
        return

    try:
        client = _get_langfuse_client()
        if client is None:
            return

        # Find active trace - we need to correlate with current agent run
        from code_puppy.run_context import get_current_run_context

        run_ctx = get_current_run_context()
        if run_ctx is None:
            logger.debug("No active run context for tool call tracing")
            return

        # Use session_id from context as correlation
        session_id = run_ctx.session_id
        if session_id is None or session_id not in _active_traces:
            logger.debug(f"No active LangFuse trace found for session: {session_id}")
            return

        trace_ctx = _active_traces[session_id]
        trace = trace_ctx["trace"]

        # Create span for tool call using LangFuse API
        span = trace.span(
            name=tool_name,
            input=tool_args,
            start_time=time.time(),
        )

        # Store tool span info, keyed by parent run_id for correlation
        parent_run_id = run_ctx.run_id
        _tool_spans[parent_run_id] = {
            "span": span,
            "tool_name": tool_name,
            "start_time": time.time(),
        }

        logger.debug(f"LangFuse tool span started: {tool_name}")

    except Exception as e:
        logger.debug(f"LangFuse tool span start failed (non-critical): {e}")


async def _on_post_tool_call(
    tool_name: str,
    tool_args: dict,
    result: Any,
    duration_ms: float,
    context: Any = None,
) -> None:
    """Close the tool call child span.

    Updates the tool span with outputs and timing.
    """
    if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:
        return

    try:
        client = _get_langfuse_client()
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

        span = tool_ctx["span"]

        # Serialize result for outputs
        try:
            if isinstance(result, (str, int, float, bool, list, dict)):
                output = result
            else:
                output = str(result)
        except Exception:
            output = "<unserializable result>"

        # End the span
        span.end(
            output=output,
            end_time=time.time(),
            metadata={"duration_ms": duration_ms},
        )

        logger.debug(f"LangFuse tool span ended: {tool_name}")

    except Exception as e:
        logger.debug(f"LangFuse tool span end failed (non-critical): {e}")


async def _on_stream_event(
    event_type: str,
    event_data: Any,
    agent_session_id: str | None = None,
) -> None:
    """Log stream events to the active trace.

    Adds events to the current trace for observability.
    """
    if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:
        return

    try:
        client = _get_langfuse_client()
        if client is None:
            return

        # Find active trace by session_id
        trace_id = agent_session_id
        if trace_id is None or trace_id not in _active_traces:
            return

        trace_ctx = _active_traces.get(trace_id)
        if trace_ctx is None:
            return

        trace = trace_ctx["trace"]

        # Build event data
        event_payload: dict[str, Any] = {
            "type": event_type,
            "timestamp": time.time(),
        }

        if isinstance(event_data, dict):
            # Include relevant event data (sanitized)
            safe_data = {k: v for k, v in event_data.items() if k not in ("_run_id", "_component_name")}
            if "delta" in event_data:
                event_payload["has_delta"] = True
            if "content" in event_data:
                content = event_data["content"]
                if isinstance(content, str):
                    event_payload["content_preview"] = content[:200] if len(content) > 200 else content
            event_payload.update(safe_data)

        # Add as an event to the trace
        try:
            trace.event(
                name=f"stream:{event_type}",
                metadata=event_payload,
            )
        except Exception:
            # Events are best-effort, ignore failures
            pass

        logger.debug(f"LangFuse stream event logged: {event_type} for trace {trace_id}")

    except Exception as e:
        logger.debug(f"LangFuse stream event logging failed (non-critical): {e}")


# =============================================================================
# Plugin Registration
# =============================================================================

# Only register callbacks if both LANGFUSE keys are set
# This ensures zero overhead when disabled
if LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY:
    logger.debug("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY detected, registering LangFuse tracing callbacks")

    register_callback("agent_run_start", _on_agent_run_start)
    register_callback("agent_run_end", _on_agent_run_end)
    register_callback("pre_tool_call", _on_pre_tool_call)
    register_callback("post_tool_call", _on_post_tool_call)
    register_callback("stream_event", _on_stream_event)

    # Attempt early client initialization to catch config errors
    _ = _get_langfuse_client()
else:
    logger.debug(
        "LANGFUSE_PUBLIC_KEY and/or LANGFUSE_SECRET_KEY not set, "
        "LangFuse tracing disabled (zero overhead)"
    )
