"""Agent Trace V2 — Normalized observability for agent execution.

This plugin provides:
- Normalized event schema with accounting state
- Explicit model call nodes (separate from agent runs)
- Reconciliation events (live estimates → exact usage)
- NDJSON persistence for replay
- Pure reducer for state management

See: agent_flow_v2_design.md for architecture details.
"""

from code_puppy.plugins.agent_trace.schema import (
    TraceEvent,
    EventType,
    NodeKind,
    TransferKind,
    TokenClass,
    AccountingState,
    NodeInfo,
    TransferInfo,
    MetricsInfo,
)
from code_puppy.plugins.agent_trace.emitter import (
    emit_span_started,
    emit_span_ended,
    emit_transfer,
    emit_usage_reported,
    emit_usage_reconciled,
)
from code_puppy.plugins.agent_trace.store import TraceStore
from code_puppy.plugins.agent_trace.reducer import (
    TraceState,
    SpanState,
    TokenUsage,
    reduce_event,
    replay_trace,
)
from code_puppy.plugins.agent_trace.cli_renderer import (
    render_trace,
    render_live,
    set_render_enabled,
    is_render_enabled,
    clear_previous_render,
)
from code_puppy.plugins.agent_trace.analytics import (
    TokenBudget,
    RunMetrics,
    RunComparison,
    Outlier,
    OutlierReport,
    analyze_token_budget,
    compare_runs,
    detect_outliers,
    export_json,
    export_otel,
    export_csv,
)
from code_puppy.plugins.agent_trace.cli_analytics import (
    render_token_budget,
    render_comparison,
    render_outlier_report,
    render_trace_summary,
    render_inline_summary,
)

__all__ = [
    # Schema
    "TraceEvent",
    "EventType",
    "NodeKind",
    "TransferKind",
    "TokenClass",
    "AccountingState",
    "NodeInfo",
    "TransferInfo",
    "MetricsInfo",
    # Emitters
    "emit_span_started",
    "emit_span_ended",
    "emit_transfer",
    "emit_usage_reported",
    "emit_usage_reconciled",
    # Store
    "TraceStore",
    # Reducer
    "TraceState",
    "SpanState",
    "TokenUsage",
    "reduce_event",
    "replay_trace",
    # CLI Renderer
    "render_trace",
    "render_live",
    "set_render_enabled",
    "is_render_enabled",
    "clear_previous_render",
    # Analytics
    "TokenBudget",
    "RunMetrics",
    "RunComparison",
    "Outlier",
    "OutlierReport",
    "analyze_token_budget",
    "compare_runs",
    "detect_outliers",
    "export_json",
    "export_otel",
    "export_csv",
    # CLI Analytics
    "render_token_budget",
    "render_comparison",
    "render_outlier_report",
    "render_trace_summary",
    "render_inline_summary",
]
