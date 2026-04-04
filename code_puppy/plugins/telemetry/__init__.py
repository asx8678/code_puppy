"""OpenTelemetry tracing plugin for Code Puppy.

This plugin provides distributed tracing for agent runs, tool calls,
and other operations using OpenTelemetry.

Configuration:
    Set OTEL_ENABLED=true environment variable to enable.
    Requires opentelemetry-api to be installed (user provides SDK).

Example:
    OTEL_ENABLED=true code-puppy

The plugin is completely silent when disabled (zero overhead).
"""

from . import span_names
from . import tracing

__all__ = ["span_names", "tracing"]
