"""Agent Trace V2 — Callback Registration.

Hooks into code_puppy's callback system to emit normalized trace events.
Key V2 improvements:
- Model calls are explicit spans (separate from agent runs)
- Token counts have accounting state (estimated vs exact)
- Reconciliation events correct live estimates
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from code_puppy.callbacks import register_callback
from code_puppy.messaging import emit_info
from code_puppy.plugins.agent_trace.schema import (
    NodeKind,
    TransferKind,
    TokenClass,
    AccountingState,
)
from code_puppy.plugins.agent_trace.emitter import (
    emit_span_started,
    emit_span_ended,
    emit_transfer,
    emit_usage_reconciled,
)
from code_puppy.plugins.agent_trace.store import TraceStore
from code_puppy.plugins.agent_trace.reducer import TraceState, reduce_event

logger = logging.getLogger(__name__)

# Module-level state
_store = TraceStore()
_trace_states: dict[str, TraceState] = {}

# Map session_id -> (trace_id, span_id, node_id) for correlation
_session_spans: dict[str, tuple[str, str, str]] = {}

# Track model call spans within agent runs
_agent_model_spans: dict[str, tuple[str, str]] = {}  # span_id -> (model_span_id, model_node_id)

# Estimated token counts for reconciliation
_estimated_usage: dict[str, dict[str, int]] = {}  # span_id -> {input, output}


def _get_or_create_trace_id(session_id: str | None) -> str:
    """Get existing trace_id for session or create new one."""
    if session_id and session_id in _session_spans:
        return _session_spans[session_id][0]
    return f"trace-{uuid.uuid4().hex[:12]}"


def _on_startup():
    """Initialize the trace system."""
    emit_info("📊 Agent Trace V2 loaded (normalized observability)")


async def _on_agent_run_start(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    **kwargs,
) -> None:
    """Handle agent run start — create agent_run span and model_call span."""
    try:
        trace_id = _get_or_create_trace_id(session_id)
        
        # Determine parent span if this is a child agent
        parent_span_id = None
        parent_node_id = None
        if session_id:
            # Check if there's a parent session
            parent_session = kwargs.get("parent_session_id")
            if parent_session and parent_session in _session_spans:
                _, parent_span_id, parent_node_id = _session_spans[parent_session]
        
        # Create agent_run span
        agent_event = emit_span_started(
            trace_id=trace_id,
            kind=NodeKind.AGENT_RUN,
            name=agent_name,
            parent_span_id=parent_span_id,
            session_id=session_id,
            parent_node_id=parent_node_id,
            extra={"model": model_name},
        )
        
        # Store the mapping
        if session_id and agent_event.span_id and agent_event.node:
            _session_spans[session_id] = (trace_id, agent_event.span_id, agent_event.node.id)
        
        # Create model_call span as child (V2: explicit model node!)
        model_event = emit_span_started(
            trace_id=trace_id,
            kind=NodeKind.MODEL_CALL,
            name=model_name,
            parent_span_id=agent_event.span_id,
            session_id=session_id,
            parent_node_id=agent_event.node.id if agent_event.node else None,
        )
        
        # Track model span for later
        if agent_event.span_id and model_event.span_id and model_event.node:
            _agent_model_spans[agent_event.span_id] = (model_event.span_id, model_event.node.id)
        
        # Initialize trace state
        if trace_id not in _trace_states:
            _trace_states[trace_id] = TraceState(trace_id=trace_id)
        
        # Reduce events into state
        _trace_states[trace_id] = reduce_event(_trace_states[trace_id], agent_event)
        _trace_states[trace_id] = reduce_event(_trace_states[trace_id], model_event)
        
        # Persist events
        _store.append(agent_event)
        _store.append(model_event)
        
    except Exception as e:
        logger.debug(f"Agent trace error in agent_run_start: {e}")


async def _on_stream_event(
    event_type: str,
    event_data: Any,
    agent_session_id: str | None = None,
    **kwargs,
) -> None:
    """Handle stream events — emit transfer events with estimated tokens."""
    try:
        if agent_session_id not in _session_spans:
            return
        
        trace_id, agent_span_id, agent_node_id = _session_spans[agent_session_id]
        
        # Get model span if available
        model_span_id, model_node_id = _agent_model_spans.get(agent_span_id, (None, None))
        source_node = model_node_id or agent_node_id
        
        # Estimate tokens from stream chunk
        token_count = None
        if isinstance(event_data, dict):
            # Try to extract content for token estimation
            content = event_data.get("content") or event_data.get("text") or ""
            if content:
                # Rough estimate: ~4 chars per token
                token_count = max(1, len(content) // 4)
        
        if token_count:
            transfer_event = emit_transfer(
                trace_id=trace_id,
                kind=TransferKind.MODEL_OUTPUT,
                source_node_id=source_node,
                target_node_id=agent_node_id,
                token_count=token_count,
                token_class=TokenClass.OUTPUT_TOKENS,
                accounting=AccountingState.ESTIMATED_LIVE,
                span_id=model_span_id or agent_span_id,
                session_id=agent_session_id,
            )
            
            # Track estimated usage for reconciliation
            span_key = model_span_id or agent_span_id
            if span_key:
                if span_key not in _estimated_usage:
                    _estimated_usage[span_key] = {"input": 0, "output": 0}
                _estimated_usage[span_key]["output"] += token_count
            
            # Reduce and persist
            _trace_states[trace_id] = reduce_event(_trace_states[trace_id], transfer_event)
            _store.append(transfer_event)
        
    except Exception as e:
        logger.debug(f"Agent trace error in stream_event: {e}")


async def _on_pre_tool_call(
    tool_name: str,
    tool_args: dict[str, Any],
    context: Any = None,
    **kwargs,
) -> None:
    """Handle tool call start — create tool_call span."""
    try:
        # Get session from context
        session_id = getattr(context, "session_id", None) if context else None
        if not session_id or session_id not in _session_spans:
            return
        
        trace_id, agent_span_id, agent_node_id = _session_spans[session_id]
        model_span_id, model_node_id = _agent_model_spans.get(agent_span_id, (None, None))
        
        # Create tool_call span
        tool_event = emit_span_started(
            trace_id=trace_id,
            kind=NodeKind.TOOL_CALL,
            name=tool_name,
            parent_span_id=model_span_id or agent_span_id,
            session_id=session_id,
            parent_node_id=model_node_id or agent_node_id,
        )
        
        # Emit tool_args transfer
        args_str = str(tool_args)[:500]  # Truncate for storage
        args_event = emit_transfer(
            trace_id=trace_id,
            kind=TransferKind.TOOL_ARGS,
            source_node_id=model_node_id or agent_node_id,
            target_node_id=tool_event.node.id if tool_event.node else None,
            token_count=len(args_str) // 4,  # Rough estimate
            token_class=TokenClass.INPUT_TOKENS,
            accounting=AccountingState.ESTIMATED_LIVE,
            preview=args_str[:200],
            span_id=tool_event.span_id,
            session_id=session_id,
        )
        
        # Reduce and persist
        _trace_states[trace_id] = reduce_event(_trace_states[trace_id], tool_event)
        _trace_states[trace_id] = reduce_event(_trace_states[trace_id], args_event)
        _store.append(tool_event)
        _store.append(args_event)
        
    except Exception as e:
        logger.debug(f"Agent trace error in pre_tool_call: {e}")


async def _on_post_tool_call(
    tool_name: str,
    tool_args: dict[str, Any],
    result: Any,
    duration_ms: float,
    context: Any = None,
    **kwargs,
) -> None:
    """Handle tool call end — emit tool_result and close span."""
    try:
        session_id = getattr(context, "session_id", None) if context else None
        if not session_id or session_id not in _session_spans:
            return
        
        trace_id, agent_span_id, agent_node_id = _session_spans[session_id]
        
        # Find the tool span (last TOOL_CALL span for this session)
        state = _trace_states.get(trace_id)
        if not state:
            return
        
        tool_span = None
        for span in reversed(list(state.spans.values())):
            if span.kind == NodeKind.TOOL_CALL and span.name == tool_name and span.status == "running":
                tool_span = span
                break
        
        if not tool_span:
            return
        
        # Emit tool_result transfer
        result_str = str(result)[:500]
        result_event = emit_transfer(
            trace_id=trace_id,
            kind=TransferKind.TOOL_RESULT,
            source_node_id=tool_span.node_id,
            target_node_id=agent_node_id,
            token_count=len(result_str) // 4,
            token_class=TokenClass.INPUT_TOKENS,  # Tool results become model input
            accounting=AccountingState.ESTIMATED_LIVE,
            preview=result_str[:200],
            span_id=tool_span.span_id,
            session_id=session_id,
        )
        
        # End tool span
        end_event = emit_span_ended(
            trace_id=trace_id,
            span_id=tool_span.span_id,
            node_id=tool_span.node_id,
            kind=NodeKind.TOOL_CALL,
            name=tool_name,
            success=True,
            duration_ms=duration_ms,
            session_id=session_id,
        )
        
        # Reduce and persist
        _trace_states[trace_id] = reduce_event(_trace_states[trace_id], result_event)
        _trace_states[trace_id] = reduce_event(_trace_states[trace_id], end_event)
        _store.append(result_event)
        _store.append(end_event)
        
    except Exception as e:
        logger.debug(f"Agent trace error in post_tool_call: {e}")


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
    """Handle agent run end — close spans and emit reconciliation."""
    try:
        if not session_id or session_id not in _session_spans:
            return
        
        trace_id, agent_span_id, agent_node_id = _session_spans[session_id]
        model_span_id, model_node_id = _agent_model_spans.get(agent_span_id, (None, None))
        
        # Extract exact usage from metadata if available
        exact_usage = None
        if metadata:
            exact_usage = metadata.get("usage") or metadata.get("token_usage")
        
        # End model span first
        if model_span_id and model_node_id:
            # Check if we have exact usage to emit reconciliation
            if exact_usage and model_span_id in _estimated_usage:
                estimated = _estimated_usage[model_span_id]
                recon_event = emit_usage_reconciled(
                    trace_id=trace_id,
                    span_id=model_span_id,
                    node_id=model_node_id,
                    estimated_input=estimated.get("input"),
                    estimated_output=estimated.get("output"),
                    exact_input=exact_usage.get("input_tokens") or exact_usage.get("prompt_tokens"),
                    exact_output=exact_usage.get("output_tokens") or exact_usage.get("completion_tokens"),
                    exact_reasoning=exact_usage.get("reasoning_tokens"),
                    exact_cached=exact_usage.get("cached_tokens"),
                    session_id=session_id,
                )
                _trace_states[trace_id] = reduce_event(_trace_states[trace_id], recon_event)
                _store.append(recon_event)
            
            model_end = emit_span_ended(
                trace_id=trace_id,
                span_id=model_span_id,
                node_id=model_node_id,
                kind=NodeKind.MODEL_CALL,
                name=model_name,
                success=success,
                error=str(error) if error else None,
                session_id=session_id,
            )
            _trace_states[trace_id] = reduce_event(_trace_states[trace_id], model_end)
            _store.append(model_end)
        
        # End agent span
        agent_end = emit_span_ended(
            trace_id=trace_id,
            span_id=agent_span_id,
            node_id=agent_node_id,
            kind=NodeKind.AGENT_RUN,
            name=agent_name,
            success=success,
            error=str(error) if error else None,
            session_id=session_id,
        )
        _trace_states[trace_id] = reduce_event(_trace_states[trace_id], agent_end)
        _store.append(agent_end)
        
        # Cleanup
        if model_span_id in _estimated_usage:
            del _estimated_usage[model_span_id]
        if agent_span_id in _agent_model_spans:
            del _agent_model_spans[agent_span_id]
        
    except Exception as e:
        logger.debug(f"Agent trace error in agent_run_end: {e}")


def _custom_help():
    """Provide help for trace commands."""
    return [
        ("trace", "Agent trace: /trace status|list|show <id>|clear"),
    ]


def _handle_trace_command(command: str, name: str) -> Any:
    """Handle /trace slash commands."""
    if name != "trace":
        return None
    
    parts = command.strip().split()
    subcommand = parts[1] if len(parts) > 1 else "status"
    
    if subcommand == "status":
        active = sum(1 for s in _trace_states.values() for sp in s.spans.values() if sp.status == "running")
        total = sum(len(s.spans) for s in _trace_states.values())
        emit_info(f"📊 Active spans: {active}, Total spans: {total}, Traces: {len(_trace_states)}")
        return True
    
    if subcommand == "list":
        traces = _store.list_traces()
        if not traces:
            emit_info("📊 No stored traces")
        else:
            emit_info(f"📊 Stored traces: {', '.join(traces[:10])}" + 
                     (f" (+{len(traces)-10} more)" if len(traces) > 10 else ""))
        return True
    
    if subcommand == "show" and len(parts) > 2:
        trace_id = parts[2]
        events = _store.read(trace_id)
        emit_info(f"📊 Trace {trace_id}: {len(events)} events")
        return True
    
    if subcommand == "clear":
        _trace_states.clear()
        _session_spans.clear()
        _agent_model_spans.clear()
        _estimated_usage.clear()
        emit_info("📊 Trace state cleared")
        return True
    
    emit_info("Usage: /trace status|list|show <id>|clear")
    return True


# Register all callbacks
register_callback("startup", _on_startup)
register_callback("agent_run_start", _on_agent_run_start)
register_callback("stream_event", _on_stream_event)
register_callback("pre_tool_call", _on_pre_tool_call)
register_callback("post_tool_call", _on_post_tool_call)
register_callback("agent_run_end", _on_agent_run_end)
register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_trace_command)
