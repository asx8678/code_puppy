"""Compaction module: enhanced summarization utilities.

This module provides three enhancements to code_puppy's existing summarization:
1. Model-aware fraction thresholds (thresholds.py)
2. Tool arg pre-truncation phase (tool_arg_truncation.py)
3. History offload to file (history_offload.py)
"""

from code_puppy.compaction.history_offload import (
    offload_evicted_messages,
)
from code_puppy.compaction.thresholds import (
    SummarizationThresholds,
    compute_summarization_thresholds,
    get_model_context_window,
)
from code_puppy.compaction.tool_arg_truncation import (
    pretruncate_messages,
    truncate_tool_arg,
    truncate_tool_call_args,
)

__all__ = [
    "compute_summarization_thresholds",
    "get_model_context_window",
    "offload_evicted_messages",
    "pretruncate_messages",
    "SummarizationThresholds",
    "truncate_tool_arg",
    "truncate_tool_call_args",
]
