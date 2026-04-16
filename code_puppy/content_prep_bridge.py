"""Bridge for Rust-accelerated content preparation.

Routes prepare_content() and format_line_numbers() through Rust 
when code_puppy_core is available, falling back to Python.
"""

from __future__ import annotations

import codecs
from typing import Any

try:
    from _code_puppy_core import prepare_content as _rust_prepare_content
    from _code_puppy_core import format_line_numbers as _rust_format_line_numbers

    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False


# UTF-8 BOM bytes: EF BB BF
_UTF8_BOM_BYTES = b"\xef\xbb\xbf"
_UTF8_BOM_CHAR = "\ufeff"


def _looks_textish(raw: bytes) -> bool:
    """Detect if bytes appear to be text (matches Rust behavior).
    
    Criteria:
    1. No NUL bytes anywhere
    2. At least 90% of bytes are >=0x20 or common whitespace (\t, \n, \r)
    
    Empty content is considered text.
    """
    if not raw:
        return True

    # Check for NUL bytes
    if b"\x00" in raw:
        return False

    # Count printable bytes
    total = len(raw)
    printable = sum(1 for b in raw if b >= 0x20 or b in (0x09, 0x0A, 0x0D))

    return (printable / total) >= 0.90


def _detect_encoding(raw: bytes) -> str:
    """Detect text encoding from raw bytes.
    
    Returns:
        str: Detected encoding name (e.g., "utf-8", "utf-8-sig", "latin-1")
    """
    if not raw:
        return "utf-8"
    
    # Check for UTF-8 BOM
    if raw.startswith(_UTF8_BOM_BYTES):
        return "utf-8-sig"
    
    # Try UTF-8 strict decode
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    
    # Try UTF-16 BOM patterns
    if raw.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if raw.startswith(b"\xfe\xff"):
        return "utf-16-be"
    
    # Fall back to latin-1 (decodes any byte sequence)
    return "latin-1"


def _python_prepare_content(raw: bytes) -> dict[str, Any]:
    """Python fallback for prepare_content.
    
    Replicates Rust behavior:
    - Strips UTF-8 BOM if present
    - Detects binary vs text (NUL bytes, printable ratio)
    - Normalizes CRLF to LF for TEXT content only
    - Binary content passes through without EOL normalization
    - Tracks had_bom and had_crlf flags
    
    Returns dict with keys:
        - text: str — cleaned text content
        - is_binary: bool — True if binary detected
        - had_bom: bool — True if UTF-8 BOM was present
        - had_crlf: bool — True if CRLF sequences detected
        - encoding: str — detected encoding
    """
    # Handle empty input
    if not raw:
        return {
            "text": "",
            "is_binary": False,
            "had_bom": False,
            "had_crlf": False,
            "encoding": "utf-8",
        }

    # Strip BOM first (if present)
    had_bom = raw.startswith(_UTF8_BOM_BYTES)
    content_bytes = raw[len(_UTF8_BOM_BYTES):] if had_bom else raw
    
    # Detect encoding
    encoding = _detect_encoding(raw)
    
    # Check for NUL bytes (binary detection)
    has_nul = b"\x00" in content_bytes
    
    # Check for CRLF sequences
    has_crlf = b"\r\n" in content_bytes
    
    # Decode content (use lossy UTF-8 for binary or decode with detected encoding)
    if has_nul or not _looks_textish(content_bytes):
        # Binary - use lossy UTF-8 conversion (matches Rust String::from_utf8_lossy)
        # IMPORTANT: Binary content does NOT get EOL normalized - passes through as-is
        text = content_bytes.decode("utf-8", errors="replace")
        return {
            "text": text,
            "is_binary": True,
            "had_bom": had_bom,
            "had_crlf": has_crlf,
            "encoding": encoding,
        }
    
    # It's text - decode and normalize EOLs
    if encoding == "utf-8-sig":
        # BOM already stripped, decode as UTF-8
        text = content_bytes.decode("utf-8", errors="replace")
    elif encoding == "utf-8":
        text = content_bytes.decode("utf-8", errors="replace")
    else:
        # Other encodings - decode then re-encode to ensure valid UTF-8 str
        text = content_bytes.decode(encoding, errors="replace")
    
    # Normalize line endings: CRLF -> LF, then orphan CR -> LF
    # ONLY for text content - binary content skips this
    if "\r" in text:
        text = text.replace("\r\n", "\n")
        text = text.replace("\r", "\n")
    
    return {
        "text": text,
        "is_binary": False,
        "had_bom": had_bom,
        "had_crlf": has_crlf,
        "encoding": encoding,
    }


