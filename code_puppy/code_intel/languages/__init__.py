"""Language-specific extractors for Tree-sitter AST parsing.

Supports: Python, JavaScript/TypeScript, Rust, Go
"""

from typing import Optional

from .python_extractor import PythonExtractor
from .javascript_extractor import JavaScriptExtractor
from .typescript_extractor import TypeScriptExtractor
from .rust_extractor import RustExtractor
from .go_extractor import GoExtractor

# Registry of extractors
_EXTRACTORS: dict[str, object] = {}


def get_extractor(language_name: str) -> Optional[object]:
    """Get the extractor for a language.

    Args:
        language_name: One of "python", "javascript", "typescript", "rust", "go".

    Returns:
        Extractor instance or None if not available.
    """
    if language_name in _EXTRACTORS:
        return _EXTRACTORS[language_name]

    extractor = None
    if language_name == "python":
        extractor = PythonExtractor()
    elif language_name == "javascript":
        extractor = JavaScriptExtractor()
    elif language_name == "typescript":
        extractor = TypeScriptExtractor()
    elif language_name == "rust":
        extractor = RustExtractor()
    elif language_name == "go":
        extractor = GoExtractor()

    if extractor:
        _EXTRACTORS[language_name] = extractor

    return extractor


__all__ = [
    "get_extractor",
    "PythonExtractor",
    "JavaScriptExtractor",
    "TypeScriptExtractor",
    "RustExtractor",
    "GoExtractor",
]
