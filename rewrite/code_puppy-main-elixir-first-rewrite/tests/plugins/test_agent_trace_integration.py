"""Integration tests for Agent Trace accounting pipeline (bd-69).

Verifies:
- Stream token estimation works correctly
- Tool spans are matched by session (not name) - fixes bd-68
- Provider usage reconciliation - integrates with bd-66
- End-to-end trace structure
"""

import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from dataclasses import dataclass

import pytest

from code_puppy.plugins.agent_trace import (
    reducer,
    emitter,
    TraceState,
    reduce_event,
    NodeKind,
    TransferKind,
    TokenClass,
    AccountingState,
    EventType,
)
from code_puppy.plugins.agent_trace.register_callbacks import (
    _on_agent_run_start,
    _on_stream_event,
    _on_pre_tool_call,
    _on_post_tool_call,
    _on_agent_run_end,
    _session_spans,
    _trace_states,
    _agent_model_spans,
    _estimated_usage,
    _active_tool_spans,
    _store,
)


@dataclass
class MockContext:
    """Mock context object for tool call callbacks."""
    session_id: str | None = None


class TestAgentTraceStreamEvents:
    """Test stream event token estimation."""

    def setup_method(self):
        """Clear global state before each test."""
        _session_spans.clear()
        _trace_states.clear()
        _agent_model_spans.clear()
        _estimated_usage.clear()
        _active_tool_spans.clear()

    @pytest.mark.asyncio
    async def test_stream_events_capture_tokens(self):
        """Verify stream events with content_delta produce token estimates."""
        # Start an agent run to set up state
        session_id = "test-session-1"
        await _on_agent_run_start(
            agent_name="test_agent",
            model_name="gpt-4",
            session_id=session_id,
        )

        # Verify trace state was created
        assert session_id in _session_spans
        trace_id, agent_span_id, _ = _session_spans[session_id]
        assert trace_id in _trace_states

        # Simulate stream events with content_delta (normalized schema)
        event_data = {
            "content_delta": "Hello, this is a test response with some content",
            "args_delta": None,
            "tool_name": None,
            "tool_name_delta": None,
            "part_kind": "text",
            "index": 0,
            "raw": {},
        }

        await _on_stream_event(
            event_type="text_delta",
            event_data=event_data,
            agent_session_id=session_id,
        )

        # Verify token estimates were captured
        state = _trace_states[trace_id]
        model_spans = [s for s in state.spans.values() if s.kind == NodeKind.MODEL_CALL]
        assert len(model_spans) == 1

        model_span = model_spans[0]
        # Content ~46 chars / 4 = ~11 tokens estimated
        assert model_span.usage.output_tokens > 0
        assert model_span.usage.accounting == AccountingState.ESTIMATED_LIVE

        # Verify estimated usage tracking (keyed by model_span_id)
        model_span_id, _ = _agent_model_spans[agent_span_id]
        assert model_span_id in _estimated_usage
        assert _estimated_usage[model_span_id]["output"] > 0

    @pytest.mark.asyncio
    async def test_stream_events_multiple_deltas(self):
        """Verify multiple stream chunks accumulate token estimates."""
        session_id = "test-session-2"
        await _on_agent_run_start(
            agent_name="test_agent",
            model_name="gpt-4",
            session_id=session_id,
        )

        trace_id = _session_spans[session_id][0]

        # Simulate multiple stream chunks
        for i in range(5):
            await _on_stream_event(
                event_type="text_delta",
                event_data={
                    "content_delta": f"Chunk {i} with some text content here. ",
                    "part_kind": "text",
                    "index": i,
                    "raw": {},
                },
                agent_session_id=session_id,
            )

        state = _trace_states[trace_id]
        model_spans = [s for s in state.spans.values() if s.kind == NodeKind.MODEL_CALL]
        assert len(model_spans) == 1

        model_span = model_spans[0]
        # Should have accumulated tokens from all 5 chunks
        # Each chunk ~35 chars / 4 = ~8-9 tokens, 5 chunks = ~45 tokens
        assert model_span.usage.output_tokens >= 20  # Rough estimate

    @pytest.mark.asyncio
    async def test_stream_events_tool_call_args(self):
        """Verify stream events with tool args produce token estimates."""
        session_id = "test-session-3"
        await _on_agent_run_start(
            agent_name="test_agent",
            model_name="gpt-4",
            session_id=session_id,
        )

        trace_id = _session_spans[session_id][0]

        # Simulate tool call streaming with args_delta
        await _on_stream_event(
            event_type="tool_call_delta",
            event_data={
                "content_delta": None,
                "args_delta": '{"param1": "value1", "param2": "value2"}',
                "tool_name": "test_tool",
                "tool_name_delta": "test",
                "part_kind": "tool_call",
                "index": 0,
                "raw": {},
            },
            agent_session_id=session_id,
        )

        state = _trace_states[trace_id]
        model_spans = [s for s in state.spans.values() if s.kind == NodeKind.MODEL_CALL]
        assert len(model_spans) == 1

        model_span = model_spans[0]
        # Should count tokens from args_delta and tool_name_delta
        assert model_span.usage.output_tokens > 0

    @pytest.mark.asyncio
    async def test_stream_events_no_session(self):
        """Verify stream events without session are gracefully ignored."""
        # No session setup - should not throw
        await _on_stream_event(
            event_type="text_delta",
            event_data={"content_delta": "test"},
            agent_session_id="nonexistent-session",
        )
        # Should complete without error

    @pytest.mark.asyncio
    async def test_stream_events_invalid_data(self):
        """Verify stream events with invalid data are handled gracefully."""
        session_id = "test-session-4"
        await _on_agent_run_start(
            agent_name="test_agent",
            model_name="gpt-4",
            session_id=session_id,
        )

        # Invalid event data (not a dict)
        await _on_stream_event(
            event_type="text_delta",
            event_data="not a dict",  # Invalid
            agent_session_id=session_id,
        )
        # Should complete without error


