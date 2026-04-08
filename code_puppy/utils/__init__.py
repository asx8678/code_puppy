"""Shared utility modules for Code Puppy.

Inspired by patterns from oh-my-pi (omp) project.
"""

from .emit import emit_error, emit_info, emit_success, emit_warning
from .ring_buffer import RingBuffer
from .parallel import map_with_concurrency, Semaphore, ParallelResult
from .dag import build_dependency_graph, detect_cycles, build_execution_waves
from .shell_split import split_compound_command
from .stream_parser import StreamLineParser, SSEParser, parse_jsonl_lenient

__all__ = [
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
]
