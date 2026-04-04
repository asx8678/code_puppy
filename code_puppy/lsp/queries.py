"""LSP query helpers.

High-level interface for common LSP operations like hover, symbols,
and document information with proper URI handling and result formatting.
"""

import logging
from pathlib import Path
from typing import Any

from code_puppy.lsp.client import LspClient
from code_puppy.lsp.manager import LspServerManager

logger = logging.getLogger(__name__)


class LspQueries:
    """Helper class for LSP queries.

    Provides convenient methods for common LSP operations with
    automatic file URI handling and result formatting.

    Example:
        queries = LspQueries(manager)
        hover_info = await queries.hover("src/main.py", line=10, character=15)
        symbols = await queries.document_symbols("src/main.py")
    """

    def __init__(self, manager: LspServerManager):
        """Initialize with a server manager.

        Args:
            manager: The LspServerManager instance to use.
        """
        self.manager = manager

    @staticmethod
    def _path_to_uri(file_path: str) -> str:
        """Convert file path to LSP URI.

        Args:
            file_path: File system path.

        Returns:
            LSP URI string (file://...).
        """
        abs_path = Path(file_path).resolve()
        return f"file://{abs_path}"

    @staticmethod
    def _uri_to_path(uri: str) -> str:
        """Convert LSP URI to file path.

        Args:
            uri: LSP URI string.

        Returns:
            File system path.
        """
        if uri.startswith("file://"):
            return uri[7:]
        return uri

    async def hover(
        self, file_path: str, line: int, character: int
    ) -> dict[str, Any] | None:
        """Get hover information at a position.

        Args:
            file_path: Path to the file.
            line: Zero-based line number.
            character: Zero-based character position.

        Returns:
            Hover information with contents and range, or None if unavailable.
        """
        client = await self.manager.get_client_for_file(file_path)
        if not client:
            return None

        try:
            uri = self._path_to_uri(file_path)
            result = await client.request(
                "textDocument/hover",
                {
                    "textDocument": {"uri": uri},
                    "position": {"line": line, "character": character},
                },
            )

            if not result:
                return None

            # Extract content from result
            contents = result.get("contents", "")
            if isinstance(contents, dict):
                # MarkupContent
                content = contents.get("value", "")
                kind = contents.get("kind", "plaintext")
            elif isinstance(contents, list) and contents:
                # MarkedString[] - use first item
                first = contents[0]
                if isinstance(first, dict):
                    content = first.get("value", "")
                    kind = first.get("language", "plaintext")
                else:
                    content = str(first)
                    kind = "plaintext"
            else:
                content = str(contents) if contents else ""
                kind = "plaintext"

            return {
                "content": content,
                "kind": kind,
                "range": result.get("range"),
            }

        except Exception as e:
            logger.debug(f"LSP hover query failed: {e}")
            return None

    async def document_symbols(self, file_path: str) -> list[dict[str, Any]]:
        """Get document symbols (outline).

        Args:
            file_path: Path to the file.

        Returns:
            List of symbols with name, kind, range, and children.
        """
        client = await self.manager.get_client_for_file(file_path)
        if not client:
            return []

        try:
            uri = self._path_to_uri(file_path)
            result = await client.request(
                "textDocument/documentSymbol",
                {"textDocument": {"uri": uri}},
            )

            if not result:
                return []

            # Handle both DocumentSymbol[] and SymbolInformation[]
            symbols = []
            for item in result:
                symbol = self._process_symbol(item)
                if symbol:
                    symbols.append(symbol)

            return symbols

        except Exception as e:
            logger.debug(f"LSP document symbols query failed: {e}")
            return []

    def _process_symbol(self, item: dict[str, Any]) -> dict[str, Any] | None:
        """Process a symbol item from LSP response.

        Args:
            item: Raw symbol item from server.

        Returns:
            Processed symbol dict or None.
        """
        if not item:
            return None

        # DocumentSymbol (hierarchical)
        if "selectionRange" in item:
            symbol = {
                "name": item.get("name", ""),
                "kind": self._symbol_kind_name(item.get("kind", 0)),
                "range": item.get("range", {}),
                "selection_range": item.get("selectionRange", {}),
                "detail": item.get("detail", ""),
            }

            # Process children recursively
            children = item.get("children", [])
            if children:
                symbol["children"] = [
                    self._process_symbol(child) for child in children
                ]

            return symbol

        # SymbolInformation (flat)
        return {
            "name": item.get("name", ""),
            "kind": self._symbol_kind_name(item.get("kind", 0)),
            "range": item.get("location", {}).get("range", {}),
            "container": item.get("containerName", ""),
        }

    @staticmethod
    def _symbol_kind_name(kind: int) -> str:
        """Convert symbol kind number to readable name.

        Args:
            kind: Symbol kind integer.

        Returns:
            Human-readable symbol kind name.
        """
        kinds = {
            1: "file",
            2: "module",
            3: "namespace",
            4: "package",
            5: "class",
            6: "method",
            7: "property",
            8: "field",
            9: "constructor",
            10: "enum",
            11: "interface",
            12: "function",
            13: "variable",
            14: "constant",
            15: "string",
            16: "number",
            17: "boolean",
            18: "array",
            19: "object",
            20: "key",
            21: "null",
            22: "enum_member",
            23: "struct",
            24: "event",
            25: "operator",
            26: "type_parameter",
        }
        return kinds.get(kind, f"unknown({kind})")

    async def definition(self, file_path: str, line: int, character: int) -> list[dict[str, Any]]:
        """Get definition locations for a symbol.

        Args:
            file_path: Path to the file.
            line: Zero-based line number.
            character: Zero-based character position.

        Returns:
            List of location dicts with uri and range.
        """
        client = await self.manager.get_client_for_file(file_path)
        if not client:
            return []

        try:
            uri = self._path_to_uri(file_path)
            result = await client.request(
                "textDocument/definition",
                {
                    "textDocument": {"uri": uri},
                    "position": {"line": line, "character": character},
                },
            )

            if not result:
                return []

            # Handle single result or array
            if isinstance(result, list):
                locations = result
            else:
                locations = [result]

            return [
                {
                    "uri": loc.get("uri", ""),
                    "path": self._uri_to_path(loc.get("uri", "")),
                    "range": loc.get("range", {}),
                }
                for loc in locations
            ]

        except Exception as e:
            logger.debug(f"LSP definition query failed: {e}")
            return []

    async def completion(
        self, file_path: str, line: int, character: int
    ) -> list[dict[str, Any]]:
        """Get completion items at a position.

        Args:
            file_path: Path to the file.
            line: Zero-based line number.
            character: Zero-based character position.

        Returns:
            List of completion items.
        """
        client = await self.manager.get_client_for_file(file_path)
        if not client:
            return []

        try:
            uri = self._path_to_uri(file_path)
            result = await client.request(
                "textDocument/completion",
                {
                    "textDocument": {"uri": uri},
                    "position": {"line": line, "character": character},
                },
            )

            if not result:
                return []

            # Handle CompletionList or CompletionItem[]
            if isinstance(result, dict) and "items" in result:
                items = result["items"]
            elif isinstance(result, list):
                items = result
            else:
                return []

            return [
                {
                    "label": item.get("label", ""),
                    "kind": item.get("kind", 0),
                    "detail": item.get("detail", ""),
                    "documentation": item.get("documentation", ""),
                    "insertText": item.get("insertText", ""),
                }
                for item in items
            ]

        except Exception as e:
            logger.debug(f"LSP completion query failed: {e}")
            return []