class TestAgentTraceToolSpans:
    """Test tool span matching by session (bd-68 fix)."""

    def setup_method(self):
        """Clear global state before each test."""
        _session_spans.clear()
        _trace_states.clear()
        _agent_model_spans.clear()
        _estimated_usage.clear()
        _active_tool_spans.clear()

    @pytest.mark.asyncio
    async def test_tool_spans_matched_by_session(self):
        """Verify tool spans are matched by session, not by name."""
        # Start two different sessions using the same tool
        session_a = "session-a"
        session_b = "session-b"

        for session_id in [session_a, session_b]:
            await _on_agent_run_start(
                agent_name="test_agent",
                model_name="gpt-4",
                session_id=session_id,
            )

        # Start tool call in session A
        context_a = MockContext(session_id=session_a)
        await _on_pre_tool_call(
            tool_name="search_tool",
            tool_args={"query": "query_a"},
            context=context_a,
        )

        # Start tool call in session B (same tool name, different session)
        context_b = MockContext(session_id=session_b)
        await _on_pre_tool_call(
            tool_name="search_tool",
            tool_args={"query": "query_b"},
            context=context_b,
        )

        # Verify both spans are tracked separately
        assert session_a in _active_tool_spans
        assert session_b in _active_tool_spans
        span_id_a = _active_tool_spans[session_a]
        span_id_b = _active_tool_spans[session_b]
        assert span_id_a != span_id_b, "Tool spans should have unique IDs per session"

        # End tool call for session A
        await _on_post_tool_call(
            tool_name="search_tool",
            tool_args={"query": "query_a"},
            result={"results": ["result_a"]},
            duration_ms=100.0,
            context=context_a,
        )

        # Verify session A span ended, session B still running
        assert session_a not in _active_tool_spans  # Popped on end
        assert session_b in _active_tool_spans  # Still active

        # Get trace state and verify spans
        trace_id_a = _session_spans[session_a][0]
        state_a = _trace_states[trace_id_a]

        # Find the tool span for session A
        tool_spans_a = [s for s in state_a.spans.values() if s.kind == NodeKind.TOOL_CALL]
        assert len(tool_spans_a) == 1
        assert tool_spans_a[0].status == "done"  # Completed

        # Verify session B tool span is still running
        trace_id_b = _session_spans[session_b][0]
        state_b = _trace_states[trace_id_b]
        tool_spans_b = [s for s in state_b.spans.values() if s.kind == NodeKind.TOOL_CALL]
        assert len(tool_spans_b) == 1
        assert tool_spans_b[0].status == "running"  # Still active

    @pytest.mark.asyncio
    async def test_concurrent_tool_calls_dont_mix_up(self):
        """Verify concurrent tool calls don't mix up spans."""
        session_id = "concurrent-session"
        await _on_agent_run_start(
            agent_name="test_agent",
            model_name="gpt-4",
            session_id=session_id,
        )

        context = MockContext(session_id=session_id)

        # Start two different tools concurrently
        await _on_pre_tool_call(
            tool_name="tool_1",
            tool_args={"arg": 1},
            context=context,
        )

        span_id_1 = _active_tool_spans[session_id]

        # Note: This overwrites the active span - only one active tool per session
        # This is the design - sequential tool calls per session
        await _on_pre_tool_call(
            tool_name="tool_2",
            tool_args={"arg": 2},
            context=context,
        )

        span_id_2 = _active_tool_spans[session_id]
        assert span_id_1 != span_id_2, "New tool call should create new span"

        # End the second tool
        await _on_post_tool_call(
            tool_name="tool_2",
            tool_args={"arg": 2},
            result={"done": True},
            duration_ms=50.0,
            context=context,
        )

        # Verify trace has both spans
        trace_id = _session_spans[session_id][0]
        state = _trace_states[trace_id]
        tool_spans = [s for s in state.spans.values() if s.kind == NodeKind.TOOL_CALL]
        assert len(tool_spans) == 2

    @pytest.mark.asyncio
    async def test_tool_call_without_context(self):
        """Verify tool call without context is gracefully ignored."""
        await _on_pre_tool_call(
            tool_name="test_tool",
            tool_args={},
            context=None,
        )
        # Should complete without error

    @pytest.mark.asyncio
    async def test_tool_call_with_invalid_context(self):
        """Verify tool call with invalid context is handled."""
        class InvalidContext:
            pass

        await _on_pre_tool_call(
            tool_name="test_tool",
            tool_args={},
            context=InvalidContext(),  # No session_id attribute
        )
        # Should complete without error


