"""OpenTelemetry tracing plugin for Code Puppy.

This plugin instruments agent runs, tool calls, and other operations
using OpenTelemetry. It uses the existing callback hooks and requires
no core code modifications.

Configuration:
    Set OTEL_ENABLED=true environment variable to enable.
    Requires opentelemetry-api to be installed (user provides SDK).

Example:
    OTEL_ENABLED=true code-puppy

The plugin is completely silent when disabled (zero overhead).
"""

from __future__ import annotations

import logging
from typing import Any

from code_puppy.callbacks import register_callback
from code_puppy.run_context import get_current_run_context

from . import tracing
from . import span_names

logger = logging.getLogger(__name__)

# Track active spans for correlating start/end events
# Key: run_id or session_id, Value: span object
_active_agent_spans: dict[str, Any] = {}
_active_tool_spans: dict[str, Any] = {}


# -----------------------------------------------------------------------------
# Agent Run Hooks
# -----------------------------------------------------------------------------


async def _on_agent_run_start(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
) -> None:
    """Handle agent run start - create OTel span.
    
    This creates a span for the agent run and stores it for later correlation
    with the agent_run_end event.
    """
    if not tracing.is_enabled():
        return
    
    # Get current RunContext for linking
    run_context = get_current_run_context()
    
    # Start span (using context manager would close it immediately in async)
    # So we start it manually and store for later
    tracer = tracing.get_tracer()
    if tracer is None:
        return
    
    try:
        # Build attributes
        attributes: dict[str, Any] = {
            span_names.ATTR_AGENT_NAME: agent_name,
            span_names.ATTR_MODEL_NAME: model_name,
        }
        
        if session_id is not None:
            attributes[span_names.ATTR_AGENT_SESSION_ID] = session_id
        
        # Link to RunContext
        if run_context is not None:
            attributes[span_names.ATTR_RUN_ID] = run_context.run_id
            attributes[span_names.ATTR_COMPONENT_TYPE] = run_context.component_type
            attributes[span_names.ATTR_COMPONENT_NAME] = run_context.component_name
            if run_context.parent_run_id:
                attributes[span_names.ATTR_PARENT_RUN_ID] = run_context.parent_run_id
            
            # Store by run_id for later lookup
            key = run_context.run_id
        else:
            # Fallback to session_id if no RunContext
            key = session_id or f"{agent_name}-{model_name}"
        
        # Start the span
        span = tracer.start_span(span_names.AGENT_RUN, attributes=attributes)
        
        # Store for later correlation
        _active_agent_spans[key] = span
        
        logger.debug(f"Started OTel span for agent run: {agent_name}/{model_name}")
        
    except Exception as e:
        # Never fail the agent run due to telemetry issues
        logger.debug(f"Failed to create agent run span: {e}")


