"""Base class for language-specific extractors.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tree_sitter import Tree

    from ..symbol_graph import SymbolGraph


class BaseExtractor(ABC):
    """Base class for language-specific AST extractors.

    Subclasses must implement the extract() method to populate a SymbolGraph
    from a Tree-sitter AST.
    """

    @abstractmethod
    def extract(
        self,
        tree: "Tree",
        source: str | bytes,
        file_path: str,
        graph: "SymbolGraph",
    ) -> int:
        """Extract symbols from an AST and add to the graph.

        Args:
            tree: Tree-sitter Tree object.
            source: Original source code.
            file_path: Path to the source file.
            graph: SymbolGraph to populate.

        Returns:
            Number of symbols extracted.
        """
        raise NotImplementedError

    def _get_node_text(self, node, source: str | bytes) -> str:
        """Get the text content of a node.

        Args:
            node: Tree-sitter node.
            source: Source code.

        Returns:
            Text content of the node.
        """
        if isinstance(source, bytes):
            return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
        return source[node.start_byte : node.end_byte]

    def _get_location(self, node, file_path: str) -> "Location":
        """Create a Location from a tree-sitter node.

        Args:
            node: Tree-sitter node.
            file_path: Path to the file.

        Returns:
            Location object.
        """
        from ..symbol_graph import Location

        return Location(
            file_path=file_path,
            line=node.start_point.row,
            column=node.start_point.column,
            end_line=node.end_point.row,
            end_column=node.end_point.column,
        )
