"""Symbol graph data structure for code intelligence.

Represents code as a graph of symbols (functions, classes, variables, etc.)
and their relationships (calls, inheritance, imports).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SymbolKind(Enum):
    """Enumeration of symbol types."""

    FUNCTION = auto()
    METHOD = auto()
    CLASS = auto()
    VARIABLE = auto()
    CONSTANT = auto()
    IMPORT = auto()
    MODULE = auto()
    TYPE_ALIAS = auto()
    INTERFACE = auto()
    STRUCT = auto()
    TRAIT = auto()
    ENUM = auto()


@dataclass
class Location:
    """Source code location."""

    file_path: str
    line: int  # 0-indexed
    column: int  # 0-indexed
    end_line: int = 0
    end_column: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "file_path": self.file_path,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }


@dataclass
class Symbol:
    """Represents a code symbol (function, class, etc.)."""

    name: str
    kind: SymbolKind
    location: Location
    signature: str = ""  # Function signature, class inheritance, etc.
    docstring: str = ""
    parent: Optional[str] = None  # Parent symbol name (e.g., class for method)
    children: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "name": self.name,
            "kind": self.kind.name,
            "location": self.location.to_dict(),
            "signature": self.signature,
            "docstring": self.docstring,
            "parent": self.parent,
            "children": self.children.copy(),
            "metadata": self.metadata.copy(),
        }


@dataclass
class Reference:
    """Represents a reference from one symbol to another."""

    source: str  # Symbol name that makes the reference
    target: str  # Symbol name being referenced
    kind: str  # "call", "import", "inheritance", "type_ref", etc.
    location: Location

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "source": self.source,
            "target": self.target,
            "kind": self.kind,
            "location": self.location.to_dict(),
        }


class SymbolGraph:
    """Graph of symbols and their relationships.

    Maintains:
    - symbols: Dict mapping symbol IDs to Symbol objects
    - references: List of Reference objects
    - file_index: Mapping from file paths to symbol names in that file

    Example:
        graph = SymbolGraph()
        graph.add_symbol(Symbol(
            name="my_function",
            kind=SymbolKind.FUNCTION,
            location=Location("/path/file.py", 10, 4),
        ))
    """

    def __init__(self):
        """Initialize an empty symbol graph."""
        self._symbols: dict[str, Symbol] = {}
        self._references: list[Reference] = []
        self._file_index: dict[str, set[str]] = {}  # file_path -> set of symbol names
        self._name_index: dict[str, set[str]] = {}  # symbol name -> set of symbol keys

    def _make_symbol_key(self, name: str, file_path: str, line: int) -> str:
        """Create unique key for a symbol."""
        return f"{file_path}:{line}:{name}"

    def add_symbol(self, symbol: Symbol) -> str:
        """Add a symbol to the graph.

        Args:
            symbol: The symbol to add.

        Returns:
            The unique key for the symbol.
        """
        key = self._make_symbol_key(
            symbol.name, symbol.location.file_path, symbol.location.line
        )
        self._symbols[key] = symbol

        # Update file index
        file_path = symbol.location.file_path
        if file_path not in self._file_index:
            self._file_index[file_path] = set()
        self._file_index[file_path].add(key)

        # Update name index
        if symbol.name not in self._name_index:
            self._name_index[symbol.name] = set()
        self._name_index[symbol.name].add(key)

        logger.debug(f"Added symbol: {key}")
        return key

    def add_reference(self, reference: Reference) -> None:
        """Add a reference to the graph.

        Args:
            reference: The reference to add.
        """
        self._references.append(reference)
        logger.debug(
            f"Added reference: {reference.source} -> {reference.target} ({reference.kind})"
        )

    def remove_file(self, file_path: str) -> int:
        """Remove all symbols from a file.

        Args:
            file_path: Path to the file.

        Returns:
            Number of symbols removed.
        """
        resolved_path = str(Path(file_path).resolve())
        keys_to_remove = self._file_index.get(resolved_path, set()).copy()

        count = 0
        for key in keys_to_remove:
            if key in self._symbols:
                symbol = self._symbols[key]

                # Remove from name index
                if symbol.name in self._name_index:
                    self._name_index[symbol.name].discard(key)
                    if not self._name_index[symbol.name]:
                        del self._name_index[symbol.name]

                # Remove from symbols
                del self._symbols[key]
                count += 1

        # Remove from file index
        if resolved_path in self._file_index:
            del self._file_index[resolved_path]

        # Remove references from/to removed symbols
        symbol_names = {self._symbols.get(k, Symbol("", SymbolKind.VARIABLE, Location("", 0, 0))).name for k in keys_to_remove if k in self._symbols}
        self._references = [
            ref for ref in self._references
            if ref.source not in symbol_names and ref.target not in symbol_names
        ]

        logger.debug(f"Removed {count} symbols from {resolved_path}")
        return count

    def get_symbol(self, name: str, file_path: Optional[str] = None) -> Optional[Symbol]:
        """Get a symbol by name.

        Args:
            name: Symbol name to search for.
            file_path: Optional file path to narrow search.

        Returns:
            The symbol if found, None otherwise.
        """
        keys = self._name_index.get(name, set())
        if not keys:
            return None

        if file_path:
            resolved = str(Path(file_path).resolve())
            for key in keys:
                if key.startswith(resolved + ":"):
                    return self._symbols.get(key)
            return None

        # Return first match if no file path specified
        return self._symbols.get(next(iter(keys)))

    def get_symbols_in_file(self, file_path: str) -> list[Symbol]:
        """Get all symbols defined in a file.

        Args:
            file_path: Path to the file.

        Returns:
            List of symbols in the file.
        """
        resolved_path = str(Path(file_path).resolve())
        keys = self._file_index.get(resolved_path, set())
        return [self._symbols[k] for k in keys if k in self._symbols]

    def find_references_to(self, symbol_name: str) -> list[Reference]:
        """Find all references to a symbol.

        Args:
            symbol_name: Name of the symbol to find references to.

        Returns:
            List of references targeting the symbol.
        """
        return [ref for ref in self._references if ref.target == symbol_name]

    def find_references_from(self, symbol_name: str) -> list[Reference]:
        """Find all references from a symbol.

        Args:
            symbol_name: Name of the symbol to find references from.

        Returns:
            List of references originating from the symbol.
        """
        return [ref for ref in self._references if ref.source == symbol_name]

    def search_symbols(self, pattern: str) -> list[Symbol]:
        """Search for symbols by name pattern (case-insensitive substring).

        Args:
            pattern: Substring to search for.

        Returns:
            List of matching symbols.
        """
        pattern_lower = pattern.lower()
        results = []
        for symbol in self._symbols.values():
            if pattern_lower in symbol.name.lower():
                results.append(symbol)
        return results

    def get_all_symbols(self) -> list[Symbol]:
        """Get all symbols in the graph.

        Returns:
            List of all symbols.
        """
        return list(self._symbols.values())

    def clear(self) -> None:
        """Clear all symbols and references."""
        self._symbols.clear()
        self._references.clear()
        self._file_index.clear()
        self._name_index.clear()
        logger.debug("Cleared symbol graph")

    def get_stats(self) -> dict:
        """Get statistics about the graph.

        Returns:
            Dict with symbol count, reference count, file count.
        """
        return {
            "symbol_count": len(self._symbols),
            "reference_count": len(self._references),
            "file_count": len(self._file_index),
        }

    def to_dict(self) -> dict:
        """Convert the entire graph to a dictionary.

        Returns:
            Dict representation of the graph.
        """
        return {
            "symbols": {k: v.to_dict() for k, v in self._symbols.items()},
            "references": [ref.to_dict() for ref in self._references],
            "stats": self.get_stats(),
        }
