"""Shared utility modules for Code Puppy.

Inspired by patterns from oh-my-pi (omp) project.
"""

from .agent_helpers import invert_conversation_roles
from .emit import emit_error, emit_info, emit_success, emit_warning
from .ring_buffer import RingBuffer
from .parallel import map_with_concurrency, Semaphore, ParallelResult
from .dag import build_dependency_graph, detect_cycles, build_execution_waves
from .shell_split import split_compound_command
from .stream_parser import StreamLineParser, SSEParser, parse_jsonl_lenient
from .llm_parsing import extract_json_from_text
from .file_display import (
    format_content_with_line_numbers,
    truncate_with_guidance,
    open_nofollow,
    safe_write_file,
)

__all__ = [
    # Agent helpers
    "invert_conversation_roles",
    # Emit utilities
    "emit_error",
    "emit_info",
    "emit_success",
    "emit_warning",
    # Existing utilities
    "RingBuffer",
    "map_with_concurrency",
    "Semaphore",
    "ParallelResult",
    "build_dependency_graph",
    "detect_cycles",
    "build_execution_waves",
    "split_compound_command",
    "StreamLineParser",
    "SSEParser",
    "parse_jsonl_lenient",
    # LLM parsing utilities
    "extract_json_from_text",
    # File display utilities (ported from deepagents)
    "format_content_with_line_numbers",
    "truncate_with_guidance",
    "open_nofollow",
    "safe_write_file",
]
