"""Shared utility modules for Code Puppy.

Inspired by patterns from oh-my-pi (omp) project.
"""

from .agent_helpers import invert_conversation_roles
from .emit import emit_error, emit_info, emit_success, emit_warning
from .ring_buffer import RingBuffer
from .parallel import map_with_concurrency, Semaphore, ParallelResult, Bulkhead, BulkheadStats, BulkheadFullError, BulkheadTimeoutError
from .file_mutex import file_lock, file_lock_sync, active_lock_count, cross_process_file_lock, cross_process_file_lock_sync
from .overflow_detect import is_context_overflow, is_rate_limit_error
from .macos_path import resolve_path_with_variants
from .clipboard import copy_to_clipboard, osc52_copy
from .eol import strip_bom, restore_bom
from .dag import build_dependency_graph, detect_cycles, build_execution_waves
from .shell_split import split_compound_command
from .stream_parser import StreamLineParser, SSEParser, parse_jsonl_lenient
from .llm_parsing import extract_json_from_text
from .file_display import (
    format_content_with_line_numbers,
    truncate_with_guidance,
    open_nofollow,
    safe_write_file,
    inject_scope_context,
)
from .checkpoint import CheckpointStore
from .install_hints import install_hint, format_missing_tool_message
from .path_safety import (
    PathSafetyError,
    PathTraversalError,
    UnsafeComponentError,
    safe_path_component,
    safe_join,
    verify_contained,
)
# New utilities from comparative review (oh-my-pi patterns)
from .fs_errors import (
    is_fs_error,
    is_enoent,
    is_eacces,
    is_eisdir,
    is_enotdir,
    is_eexist,
    is_enotempty,
    is_eperm,
    is_enospc,
    is_erofs,
    has_fs_code,
    get_fs_code,
)
from .config_resolve import (
    resolve_config_value,
    resolve_config_value_sync,
    resolve_headers,
    resolve_headers_sync,
    clear_config_value_cache,
)
from .peek_file import peek_file_sync, peek_file, reset_pools

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
    "Bulkhead",
    "BulkheadStats",
    "BulkheadFullError",
    "BulkheadTimeoutError",
    # File mutation serialization (ported from pi-mono-main)
    "file_lock",
    "file_lock_sync",
    "active_lock_count",
    # Cross-process file locking (ported from oh-my-pi)
    "cross_process_file_lock",
    "cross_process_file_lock_sync",
    # Context overflow detection (ported from pi-mono-main)
    "is_context_overflow",
    "is_rate_limit_error",
    # macOS path variant resolution (ported from pi-mono-main)
    "resolve_path_with_variants",
    # Clipboard with OSC 52 (ported from pi-mono-main)
    "copy_to_clipboard",
    "osc52_copy",
    # BOM handling (ported from pi-mono-main)
    "strip_bom",
    "restore_bom",
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
    "inject_scope_context",
    # Checkpointing (ported from Agentless skip_existing pattern)
    "CheckpointStore",
    # Install hints (ported from deepagents)
    "install_hint",
    "format_missing_tool_message",
    # Path safety utilities (security)
    "PathSafetyError",
    "PathTraversalError",
    "UnsafeComponentError",
    "safe_path_component",
    "safe_join",
    "verify_contained",
    # FS error type guards (ported from oh-my-pi)
    "is_fs_error",
    "is_enoent",
    "is_eacces",
    "is_eisdir",
    "is_enotdir",
    "is_eexist",
    "is_enotempty",
    "is_eperm",
    "is_enospc",
    "is_erofs",
    "has_fs_code",
    "get_fs_code",
    # Config value resolution (ported from oh-my-pi)
    "resolve_config_value",
    "resolve_config_value_sync",
    "resolve_headers",
    "resolve_headers_sync",
    "clear_config_value_cache",
    # Buffer-pooled file peeking (ported from oh-my-pi)
    "peek_file_sync",
    "peek_file",
    "reset_pools",
]
