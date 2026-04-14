"""Zig cffi bridge - direct bindings to Zig shared libraries.

Exposes: ZIG_AVAILABLE, process_messages_batch(), prune_and_filter(),
process_messages_batch_binary(), parse_source(), list_files(), grep(),
is_language_supported()
"""

from __future__ import annotations

import json
import os
import platform
from pathlib import Path
from typing import Any, Callable

# ── cffi setup ────────────────────────────────────────────────────────────────
try:
    from cffi import FFI
    _ffi = FFI()
    CFFI_AVAILABLE = True
except ImportError:
    CFFI_AVAILABLE = False
    _ffi = None  # type: ignore[assignment]


def _get_lib_ext() -> str:
    system = platform.system()
    return ".dylib" if system == "Darwin" else ".dll" if system == "Windows" else ".so"


def _find_lib(name: str) -> Path | None:
    ext = _get_lib_ext()
    base = Path(__file__).parent.parent.parent
    paths = [
        Path.cwd() / "zig-out" / "lib" / f"lib{name}{ext}",
        base / "zig-out" / "lib" / f"lib{name}{ext}",
        Path(f"/usr/local/lib/lib{name}{ext}"),
        Path(f"/usr/lib/lib{name}{ext}"),
    ]
    for env in ["LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "PATH"]:
        if env in os.environ:
            paths += [Path(p) / f"lib{name}{ext}" for p in os.environ[env].split(os.pathsep)]
    for p in paths:
        if p.exists():
            return p
    return None


def _load_lib(name: str) -> Any | None:
    if not CFFI_AVAILABLE or _ffi is None:
        return None
    path = _find_lib(name)
    if path is None:
        return None
    try:
        return _ffi.dlopen(str(path))
    except (OSError, AttributeError):
        return None


# ── C declarations ───────────────────────────────────────────────────────────
if CFFI_AVAILABLE and _ffi is not None:
    _ffi.cdef("""
        typedef void* PuppyCoreHandle;
        typedef enum { success=0, invalid_argument=-1, out_of_memory=-2,
                       serialization_failed=-3, pruning_failed=-4 } PuppyCoreError;
        PuppyCoreHandle puppy_core_create(void);
        void puppy_core_destroy(PuppyCoreHandle handle);
        PuppyCoreError puppy_core_process_messages(PuppyCoreHandle h, const char* msgs,
            const char* sys, char** out);
        void puppy_core_free_string(char* ptr);

        // Binary protocol for fast FFI (avoids JSON serialization)
        PuppyCoreError puppy_core_process_messages_binary(
            PuppyCoreHandle h,
            const uint8_t* input_data,
            size_t input_len,
            const char* sys,
            uint8_t** output_data,
            size_t* output_len
        );
        void puppy_core_free_bytes(uint8_t* ptr, size_t len);

        typedef void* TurboOpsHandle;
        typedef enum { tops_success=0, tops_invalid=-1 } TurboOpsError;
        TurboOpsHandle turbo_ops_create(int parallel);
        void turbo_ops_destroy(TurboOpsHandle handle);
        TurboOpsError turbo_ops_list_files(TurboOpsHandle h, const char* dir,
            int recursive, char** out);
        TurboOpsError turbo_ops_grep(TurboOpsHandle h, const char* pat,
            const char* dir, char** out);
        void turbo_ops_free_string(char* ptr);

        typedef void* TurboParseHandle;
        typedef enum { tps_success=0, tps_invalid=-1, tps_lang_not_found=-3 } TurboParseError;
        TurboParseHandle turbo_parse_create(void);
        void turbo_parse_destroy(TurboParseHandle handle);
        TurboParseError turbo_parse_source(TurboParseHandle h, const char* src,
            const char* lang, char** out);
        int turbo_parse_is_language_supported(const char* lang);
        void turbo_parse_free_string(char* ptr);
    """)

_lib_puppy_core = _load_lib("zig_puppy_core") if CFFI_AVAILABLE else None
_lib_turbo_ops = _load_lib("zig_turbo_ops") if CFFI_AVAILABLE else None
_lib_turbo_parse = _load_lib("zig_turbo_parse") if CFFI_AVAILABLE else None
ZIG_AVAILABLE = any([lib is not None for lib in [_lib_puppy_core, _lib_turbo_ops, _lib_turbo_parse]])

# ── Handle cache (module-level singletons) ───────────────────────────────────
_cached_puppy_core_handle = None
_cached_turbo_ops_handle = None
_cached_turbo_parse_handle = None


def _get_puppy_core_handle():
    """Get cached puppy_core handle (lazy initialization)."""
    global _cached_puppy_core_handle
    if _cached_puppy_core_handle is None and _lib_puppy_core is not None:
        _cached_puppy_core_handle = _lib_puppy_core.puppy_core_create()
    return _cached_puppy_core_handle


def _get_turbo_ops_handle():
    """Get cached turbo_ops handle (lazy initialization)."""
    global _cached_turbo_ops_handle
    if _cached_turbo_ops_handle is None and _lib_turbo_ops is not None:
        _cached_turbo_ops_handle = _lib_turbo_ops.turbo_ops_create(1)
    return _cached_turbo_ops_handle


def _get_turbo_parse_handle():
    """Get cached turbo_parse handle (lazy initialization)."""
    global _cached_turbo_parse_handle
    if _cached_turbo_parse_handle is None and _lib_turbo_parse is not None:
        _cached_turbo_parse_handle = _lib_turbo_parse.turbo_parse_create()
    return _cached_turbo_parse_handle


def _zig_str_to_py(zig_ptr: Any, free_fn: Callable[[Any], None]) -> str:
    if zig_ptr is None:
        return ""
    py_str = _ffi.string(zig_ptr).decode("utf-8")  # type: ignore[attr-defined]
    free_fn(zig_ptr)
    return py_str


def _safe_call(lib: Any, fn: str, *args: Any, free: str = "") -> dict[str, Any]:
    if lib is None:
        return {"success": False, "error": "Zig library not loaded"}
    fn_obj = getattr(lib, fn, None)
    if fn_obj is None:
        return {"success": False, "error": f"{fn} not found"}
    if free:
        out = _ffi.new("char**")  # type: ignore[attr-defined]
        rc = fn_obj(*args, out)
        if rc != 0:
            return {"success": False, "error": f"Zig error: {rc}"}
        if out[0] == _ffi.NULL:  # type: ignore[attr-defined]
            return {"success": False, "error": "Zig returned null pointer"}
        output = _zig_str_to_py(out[0], getattr(lib, free))
        try:
            return {"success": True, "data": json.loads(output)}
        except json.JSONDecodeError:
            return {"success": True, "raw": output}
    return {"success": True, "result": fn_obj(*args)}


# ── Public API ───────────────────────────────────────────────────────────────
def process_messages_batch(messages: list[dict], system_prompt: str = "") -> dict[str, Any]:
    h = _get_puppy_core_handle()
    if h is None:
        return {"success": False, "error": "zig_puppy_core not available"}
    return _safe_call(_lib_puppy_core, "puppy_core_process_messages",
        h, json.dumps(messages).encode(), system_prompt.encode(),
        free="puppy_core_free_string")


def prune_and_filter(messages: list[dict], max_tokens: int = 50000) -> dict[str, Any]:
    # TODO: Implement once Zig side is complete
    return {"success": False, "error": "Not yet implemented in Zig"}


def list_files(directory: str = ".", recursive: bool = True) -> dict[str, Any]:
    h = _get_turbo_ops_handle()
    if h is None:
        return {"success": False, "error": "zig_turbo_ops not available"}
    return _safe_call(_lib_turbo_ops, "turbo_ops_list_files",
        h, directory.encode(), 1 if recursive else 0, free="turbo_ops_free_string")


def grep(pattern: str, directory: str = ".") -> dict[str, Any]:
    h = _get_turbo_ops_handle()
    if h is None:
        return {"success": False, "error": "zig_turbo_ops not available"}
    return _safe_call(_lib_turbo_ops, "turbo_ops_grep",
        h, pattern.encode(), directory.encode(), free="turbo_ops_free_string")


def parse_source(source: str, language: str) -> dict[str, Any]:
    h = _get_turbo_parse_handle()
    if h is None:
        return {"success": False, "error": "zig_turbo_parse not available"}
    return _safe_call(_lib_turbo_parse, "turbo_parse_source",
        h, source.encode(), language.encode(), free="turbo_parse_free_string")


def is_language_supported(language: str) -> bool:
    if _lib_turbo_parse is None:
        return False
    return bool(_lib_turbo_parse.turbo_parse_is_language_supported(language.encode()))


# ── Binary Protocol Helpers ──────────────────────────────────────────────────

def _pack_messages_binary(messages: list[dict]) -> bytes:
    """Pack messages into compact binary format.

    Format:
        [u32 message_count]
        For each message:
          [u8 role_len][role bytes]
          [u32 parts_count]
          For each part:
            [u32 content_len][content bytes]
    """
    import struct
    buf = bytearray()
    buf.extend(struct.pack('<I', len(messages)))  # u32 count

    for msg in messages:
        role = (msg.get('role') or '').encode('utf-8')
        buf.append(len(role))  # u8 role_len
        buf.extend(role)
        parts = msg.get('parts', [])
        buf.extend(struct.pack('<I', len(parts)))  # u32 parts_count

        for part in parts:
            # Try content first, fall back to content_json
            content = (part.get('content') or part.get('content_json') or '').encode('utf-8')
            buf.extend(struct.pack('<I', len(content)))  # u32 content_len
            buf.extend(content)

    return bytes(buf)


def _unpack_result_binary(data: bytes) -> dict[str, Any]:
    """Unpack binary result from Zig.

    Format:
        [u32 count]
        For each message:
          [i64 tokens]
          [u64 hash]
        [i64 total_tokens]
        [i64 overhead_tokens]
    """
    import struct
    pos = 0

    count = struct.unpack_from('<I', data, pos)[0]
    pos += 4

    per_message_tokens = []
    message_hashes = []

    for _ in range(count):
        tokens = struct.unpack_from('<q', data, pos)[0]
        pos += 8  # i64
        hash_val = struct.unpack_from('<Q', data, pos)[0]
        pos += 8  # u64
        per_message_tokens.append(tokens)
        message_hashes.append(hash_val)

    total_tokens = struct.unpack_from('<q', data, pos)[0]
    pos += 8
    overhead = struct.unpack_from('<q', data, pos)[0]
    pos += 8

    return {
        'per_message_tokens': per_message_tokens,
        'total_message_tokens': total_tokens,
        'message_hashes': message_hashes,
        'context_overhead_tokens': overhead,
    }


def _safe_call_binary(lib: Any, fn: str, *args: Any) -> dict[str, Any]:
    """Call a binary FFI function and handle result unpacking."""
    import struct

    if lib is None:
        return {"success": False, "error": "Zig library not loaded"}

    fn_obj = getattr(lib, fn, None)
    if fn_obj is None:
        return {"success": False, "error": f"{fn} not found"}

    out_ptr = _ffi.new("uint8_t**")  # type: ignore[attr-defined]
    out_len = _ffi.new("size_t*")  # type: ignore[attr-defined]

    rc = fn_obj(*args, out_ptr, out_len)

    if rc != 0:
        return {"success": False, "error": f"Zig error: {rc}"}

    if out_ptr[0] == _ffi.NULL:  # type: ignore[attr-defined]
        return {"success": False, "error": "Zig returned null pointer"}

    try:
        # Copy bytes from Zig buffer
        buf_len = out_len[0]
        raw_bytes = bytes(_ffi.buffer(out_ptr[0], buf_len))  # type: ignore[attr-defined]
        result = _unpack_result_binary(raw_bytes)
        result["success"] = True

        # Free Zig memory
        lib.puppy_core_free_bytes(out_ptr[0], buf_len)
        return result
    except struct.error as e:
        lib.puppy_core_free_bytes(out_ptr[0], out_len[0])
        return {"success": False, "error": f"Failed to unpack result: {e}"}


# ── Public API ───────────────────────────────────────────────────────────────

def process_messages_batch_binary(messages: list[dict], system_prompt: str = "") -> dict[str, Any]:
    """Process messages using the binary protocol (faster than JSON for large batches).

    This avoids JSON serialization overhead by using a compact binary format
    for both input and output.
    """
    h = _get_puppy_core_handle()
    if h is None:
        return {"success": False, "error": "zig_puppy_core not available"}

    binary_data = _pack_messages_binary(messages)
    return _safe_call_binary(
        _lib_puppy_core,
        "puppy_core_process_messages_binary",
        h,
        binary_data,
        len(binary_data),
        system_prompt.encode('utf-8')
    )


__all__ = [
    "ZIG_AVAILABLE", "CFFI_AVAILABLE",
    "process_messages_batch", "process_messages_batch_binary", "prune_and_filter",
    "list_files", "grep", "parse_source", "is_language_supported",
]
