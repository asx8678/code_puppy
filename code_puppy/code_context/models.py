"""Code Context Models — Data classes for symbol and code context representation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class SymbolInfo:
    """Information about a code symbol (function, class, method, etc.)."""

    name: str
    kind: str
    start_line: int
    end_line: int
    start_col: int = 0
    end_col: int = 0
    parent: Optional[str] = None
    docstring: Optional[str] = None
    children: List[SymbolInfo] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SymbolInfo:
        """Create SymbolInfo from a dictionary."""
        return cls(
            name=data.get("name", ""),
            kind=data.get("kind", "unknown"),
            start_line=data.get("start_line", 0),
            end_line=data.get("end_line", 0),
            start_col=data.get("start_col", 0),
            end_col=data.get("end_col", 0),
            parent=data.get("parent"),
            docstring=data.get("docstring"),
            children=[],
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert SymbolInfo to a dictionary."""
        return {
            "name": self.name,
            "kind": self.kind,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "start_col": self.start_col,
            "end_col": self.end_col,
            "parent": self.parent,
            "docstring": self.docstring,
            "children": [c.to_dict() for c in self.children],
        }

    @property
    def line_range(self) -> tuple[int, int]:
        """Get the line range as a tuple."""
        return (self.start_line, self.end_line)

    @property
    def is_top_level(self) -> bool:
        """Check if this is a top-level symbol (no parent)."""
        return self.parent is None

    @property
    def size_lines(self) -> int:
        """Get the size of the symbol in lines."""
        return self.end_line - self.start_line + 1


@dataclass
class FileOutline:
    """Hierarchical outline of a source file."""

    language: str
    symbols: List[SymbolInfo]
    extraction_time_ms: float = 0.0
    success: bool = True
    errors: List[str] = field(default_factory=list)

    @property
    def top_level_symbols(self) -> List[SymbolInfo]:
        """Get only top-level symbols."""
        return [s for s in self.symbols if s.is_top_level]

    @property
    def classes(self) -> List[SymbolInfo]:
        """Get all class-like symbols."""
        return [
            s
            for s in self.symbols
            if s.kind in ("class", "struct", "interface", "trait", "enum")
        ]

    @property
    def functions(self) -> List[SymbolInfo]:
        """Get all function-like symbols."""
        return [s for s in self.symbols if s.kind in ("function", "method")]

    @property
    def imports(self) -> List[SymbolInfo]:
        """Get all import symbols."""
        return [s for s in self.symbols if s.kind == "import"]

    def get_symbol_by_name(self, name: str) -> Optional[SymbolInfo]:
        """Find a symbol by its name."""
        for symbol in self.symbols:
            if symbol.name == name:
                return symbol
        return None

    def get_symbols_in_range(self, start_line: int, end_line: int) -> List[SymbolInfo]:
        """Get all symbols within a line range."""
        return [
            s
            for s in self.symbols
            if s.start_line >= start_line and s.end_line <= end_line
        ]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "language": self.language,
            "symbols": [s.to_dict() for s in self.symbols],
            "extraction_time_ms": self.extraction_time_ms,
            "success": self.success,
            "errors": self.errors,
        }


@dataclass
class CodeContext:
    """Complete context for a code file including symbols, content, and metadata."""

    file_path: str
    content: Optional[str] = None
    language: Optional[str] = None
    outline: Optional[FileOutline] = None
    file_size: int = 0
    num_lines: int = 0
    num_tokens: int = 0
    parse_time_ms: float = 0.0
    has_errors: bool = False
    error_message: Optional[str] = None

    @property
    def is_parsed(self) -> bool:
        """Check if the file was successfully parsed."""
        return self.outline is not None and self.outline.success

    @property
    def symbol_count(self) -> int:
        """Get the total number of symbols."""
        return len(self.outline.symbols) if self.outline else 0

    def get_summary(self) -> str:
        """Get a human-readable summary of the code context."""
        lines = [
            f"📄 {self.file_path}",
            f"   Language: {self.language or 'unknown'}",
            f"   Lines: {self.num_lines}, Tokens: {self.num_tokens}",
        ]

        if self.outline:
            lines.append(f"   Symbols: {len(self.outline.symbols)}")
            if self.outline.classes:
                lines.append(f"   Classes: {len(self.outline.classes)}")
            if self.outline.functions:
                lines.append(f"   Functions: {len(self.outline.functions)}")

        if self.has_errors and self.error_message:
            lines.append(f"   ⚠️ Error: {self.error_message}")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "file_path": self.file_path,
            "content": self.content,
            "language": self.language,
            "outline": self.outline.to_dict() if self.outline else None,
            "file_size": self.file_size,
            "num_lines": self.num_lines,
            "num_tokens": self.num_tokens,
            "parse_time_ms": self.parse_time_ms,
            "has_errors": self.has_errors,
            "error_message": self.error_message,
        }