def _python_format_line_numbers(
    content: str,
    start_line: int = 1,
    max_line_length: int = 5000,
    line_number_width: int = 6,
) -> str:
    """Python fallback for format_line_numbers.
    
    Formats content with line numbers (cat -n style).
    For lines exceeding max_line_length, splits into chunks with
    continuation markers (e.g., "5.1", "5.2", "5.3").
    
    Uses CHARACTER-based length matching (not bytes) to match
    Python's len() behavior and the Rust implementation.
    """
    if not content:
        return f"{start_line:{line_number_width}d}\t"
    
    lines = content.split("\n")
    result_lines = []

    for i, line in enumerate(lines):
        line_num = start_line + i
        # CHARACTER-BASED length (not bytes) to match Python's len(line)
        char_len = len(line)

        if char_len <= max_line_length:
            result_lines.append(f"{line_num:{line_number_width}d}\t{line}")
        else:
            # Long line: split into chunks with continuation markers
            num_chunks = (char_len + max_line_length - 1) // max_line_length

            for chunk_idx in range(num_chunks):
                start = chunk_idx * max_line_length
                end = min(start + max_line_length, char_len)
                chunk = line[start:end]

                if chunk_idx == 0:
                    # First chunk: regular line number format
                    result_lines.append(f"{line_num:{line_number_width}d}\t{chunk}")
                else:
                    # Continuation chunk: use marker like "5.1", "5.2"
                    continuation_marker = f"{line_num}.{chunk_idx}"
                    result_lines.append(
                        f"{continuation_marker:>{line_number_width}}\t{chunk}"
                    )

    return "\n".join(result_lines)


def prepare_content(raw: bytes) -> dict[str, Any]:
    """Prepare raw file bytes for display.
    
    Routes to Rust implementation when available, otherwise uses
    Python fallback that replicates Rust behavior.
    
    Returns dict with keys:
        - text: str — cleaned text (BOM stripped, CRLF normalized for text)
        - is_binary: bool — True if content appears to be binary
        - had_bom: bool — True if UTF-8 BOM was present
        - had_crlf: bool — True if CRLF line endings were detected
        - encoding: str — detected encoding
    
    Args:
        raw: Raw file bytes
        
    Returns:
        dict: Prepared content info
    """
    if RUST_AVAILABLE:
        result = _rust_prepare_content(raw)
        return {
            "text": result.content,
            "is_binary": not result.is_text,
            "had_bom": result.had_bom,
            "had_crlf": result.had_crlf,
            "encoding": "utf-8-sig" if result.had_bom else "utf-8",
        }
    
    return _python_prepare_content(raw)


def format_line_numbers(
    content: str,
    start_line: int = 1,
    max_line_length: int = 5000,
    line_number_width: int = 6,
) -> str:
    """Format content with line numbers (cat -n style).
    
    Routes to Rust implementation when available, otherwise uses
    Python fallback.
    
    For lines exceeding max_line_length (character count, not bytes),
    splits into chunks with continuation markers (e.g., "5.1", "5.2", "5.3").
    
    Uses CHARACTER-based length matching to match Python's len() behavior.
    
    Args:
        content: Content to format (lines separated by \n)
        start_line: Starting line number (1-based, default 1)
        max_line_length: Maximum character count before splitting (default 5000)
        line_number_width: Width for line number column (default 6)
        
    Returns:
        Formatted content with line numbers and continuation markers
        
    Example:
        >>> format_line_numbers("hello\\nworld", 1)
        '     1\\thello\\n     2\\tworld'
    """
    if RUST_AVAILABLE:
        return _rust_format_line_numbers(content, start_line, max_line_length, line_number_width)
    
    return _python_format_line_numbers(content, start_line, max_line_length, line_number_width)
