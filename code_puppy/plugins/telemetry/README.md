# OpenTelemetry Tracing Plugin

Provides distributed tracing for Code Puppy agent runs, tool calls, and other operations using OpenTelemetry.

## Features

- **Agent run spans** - Full visibility into agent execution lifecycle
- **Tool call spans** - Track tool invocations and durations
- **Stream events** - Record streaming events on active spans
- **Zero overhead when disabled** - Completely silent when `OTEL_ENABLED` is not set
- **Graceful degradation** - Works without opentelemetry-api installed

## Configuration

Set the environment variable to enable:

```bash
export OTEL_ENABLED=true
code-puppy
```

## Requirements

The plugin uses `opentelemetry-api` only - you must provide the SDK and configure it:

```bash
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
```

Configure the SDK in your application code or via environment variables:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_SERVICE_NAME=code-puppy
```

## Instrumentation Details

### Spans Created

| Span Name | Hook | Attributes |
|-----------|------|------------|
| `agent.run` | `agent_run_start` | `agent.name`, `model.name`, `agent.session_id`, `run.id` |
| `tool.call` | `pre_tool_call` | `tool.name`, `tool.argsKeys`, `run.id` |
| `stream.event` | `stream_event` | Recorded as span event |

### Span Attributes

- `agent.name` - Name of the executing agent
- `model.name` - Name of the model being used
- `agent.session_id` - Session identifier
- `run.id` - Unique run identifier from RunContext
- `run.parent_id` - Parent run identifier for hierarchical tracing
- `component.type` - Component type (agent, tool, etc.)
- `component.name` - Component name
- `tool.name` - Tool being called
- `tool.argsKeys` - Keys of tool arguments (values not recorded for privacy)
- `duration_ms` - Operation duration in milliseconds
- `success` - Whether operation succeeded
- `error.type` - Type of error if failed
- `tokens.input` / `tokens.output` - Token counts from metadata

## Architecture

The plugin uses the existing callback system:
- `agent_run_start` / `agent_run_end` - Agent run spans
- `pre_tool_call` / `post_tool_call` - Tool call spans
- `stream_event` - Stream event recording
- `startup` - Initialization logging

All spans are linked to `RunContext` for hierarchical tracing.

## Privacy Notes

- Tool argument **values** are never recorded (only keys)
- Response text is not included in spans
- Only metadata (tokens, timing, success/failure) is captured
