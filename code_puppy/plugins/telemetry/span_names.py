"""Span name constants for OpenTelemetry tracing.

This module provides centralized span naming conventions for the
telemetry plugin to ensure consistency across all traces.
"""

# Agent-related spans
AGENT_RUN = "agent.run"
AGENT_RUN_END = "agent.run.end"

# Tool-related spans
TOOL_CALL = "tool.call"
TOOL_CALL_END = "tool.call.end"

# Context-related spans
CONTEXT_PACK = "context.pack"
CONTEXT_UNPACK = "context.unpack"

# Session-related spans
SESSION_SAVE = "session.save"
SESSION_LOAD = "session.load"

# Stream-related spans
STREAM_EVENT = "stream.event"

# Attribute keys for span metadata
ATTR_AGENT_NAME = "agent.name"
ATTR_AGENT_SESSION_ID = "agent.session_id"
ATTR_MODEL_NAME = "model.name"
ATTR_TOOL_NAME = "tool.name"
ATTR_TOOL_ARGS_KEYS = "tool.args_keys"
ATTR_DURATION_MS = "duration_ms"
ATTR_SUCCESS = "success"
ATTR_ERROR_TYPE = "error.type"
ATTR_ERROR_MESSAGE = "error.message"
ATTR_RUN_ID = "run.id"
ATTR_PARENT_RUN_ID = "run.parent_id"
ATTR_COMPONENT_TYPE = "component.type"
ATTR_COMPONENT_NAME = "component.name"
ATTR_EVENT_TYPE = "event.type"
ATTR_CONTEXT_SIZE = "context.size_bytes"
ATTR_SESSION_ID = "session.id"
