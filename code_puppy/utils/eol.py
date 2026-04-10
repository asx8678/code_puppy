"""End-of-line normalization with binary-file detection.

Ported from plandex's ``shared/utils.go`` ``NormalizeEOL`` + ``looksTextish``
heuristic.  Applies CRLF → LF conversion **only** when the input looks like
a text file, preventing corruption of binary content that happens to contain
``\\r\\n`` byte sequences.

The heuristic is intentionally conservative:
  1. No NUL (``\x00``) bytes anywhere — NUL is the strongest binary signal.
  2. Valid UTF-8 decode (Python ``str`` already guarantees this when content
     was read with ``errors="replace"`` or ``errors="surrogatepass"``).
  3. At least 90 % of characters are printable (letters, digits, punctuation,
     whitespace).  This catches raw binary that survived UTF-8 decoding.

If any check fails the content is returned unchanged.
"""

from __future__ import annotations

__all__ = ["normalize_eol", "looks_textish"]


def looks_textish(content: str) -> bool:
    """Return True if *content* looks like human-readable text.

    The check is designed to be fast on typical source files (early-exit on
    NUL) and reasonably accurate on binary blobs.

    Args:
        content: The string to inspect.  An empty string is considered text.

    Returns:
        ``True`` when the content is likely text, ``False`` when it appears
        to be binary.
    """
    if not content:
        return True  # empty is text

    # 1. NUL byte → binary
    if "\x00" in content:
        return False

    # 2. Printable-ratio check.  We count characters that are NOT control
    #    characters (categories Cc/Cf minus common whitespace).
    #    Common whitespace (\t, \n, \r, space) is treated as printable.
    total = len(content)
    printable = 0
    for ch in content:
        cp = ord(ch)
        if cp >= 0x20:
            # 0x20 (space) and above — most are printable.
            # 0x7F (DEL) and 0x80-0x9F (C1 controls) are the main exceptions
            # but they're rare enough in real text that a 90% threshold
            # handles them fine.
            printable += 1
        elif ch in "\t\n\r":
            printable += 1
        # else: raw control character, counts against printable ratio

    ratio = printable / total
    return ratio >= 0.90


def normalize_eol(content: str) -> str:
    r"""Normalize line endings to ``\n`` if the content looks like text.

    Applies CRLF (``\r\n``) → LF (``\n``) conversion and strips orphan CRs
    (``\r`` not followed by ``\n``).  Binary-looking content is returned
    unchanged — see :func:`looks_textish` for the detection heuristic.

    Args:
        content: File content to normalize.

    Returns:
        The content with consistent ``\n`` line endings, or the original
        content unchanged if it looks binary.
    """
    if not content:
        return content

    if not looks_textish(content):
        return content

    # CRLF → LF first, then orphan CR → LF
    result = content.replace("\r\n", "\n")
    result = result.replace("\r", "\n")
    return result