class TestAgentTraceProviderUsage:
    """Test provider usage reconciliation (integrates with bd-66)."""

    def setup_method(self):
        """Clear global state before each test."""
        _session_spans.clear()
        _trace_states.clear()
        _agent_model_spans.clear()
        _estimated_usage.clear()
        _active_tool_spans.clear()

    @pytest.mark.asyncio
    async def test_provider_usage_reconciliation(self):
        """Verify provider usage metadata reconciles estimated to exact tokens."""
        session_id = "reconciliation-session"
        await _on_agent_run_start(
            agent_name="test_agent",
            model_name="gpt-4",
            session_id=session_id,
        )

        trace_id, agent_span_id, _ = _session_spans[session_id]

        # Generate some estimated tokens via streaming
        await _on_stream_event(
            event_type="text_delta",
            event_data={
                "content_delta": "Estimated content with some length here.",
                "part_kind": "text",
                "index": 0,
                "raw": {},
            },
            agent_session_id=session_id,
        )

        # Verify we have estimated tokens
        state_before = _trace_states[trace_id]
        model_spans = [s for s in state_before.spans.values() if s.kind == NodeKind.MODEL_CALL]
        assert len(model_spans) == 1
        estimated_tokens = model_spans[0].usage.output_tokens
        assert estimated_tokens > 0

        # End with provider usage metadata (bd-66 integration point)
        await _on_agent_run_end(
            agent_name="test_agent",
            model_name="gpt-4",
            session_id=session_id,
            success=True,
            metadata={
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "reasoning_tokens": 10,
                    "cached_tokens": 5,
                }
            },
        )

        # Verify reconciliation occurred
        state_after = _trace_states[trace_id]
        model_spans_after = [s for s in state_after.spans.values() if s.kind == NodeKind.MODEL_CALL]
        assert len(model_spans_after) == 1

        reconciled_span = model_spans_after[0]
        assert reconciled_span.usage.output_tokens == 50  # Exact, not estimated
        assert reconciled_span.usage.input_tokens == 100
        assert reconciled_span.usage.reasoning_tokens == 10
        assert reconciled_span.usage.reconciled is True
        assert reconciled_span.usage.accounting == AccountingState.RECONCILED

    @pytest.mark.asyncio
    async def test_reconciliation_without_provider_usage(self):
        """Verify graceful handling when no provider usage is available."""
        session_id = "no-reconciliation-session"
        await _on_agent_run_start(
            agent_name="test_agent",
            model_name="gpt-4",
            session_id=session_id,
        )

        trace_id = _session_spans[session_id][0]

        # Generate some estimated tokens
        await _on_stream_event(
            event_type="text_delta",
            event_data={"content_delta": "Some content", "part_kind": "text", "raw": {}},
            agent_session_id=session_id,
        )

        # End without provider usage metadata
        await _on_agent_run_end(
            agent_name="test_agent",
            model_name="gpt-4",
            session_id=session_id,
            success=True,
            metadata=None,  # No usage data
        )

        # Should complete without error - span ends but no reconciliation
        state = _trace_states[trace_id]
        model_spans = [s for s in state.spans.values() if s.kind == NodeKind.MODEL_CALL]
        assert len(model_spans) == 1
        assert model_spans[0].status == "done"

    @pytest.mark.asyncio
    async def test_emit_usage_reported_event(self):
        """Verify emit_usage_reported creates correct event structure."""
        event = emitter.emit_usage_reported(
            trace_id="test-trace",
            span_id="test-span",
            node_id="test-node",
            input_tokens=100,
            output_tokens=50,
            reasoning_tokens=10,
            cached_tokens=5,
            accounting=AccountingState.PROVIDER_REPORTED_EXACT,
            cost_usd=0.0025,
            model_name="gpt-4",
            session_id="test-session",
        )

        assert event.event_type == EventType.USAGE_REPORTED
        assert event.trace_id == "test-trace"
        assert event.span_id == "test-span"
        assert event.session_id == "test-session"
        assert event.transfer is not None
        assert event.transfer.token_count == 50
        assert event.transfer.accounting == AccountingState.PROVIDER_REPORTED_EXACT

        assert event.extra is not None
        usage = event.extra.get("usage", {})
        assert usage["input_tokens"] == 100
        assert usage["output_tokens"] == 50
        assert usage["reasoning_tokens"] == 10
        assert usage["cached_tokens"] == 5
        assert usage["model_name"] == "gpt-4"

    @pytest.mark.asyncio
    async def test_emit_usage_reconciled_event(self):
        """Verify emit_usage_reconciled creates correct event structure."""
        event = emitter.emit_usage_reconciled(
            trace_id="test-trace",
            span_id="test-span",
            node_id="test-node",
            estimated_input=80,
            estimated_output=40,
            exact_input=100,
            exact_output=50,
            exact_reasoning=10,
            exact_cached=5,
            cost_usd=0.0025,
            session_id="test-session",
        )

        assert event.event_type == EventType.USAGE_RECONCILED
        assert event.trace_id == "test-trace"
        assert event.transfer is not None
        assert event.transfer.accounting == AccountingState.RECONCILED

        assert event.extra is not None
        reconciliation = event.extra.get("reconciliation", {})
        assert reconciliation["estimated"]["input_tokens"] == 80
        assert reconciliation["estimated"]["output_tokens"] == 40
        assert reconciliation["exact"]["input_tokens"] == 100
        assert reconciliation["exact"]["output_tokens"] == 50
        assert reconciliation["exact"]["reasoning_tokens"] == 10
        assert reconciliation["exact"]["cached_tokens"] == 5
        assert reconciliation["drift"]["input_tokens"] == 20  # 100 - 80
        assert reconciliation["drift"]["output_tokens"] == 10  # 50 - 40


