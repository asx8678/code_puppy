"""OpenTelemetry tracing implementation for Code Puppy.

This module provides span creation and management using the OpenTelemetry API.
It gracefully degrades if opentelemetry-api is not installed.

Design principles:
- Use opentelemetry-api (not SDK) - user provides the SDK
- Zero overhead when disabled (OTEL_ENABLED env var check)
- Context managers for span lifecycle
- Integration with RunContext for hierarchical tracing
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Generator

# Check if telemetry is enabled via environment variable
OTEL_ENABLED = os.environ.get("OTEL_ENABLED", "").lower() in ("true", "1", "yes", "on")

# Try to import OpenTelemetry - gracefully degrade if not available
try:
    from opentelemetry import trace
    from opentelemetry.trace import Span, SpanContext, Tracer, Status, StatusCode
    from opentelemetry.context import Context

    _otel_available = True
except ImportError:
    _otel_available = False
    trace = None
    Span = None
    SpanContext = None
    Tracer = None
    Status = None
    StatusCode = None
    Context = None

# Cache for the tracer instance
_tracer: Tracer | None = None


def is_enabled() -> bool:
    """Check if telemetry is enabled and available.
    
    Returns:
        True if OTEL_ENABLED is set and opentelemetry-api is installed.
    """
    return OTEL_ENABLED and _otel_available


def get_tracer() -> Tracer | None:
    """Get the OpenTelemetry tracer instance.
    
    Returns:
        Tracer instance if available, None otherwise.
    """
    global _tracer
    
    if not is_enabled():
        return None
    
    if _tracer is None and trace is not None:
        _tracer = trace.get_tracer("code_puppy", "1.0.0")
    
    return _tracer


def get_current_span() -> Span | None:
    """Get the current span from OpenTelemetry context.
    
    Returns:
        Current span if available, None otherwise.
    """
    if not is_enabled() or trace is None:
        return None
    
    return trace.get_current_span()


def set_span_attribute(span: Span | None, key: str, value: Any) -> None:
    """Safely set an attribute on a span.
    
    Args:
        span: The span to set attribute on (can be None)
        key: Attribute key
        value: Attribute value
    """
    if span is not None and hasattr(span, "set_attribute"):
        # Handle None values - OTel doesn't accept None
        if value is None:
            return
        
        # Convert non-primitive types to string
        if not isinstance(value, (str, int, float, bool)):
            value = str(value)
        
        try:
            span.set_attribute(key, value)
        except Exception:
            # Silently ignore attribute errors
            pass


def set_span_status(
    span: Span | None,
    success: bool,
    error: Exception | None = None,
) -> None:
    """Set span status based on success/failure.
    
    Args:
        span: The span to set status on
        success: Whether the operation succeeded
        error: Optional exception if operation failed
    """
    if span is None or not hasattr(span, "set_status"):
        return
    
    try:
        if success:
            span.set_status(Status(StatusCode.OK))
        else:
            if error is not None:
                span.set_status(
                    Status(StatusCode.ERROR, description=str(error))
                )
            else:
                span.set_status(Status(StatusCode.ERROR))
    except Exception:
        # Silently ignore status errors
        pass


def end_span(span: Span | None, success: bool = True, error: Exception | None = None) -> None:
    """End a span with appropriate status.
    
    Args:
        span: The span to end
        success: Whether the operation succeeded
        error: Optional exception if operation failed
    """
    if span is None or not hasattr(span, "end"):
        return
    
    try:
        set_span_status(span, success, error)
        span.end()
    except Exception:
        # Silently ignore end errors
        pass


@contextmanager
def start_span(
    name: str,
    kind: Any = None,
    attributes: dict[str, Any] | None = None,
    parent_span: Span | None = None,
) -> Generator[Span | None, None, None]:
    """Context manager for starting and ending a span.
    
    This is the primary API for creating spans. It handles:
    - Checking if telemetry is enabled
    - Creating the span with proper parent context
    - Setting initial attributes
    - Ending the span on exit with proper status
    
    Args:
        name: Span name
        kind: Optional span kind (defaults to INTERNAL)
        attributes: Optional initial attributes
        parent_span: Optional parent span for explicit parenting
    
    Yields:
        The created span or None if telemetry is disabled
    
    Example:
        with start_span("my.operation", attributes={"key": "value"}) as span:
            do_work()
            # Span automatically ends when context exits
    """
    tracer = get_tracer()
    
    if tracer is None:
        # Telemetry disabled - yield None and skip
        yield None
        return
    
    # Determine span kind
    if kind is None and hasattr(trace, "SpanKind"):
        kind = trace.SpanKind.INTERNAL
    
    # Build context with explicit parent if provided
    ctx = None
    if parent_span is not None and Context is not None:
        from opentelemetry.trace import set_span_in_context
        ctx = set_span_in_context(parent_span)
    
    span = None
    try:
        # Start the span
        if ctx is not None:
            span = tracer.start_span(name, kind=kind, context=ctx)
        else:
            span = tracer.start_span(name, kind=kind)
        
        # Set initial attributes
        if attributes:
            for key, value in attributes.items():
                set_span_attribute(span, key, value)
        
        # Make this span current in context
        if hasattr(trace, "use_span"):
            with trace.use_span(span, end_on_exit=False):
                yield span
        else:
            yield span
        
        # Normal exit - mark as success
        end_span(span, success=True)
        
    except Exception as e:
        # Exception exit - mark as error and re-raise
        end_span(span, success=False, error=e)
        raise


@contextmanager
def start_agent_run_span(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    run_context: Any = None,
) -> Generator[Span | None, None, None]:
    """Start a span for an agent run.
    
    Args:
        agent_name: Name of the agent
        model_name: Name of the model being used
        session_id: Optional session identifier
        run_context: Optional RunContext for linking
    
    Yields:
        The created span or None
    """
    from . import span_names
    
    attributes: dict[str, Any] = {
        span_names.ATTR_AGENT_NAME: agent_name,
        span_names.ATTR_MODEL_NAME: model_name,
    }
    
    if session_id is not None:
        attributes[span_names.ATTR_AGENT_SESSION_ID] = session_id
    
    # Link to RunContext if available
    if run_context is not None:
        attributes[span_names.ATTR_RUN_ID] = getattr(run_context, "run_id", None)
        attributes[span_names.ATTR_COMPONENT_TYPE] = getattr(run_context, "component_type", None)
        attributes[span_names.ATTR_COMPONENT_NAME] = getattr(run_context, "component_name", None)
        parent_run_id = getattr(run_context, "parent_run_id", None)
        if parent_run_id:
            attributes[span_names.ATTR_PARENT_RUN_ID] = parent_run_id
    
    with start_span(span_names.AGENT_RUN, attributes=attributes) as span:
        yield span


@contextmanager
def start_tool_call_span(
    tool_name: str,
    tool_args: dict | None = None,
    run_context: Any = None,
) -> Generator[Span | None, None, None]:
    """Start a span for a tool call.
    
    Args:
        tool_name: Name of the tool being called
        tool_args: Optional tool arguments
        run_context: Optional RunContext for linking
    
    Yields:
        The created span or None
    """
    from . import span_names
    
    attributes: dict[str, Any] = {
        span_names.ATTR_TOOL_NAME: tool_name,
    }
    
    # Record argument keys (not values - avoid leaking sensitive data)
    if tool_args is not None:
        keys = list(tool_args.keys())
        attributes[span_names.ATTR_TOOL_ARGS_KEYS] = keys
    
    # Link to RunContext if available
    if run_context is not None:
        attributes[span_names.ATTR_RUN_ID] = getattr(run_context, "run_id", None)
        attributes[span_names.ATTR_COMPONENT_TYPE] = getattr(run_context, "component_type", None)
        attributes[span_names.ATTR_COMPONENT_NAME] = getattr(run_context, "component_name", None)
        parent_run_id = getattr(run_context, "parent_run_id", None)
        if parent_run_id:
            attributes[span_names.ATTR_PARENT_RUN_ID] = parent_run_id
    
    with start_span(span_names.TOOL_CALL, attributes=attributes) as span:
        yield span


def record_event(
    span: Span | None,
    event_type: str,
    event_data: dict[str, Any] | None = None,
) -> None:
    """Record an event on a span.
    
    Args:
        span: The span to record event on
        event_type: Type of event
        event_data: Optional event attributes
    """
    if span is None or not hasattr(span, "add_event"):
        return
    
    try:
        if event_data:
            # Sanitize event data - convert non-primitives to strings
            sanitized: dict[str, Any] = {}
            for key, value in event_data.items():
                if value is None:
                    continue
                if not isinstance(value, (str, int, float, bool)):
                    sanitized[key] = str(value)
                else:
                    sanitized[key] = value
            span.add_event(event_type, sanitized)
        else:
            span.add_event(event_type)
    except Exception:
        # Silently ignore event errors
        pass


def update_span_from_run_context(span: Span | None, run_context: Any) -> None:
    """Update span attributes from a RunContext.
    
    This is useful when the RunContext is updated after the span starts
    (e.g., with results, errors, or timing info).
    
    Args:
        span: The span to update
        run_context: RunContext with updated data
    """
    from . import span_names
    
    if span is None or run_context is None:
        return
    
    # Update duration if available
    duration_ms = getattr(run_context, "duration_ms", None)
    if duration_ms is not None:
        set_span_attribute(span, span_names.ATTR_DURATION_MS, duration_ms)
    
    # Update success status if available
    success = getattr(run_context, "success", None)
    if success is not None:
        set_span_attribute(span, span_names.ATTR_SUCCESS, success)
    
    # Update error info if available
    error_type = getattr(run_context, "error_type", None)
    if error_type is not None:
        set_span_attribute(span, span_names.ATTR_ERROR_TYPE, error_type)