async def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: Exception | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Handle agent run end - close OTel span.
    
    This retrieves the previously created span, updates it with final
    status and metadata, then ends it.
    """
    if not tracing.is_enabled():
        return
    
    # Find the span to close
    run_context = get_current_run_context()
    
    if run_context is not None:
        key = run_context.run_id
    else:
        key = session_id or f"{agent_name}-{model_name}"
    
    span = _active_agent_spans.pop(key, None)
    
    if span is None:
        logger.debug(f"No active span found for agent run end: {key}")
        return
    
    try:
        # Update with final data from RunContext
        if run_context is not None:
            tracing.update_span_from_run_context(span, run_context)
        
        # Update with metadata
        if metadata:
            # Add relevant metadata as attributes
            if "input_tokens" in metadata:
                tracing.set_span_attribute(span, "tokens.input", metadata["input_tokens"])
            if "output_tokens" in metadata:
                tracing.set_span_attribute(span, "tokens.output", metadata["output_tokens"])
            if "prompt_tokens" in metadata:
                tracing.set_span_attribute(span, "tokens.prompt", metadata["prompt_tokens"])
            if "completion_tokens" in metadata:
                tracing.set_span_attribute(span, "tokens.completion", metadata["completion_tokens"])
        
        # Set final status and end
        tracing.end_span(span, success=success, error=error)
        
        logger.debug(f"Ended OTel span for agent run: {agent_name}/{model_name} (success={success})")
        
    except Exception as e:
        # Ensure span is ended even if update fails
        try:
            tracing.end_span(span, success=False, error=e)
        except Exception:
            pass
        logger.debug(f"Error ending agent run span: {e}")


# -----------------------------------------------------------------------------
# Tool Call Hooks
# -----------------------------------------------------------------------------


async def _on_pre_tool_call(
    tool_name: str,
    tool_args: dict,
    context: Any = None,
) -> None:
    """Handle tool call start - create OTel span.
    
    Creates a span for the tool invocation, linked to the current
    RunContext if available.
    """
    if not tracing.is_enabled():
        return
    
    # Get current RunContext for linking
    run_context = get_current_run_context()
    
    tracer = tracing.get_tracer()
    if tracer is None:
        return
    
    try:
        # Build attributes
        attributes: dict[str, Any] = {
            span_names.ATTR_TOOL_NAME: tool_name,
        }
        
        # Record argument keys (not values - avoid leaking sensitive data)
        if tool_args:
            attributes[span_names.ATTR_TOOL_ARGS_KEYS] = list(tool_args.keys())
        
        # Link to RunContext
        if run_context is not None:
            attributes[span_names.ATTR_RUN_ID] = run_context.run_id
            attributes[span_names.ATTR_COMPONENT_TYPE] = run_context.component_type
            attributes[span_names.ATTR_COMPONENT_NAME] = run_context.component_name
            if run_context.parent_run_id:
                attributes[span_names.ATTR_PARENT_RUN_ID] = run_context.parent_run_id
            
            key = f"{run_context.run_id}:{tool_name}"
        else:
            key = tool_name
        
        # Start the span
        span = tracer.start_span(span_names.TOOL_CALL, attributes=attributes)
        
        # Store for later correlation
        _active_tool_spans[key] = span
        
        logger.debug(f"Started OTel span for tool call: {tool_name}")
        
    except Exception as e:
        logger.debug(f"Failed to create tool call span: {e}")


async def _on_post_tool_call(
    tool_name: str,
    tool_args: dict,
    result: Any,
    duration_ms: float,
    context: Any = None,
) -> None:
    """Handle tool call end - close OTel span.
    
    Retrieves the previously created tool span, records the duration,
    and ends it.
    """
    if not tracing.is_enabled():
        return
    
    # Find the span to close
    run_context = get_current_run_context()
    
    if run_context is not None:
        key = f"{run_context.run_id}:{tool_name}"
    else:
        key = tool_name
    
    span = _active_tool_spans.pop(key, None)
    
    if span is None:
        logger.debug(f"No active span found for tool call end: {key}")
        return
    
    try:
        # Record duration
        tracing.set_span_attribute(span, span_names.ATTR_DURATION_MS, duration_ms)
        
        # Record success based on result
        # If result contains an error indicator, mark as failed
        success = True
        if isinstance(result, dict):
            if result.get("error") or result.get("_error"):
                success = False
        elif isinstance(result, Exception):
            success = False
        
        # Set final status and end
        error = result if isinstance(result, Exception) else None
        tracing.end_span(span, success=success, error=error)
        
        logger.debug(f"Ended OTel span for tool call: {tool_name} (duration={duration_ms}ms)")
        
    except Exception as e:
        # Ensure span is ended even if update fails
        try:
            tracing.end_span(span, success=False, error=e)
        except Exception:
            pass
        logger.debug(f"Error ending tool call span: {e}")


# -----------------------------------------------------------------------------
# Stream Event Hook
# -----------------------------------------------------------------------------


async def _on_stream_event(
    event_type: str,
    event_data: Any,
    agent_session_id: str | None = None,
) -> None:
    """Handle stream events - record as span events.
    
    Records streaming events on the current span for detailed visibility
    into the agent's execution flow.
    """
    if not tracing.is_enabled():
        return
    
    try:
        # Get current span
        span = tracing.get_current_span()
        
        if span is None:
            # Fall back to finding an active agent span
            run_context = get_current_run_context()
            if run_context is not None:
                span = _active_agent_spans.get(run_context.run_id)
        
        if span is None:
            return
        
        # Prepare event data
        event_attrs: dict[str, Any] = {
            span_names.ATTR_EVENT_TYPE: event_type,
        }
        
        # Add event data if it's a dict
        if isinstance(event_data, dict):
            # Include run_id and component_name if present
            if "_run_id" in event_data:
                event_attrs["run_id"] = event_data["_run_id"]
            if "_component_name" in event_data:
                event_attrs["component_name"] = event_data["_component_name"]
        
        tracing.record_event(span, span_names.STREAM_EVENT, event_attrs)
        
        logger.debug(f"Recorded stream event: {event_type}")
        
    except Exception as e:
        logger.debug(f"Failed to record stream event: {e}")


# -----------------------------------------------------------------------------
# Startup Hook
# -----------------------------------------------------------------------------


async def _on_startup() -> None:
    """Handle startup - log telemetry status."""
    if tracing.is_enabled():
        logger.info("OpenTelemetry tracing enabled")
        tracer = tracing.get_tracer()
        if tracer is None:
            logger.warning("OTEL_ENABLED is set but opentelemetry-api is not installed")
        else:
            logger.info("OpenTelemetry tracer initialized successfully")
    else:
        logger.debug("OpenTelemetry tracing disabled (set OTEL_ENABLED=true to enable)")


# -----------------------------------------------------------------------------
# Register Callbacks
# -----------------------------------------------------------------------------

register_callback("startup", _on_startup)
register_callback("agent_run_start", _on_agent_run_start)
register_callback("agent_run_end", _on_agent_run_end)
register_callback("pre_tool_call", _on_pre_tool_call)
register_callback("post_tool_call", _on_post_tool_call)
register_callback("stream_event", _on_stream_event)

# Only log registration if tracing is enabled (keeps silent when disabled)
if tracing.is_enabled():
    logger.info("OpenTelemetry telemetry plugin callbacks registered")
else:
    logger.debug("OpenTelemetry telemetry plugin callbacks registered (disabled)")