class TestAgentTraceEndToEnd:
    """Test complete end-to-end trace flow."""

    def setup_method(self):
        """Clear global state before each test."""
        _session_spans.clear()
        _trace_states.clear()
        _agent_model_spans.clear()
        _estimated_usage.clear()
        _active_tool_spans.clear()

    @pytest.mark.asyncio
    async def test_end_to_end_trace_structure(self):
        """Verify complete run: start → stream → tool → stream → end."""
        session_id = "e2e-session"

        # 1. Agent run start
        await _on_agent_run_start(
            agent_name="code_explorer",
            model_name="claude-3-sonnet",
            session_id=session_id,
        )

        trace_id, agent_span_id, agent_node_id = _session_spans[session_id]
        state = _trace_states[trace_id]

        # Verify initial structure
        agent_spans = [s for s in state.spans.values() if s.kind == NodeKind.AGENT_RUN]
        model_spans = [s for s in state.spans.values() if s.kind == NodeKind.MODEL_CALL]
        assert len(agent_spans) == 1
        assert len(model_spans) == 1
        assert model_spans[0].parent_span_id == agent_span_id
        assert agent_spans[0].status == "running"

        # 2. Stream events (model output)
        for i in range(3):
            await _on_stream_event(
                event_type="text_delta",
                event_data={
                    "content_delta": f"Response part {i}: analyzing code structure. ",
                    "part_kind": "text",
                    "index": i,
                    "raw": {},
                },
                agent_session_id=session_id,
            )

        # 3. Tool call (pre)
        context = MockContext(session_id=session_id)
        await _on_pre_tool_call(
            tool_name="list_files",
            tool_args={"directory": ".", "recursive": True},
            context=context,
        )

        # Verify tool span created
        state = _trace_states[trace_id]
        tool_spans = [s for s in state.spans.values() if s.kind == NodeKind.TOOL_CALL]
        assert len(tool_spans) == 1
        assert tool_spans[0].status == "running"
        assert tool_spans[0].name == "list_files"

        # 4. Tool call (post)
        await _on_post_tool_call(
            tool_name="list_files",
            tool_args={"directory": ".", "recursive": True},
            result=["file1.py", "file2.py"],
            duration_ms=150.0,
            context=context,
        )

        # Verify tool span ended
        state = _trace_states[trace_id]
        tool_spans = [s for s in state.spans.values() if s.kind == NodeKind.TOOL_CALL]
        assert tool_spans[0].status == "done"
        assert tool_spans[0].duration_ms is not None

        # 5. More stream events after tool
        await _on_stream_event(
            event_type="text_delta",
            event_data={
                "content_delta": "Based on the files found, let me continue analyzing.",
                "part_kind": "text",
                "index": 4,
                "raw": {},
            },
            agent_session_id=session_id,
        )

        # 6. Agent run end
        await _on_agent_run_end(
            agent_name="code_explorer",
            model_name="claude-3-sonnet",
            session_id=session_id,
            success=True,
            metadata={
                "usage": {
                    "input_tokens": 500,
                    "output_tokens": 200,
                }
            },
        )

        # Final verification
        state = _trace_states[trace_id]

        # All spans ended
        agent_spans = [s for s in state.spans.values() if s.kind == NodeKind.AGENT_RUN]
        model_spans = [s for s in state.spans.values() if s.kind == NodeKind.MODEL_CALL]
        tool_spans = [s for s in state.spans.values() if s.kind == NodeKind.TOOL_CALL]

        assert agent_spans[0].status == "done"
        assert model_spans[0].status == "done"
        assert model_spans[0].usage.reconciled is True
        assert model_spans[0].usage.output_tokens == 200
        assert model_spans[0].usage.input_tokens == 500

        # Hierarchy verified
        assert model_spans[0].parent_span_id == agent_spans[0].span_id
        assert tool_spans[0].parent_span_id == model_spans[0].span_id

    @pytest.mark.asyncio
    async def test_failed_agent_run(self):
        """Verify trace handles failed agent runs correctly."""
        session_id = "failed-session"

        await _on_agent_run_start(
            agent_name="failing_agent",
            model_name="gpt-4",
            session_id=session_id,
        )

        trace_id = _session_spans[session_id][0]

        # Some streaming
        await _on_stream_event(
            event_type="text_delta",
            event_data={"content_delta": "Starting operation...", "part_kind": "text", "raw": {}},
            agent_session_id=session_id,
        )

        # End with error
        error = Exception("Something went wrong")
        await _on_agent_run_end(
            agent_name="failing_agent",
            model_name="gpt-4",
            session_id=session_id,
            success=False,
            error=error,
            metadata=None,
        )

        # Verify error state
        state = _trace_states[trace_id]
        agent_spans = [s for s in state.spans.values() if s.kind == NodeKind.AGENT_RUN]
        assert len(agent_spans) == 1
        assert agent_spans[0].status == "failed"
        assert agent_spans[0].error == "Something went wrong"

    @pytest.mark.asyncio
    async def test_multiple_agent_runs_same_session(self):
        """Verify multiple agent runs in same session are tracked."""
        session_id = "multi-run-session"

        # First run
        await _on_agent_run_start(
            agent_name="agent_1",
            model_name="gpt-4",
            session_id=session_id,
        )

        await _on_agent_run_end(
            agent_name="agent_1",
            model_name="gpt-4",
            session_id=session_id,
            success=True,
        )

        # Second run
        await _on_agent_run_start(
            agent_name="agent_2",
            model_name="claude-3",
            session_id=session_id,
        )

        await _on_agent_run_end(
            agent_name="agent_2",
            model_name="claude-3",
            session_id=session_id,
            success=True,
        )

        # Verify trace has both agent runs
        trace_id = _session_spans[session_id][0]
        state = _trace_states[trace_id]
        agent_spans = [s for s in state.spans.values() if s.kind == NodeKind.AGENT_RUN]
        assert len(agent_spans) == 2

    @pytest.mark.asyncio
    async def test_trace_token_budget(self):
        """Verify trace tracks token budget correctly."""
        session_id = "budget-session"

        await _on_agent_run_start(
            agent_name="budget_agent",
            model_name="gpt-4",
            session_id=session_id,
        )

        trace_id = _session_spans[session_id][0]

        # Simulate significant token usage
        large_content = "x" * 400  # 100 tokens at 4 chars per token
        await _on_stream_event(
            event_type="text_delta",
            event_data={"content_delta": large_content, "part_kind": "text", "raw": {}},
            agent_session_id=session_id,
        )

        state = _trace_states[trace_id]
        model_spans = [s for s in state.spans.values() if s.kind == NodeKind.MODEL_CALL]
        assert len(model_spans) == 1
        assert model_spans[0].usage.output_tokens >= 90  # ~100 estimated


