"""Zig cffi bridge - direct bindings to Zig shared libraries.

Exposes: ZIG_AVAILABLE, process_messages_batch(), prune_and_filter(),
parse_source(), list_files(), grep(), is_language_supported()
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
        typedef enum { success=0, invalid_argument=-1, out_of_memory=-2 } PuppyCoreError;
        PuppyCoreHandle puppy_core_create(void);
        void puppy_core_destroy(PuppyCoreHandle handle);
        PuppyCoreError puppy_core_process_messages(PuppyCoreHandle h, const char* msgs,
            const char* sys, char** out);
        void puppy_core_free_string(char* ptr);

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
        output = _zig_str_to_py(out[0], getattr(lib, free))
        try:
            return {"success": True, "data": json.loads(output)}
        except json.JSONDecodeError:
            return {"success": True, "raw": output}
    return {"success": True, "result": fn_obj(*args)}


# ── Public API ───────────────────────────────────────────────────────────────
def process_messages_batch(messages: list[dict], system_prompt: str = "") -> dict[str, Any]:
    if _lib_puppy_core is None:
        return {"success": False, "error": "zig_puppy_core not available"}
    h = _lib_puppy_core.puppy_core_create()
    if h is None:
        return {"success": False, "error": "Failed to create handle"}
    try:
        return _safe_call(_lib_puppy_core, "puppy_core_process_messages",
            h, json.dumps(messages).encode(), system_prompt.encode(),
            free="puppy_core_free_string")
    finally:
        _lib_puppy_core.puppy_core_destroy(h)


def prune_and_filter(messages: list[dict], max_tokens: int = 50000) -> dict[str, Any]:
    # TODO: Implement once Zig side is complete
    return {"success": False, "error": "Not yet implemented in Zig"}


def list_files(directory: str = ".", recursive: bool = True) -> dict[str, Any]:
    if _lib_turbo_ops is None:
        return {"success": False, "error": "zig_turbo_ops not available"}
    h = _lib_turbo_ops.turbo_ops_create(1)
    if h is None:
        return {"success": False, "error": "Failed to create handle"}
    try:
        return _safe_call(_lib_turbo_ops, "turbo_ops_list_files",
            h, directory.encode(), 1 if recursive else 0, free="turbo_ops_free_string")
    finally:
        _lib_turbo_ops.turbo_ops_destroy(h)


def grep(pattern: str, directory: str = ".") -> dict[str, Any]:
    if _lib_turbo_ops is None:
        return {"success": False, "error": "zig_turbo_ops not available"}
    h = _lib_turbo_ops.turbo_ops_create(1)
    if h is None:
        return {"success": False, "error": "Failed to create handle"}
    try:
        return _safe_call(_lib_turbo_ops, "turbo_ops_grep",
            h, pattern.encode(), directory.encode(), free="turbo_ops_free_string")
    finally:
        _lib_turbo_ops.turbo_ops_destroy(h)


def parse_source(source: str, language: str) -> dict[str, Any]:
    if _lib_turbo_parse is None:
        return {"success": False, "error": "zig_turbo_parse not available"}
    h = _lib_turbo_parse.turbo_parse_create()
    if h is None:
        return {"success": False, "error": "Failed to create handle"}
    try:
        return _safe_call(_lib_turbo_parse, "turbo_parse_source",
            h, source.encode(), language.encode(), free="turbo_parse_free_string")
    finally:
        _lib_turbo_parse.turbo_parse_destroy(h)


def is_language_supported(language: str) -> bool:
    if _lib_turbo_parse is None:
        return False
    return bool(_lib_turbo_parse.turbo_parse_is_language_supported(language.encode()))


__all__ = [
    "ZIG_AVAILABLE", "CFFI_AVAILABLE",
    "process_messages_batch", "prune_and_filter",
    "list_files", "grep", "parse_source", "is_language_supported",
]