class TestAgentTraceReducer:
    """Test the reducer functionality directly."""

    def test_reduce_span_started(self):
        """Verify reducer handles span.started events."""
        state = TraceState(trace_id="test-trace")

        event = emitter.emit_span_started(
            trace_id="test-trace",
            kind=NodeKind.AGENT_RUN,
            name="test_agent",
        )

        new_state = reduce_event(state, event)

        assert len(new_state.spans) == 1
        assert event.span_id in new_state.spans
        span = new_state.spans[event.span_id]
        assert span.kind == NodeKind.AGENT_RUN
        assert span.name == "test_agent"
        assert span.status == "running"

    def test_reduce_span_ended(self):
        """Verify reducer handles span.ended events."""
        # Start span
        state = TraceState(trace_id="test-trace")
        start_event = emitter.emit_span_started(
            trace_id="test-trace",
            kind=NodeKind.AGENT_RUN,
            name="test_agent",
        )
        state = reduce_event(state, start_event)

        # End span
        end_event = emitter.emit_span_ended(
            trace_id="test-trace",
            span_id=start_event.span_id,
            node_id=start_event.node.id,
            kind=NodeKind.AGENT_RUN,
            name="test_agent",
            success=True,
            duration_ms=1000.0,
        )
        state = reduce_event(state, end_event)

        span = state.spans[start_event.span_id]
        assert span.status == "done"
        assert span.ended_at is not None
        assert span.duration_ms == 1000.0

    def test_reduce_transfer_tokens(self):
        """Verify reducer accumulates transfer tokens."""
        state = TraceState(trace_id="test-trace")

        # Create a span first
        start_event = emitter.emit_span_started(
            trace_id="test-trace",
            kind=NodeKind.MODEL_CALL,
            name="gpt-4",
        )
        state = reduce_event(state, start_event)
        span_id = start_event.span_id

        # Add transfers
        for _ in range(5):
            transfer_event = emitter.emit_transfer(
                trace_id="test-trace",
                kind=TransferKind.MODEL_OUTPUT,
                source_node_id=start_event.node.id,
                token_count=10,
                token_class=TokenClass.OUTPUT_TOKENS,
                accounting=AccountingState.ESTIMATED_LIVE,
                span_id=span_id,
            )
            state = reduce_event(state, transfer_event)

        span = state.spans[span_id]
        assert span.usage.output_tokens == 50  # 5 * 10
        assert span.usage.accounting == AccountingState.ESTIMATED_LIVE

    def test_reduce_usage_reconciled(self):
        """Verify reducer reconciles estimated to exact tokens."""
        state = TraceState(trace_id="test-trace")

        # Start span
        start_event = emitter.emit_span_started(
            trace_id="test-trace",
            kind=NodeKind.MODEL_CALL,
            name="gpt-4",
        )
        state = reduce_event(state, start_event)
        span_id = start_event.span_id
        node_id = start_event.node.id

        # Add estimated transfer
        transfer_event = emitter.emit_transfer(
            trace_id="test-trace",
            kind=TransferKind.MODEL_OUTPUT,
            token_count=40,
            token_class=TokenClass.OUTPUT_TOKENS,
            accounting=AccountingState.ESTIMATED_LIVE,
            span_id=span_id,
        )
        state = reduce_event(state, transfer_event)

        # Reconcile
        reconcile_event = emitter.emit_usage_reconciled(
            trace_id="test-trace",
            span_id=span_id,
            node_id=node_id,
            estimated_input=0,
            estimated_output=40,
            exact_input=100,
            exact_output=50,
        )
        state = reduce_event(state, reconcile_event)

        span = state.spans[span_id]
        assert span.usage.output_tokens == 50  # Exact value
        assert span.usage.input_tokens == 100
        assert span.usage.reconciled is True
        assert span.usage.accounting == AccountingState.RECONCILED

    def test_replay_trace(self):
        """Verify trace replay reconstructs state."""
        events = []

        # Build a sequence of events
        start_event = emitter.emit_span_started(
            trace_id="replay-trace",
            kind=NodeKind.AGENT_RUN,
            name="test_agent",
        )
        events.append(start_event)

        transfer_event = emitter.emit_transfer(
            trace_id="replay-trace",
            kind=TransferKind.MODEL_OUTPUT,
            token_count=25,
            token_class=TokenClass.OUTPUT_TOKENS,
            accounting=AccountingState.ESTIMATED_LIVE,
            span_id=start_event.span_id,
        )
        events.append(transfer_event)

        end_event = emitter.emit_span_ended(
            trace_id="replay-trace",
            span_id=start_event.span_id,
            node_id=start_event.node.id,
            kind=NodeKind.AGENT_RUN,
            success=True,
        )
        events.append(end_event)

        # Replay
        from code_puppy.plugins.agent_trace.reducer import replay_trace
        state = replay_trace(events)

        assert state.trace_id == "replay-trace"
        assert len(state.spans) == 1
        span = state.spans[start_event.span_id]
        assert span.kind == NodeKind.AGENT_RUN
        assert span.status == "done"
        assert span.usage.output_tokens == 25
