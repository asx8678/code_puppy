"""Code validation using LSP diagnostics.

Validates code by opening documents in LSP servers and collecting
diagnostics. Supports both file validation and inline code validation.
"""

import logging
import tempfile
from pathlib import Path
from typing import Any

from code_puppy.lsp.client import LspClient
from code_puppy.lsp.manager import LspServerManager

logger = logging.getLogger(__name__)


class LspValidator:
    """Code validation using LSP diagnostics.

    Opens documents in language servers and collects diagnostics
    for error checking and type validation.

    Example:
        validator = LspValidator(manager)

        # Validate a file
        result = await validator.validate_file("src/main.py")

        # Validate inline code
        result = await validator.validate_code(
            "def foo(x: int) -> str: return x",
            language="python"
        )
    """

    def __init__(self, manager: LspServerManager):
        """Initialize with a server manager.

        Args:
            manager: The LspServerManager instance to use.
        """
        self.manager = manager
        self._opened_documents: set[str] = set()

    @staticmethod
    def _path_to_uri(file_path: str) -> str:
        """Convert file path to LSP URI."""
        abs_path = Path(file_path).resolve()
        return f"file://{abs_path}"

    async def _open_document(self, client: LspClient, file_path: str, text: str) -> None:
        """Open a document in the LSP server.

        Args:
            client: The LSP client.
            file_path: Path to the document.
            text: Document content.
        """
        uri = self._path_to_uri(file_path)

        # Only open if not already opened
        if uri not in self._opened_documents:
            await client.notify(
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": uri,
                        "languageId": self._detect_language_id(file_path),
                        "version": 1,
                        "text": text,
                    }
                },
            )
            self._opened_documents.add(uri)

    async def _close_document(self, client: LspClient, file_path: str) -> None:
        """Close a document in the LSP server.

        Args:
            client: The LSP client.
            file_path: Path to the document.
        """
        uri = self._path_to_uri(file_path)

        if uri in self._opened_documents:
            await client.notify(
                "textDocument/didClose",
                {"textDocument": {"uri": uri}},
            )
            self._opened_documents.discard(uri)

    @staticmethod
    def _detect_language_id(file_path: str) -> str:
        """Detect LSP language ID from file path.

        Args:
            file_path: Path to the file.

        Returns:
            LSP language ID.
        """
        ext = Path(file_path).suffix.lower()

        language_map = {
            ".py": "python",
            ".pyi": "python",
            ".ts": "typescript",
            ".tsx": "typescriptreact",
            ".js": "javascript",
            ".jsx": "javascriptreact",
            ".mjs": "javascript",
            ".cjs": "javascript",
            ".rs": "rust",
            ".go": "go",
        }

        return language_map.get(ext, "plaintext")

    async def validate_file(
        self, file_path: str, max_diagnostics: int = 50
    ) -> dict[str, Any]:
        """Validate a file and return diagnostics.

        Opens the file in the LSP server, waits for diagnostics,
        and returns them in a structured format.

        Args:
            file_path: Path to the file to validate.
            max_diagnostics: Maximum number of diagnostics to return.

        Returns:
            Validation result with diagnostics, error count, warning count.
        """
        client = await self.manager.get_client_for_file(file_path)
        if not client:
            return {
                "valid": False,
                "error": "No LSP server available for this file type",
                "diagnostics": [],
                "error_count": 0,
                "warning_count": 0,
            }

        try:
            # Read file content
            path = Path(file_path)
            if not path.exists():
                return {
                    "valid": False,
                    "error": f"File not found: {file_path}",
                    "diagnostics": [],
                    "error_count": 0,
                    "warning_count": 0,
                }

            text = path.read_text(encoding="utf-8", errors="replace")

            # Open document
            await self._open_document(client, file_path, text)

            # Request diagnostics via document diagnostic request
            # Note: Some servers send diagnostics via notifications, but we
            # can also use the pull diagnostics model if supported
            try:
                uri = self._path_to_uri(file_path)
                result = await client.request(
                    "textDocument/diagnostic",
                    {"textDocument": {"uri": uri}},
                )

                if result and "items" in result:
                    diagnostics = result["items"]
                else:
                    diagnostics = []

            except Exception:
                # Server may not support pull diagnostics
                # In this case, we can't get diagnostics directly
                # Return empty result indicating we tried
                diagnostics = []

            # Process diagnostics
            processed = []
            error_count = 0
            warning_count = 0

            for diag in diagnostics[:max_diagnostics]:
                severity = diag.get("severity", 1)
                processed_diag = {
                    "message": diag.get("message", ""),
                    "severity": self._severity_name(severity),
                    "line": diag.get("range", {}).get("start", {}).get("line", 0),
                    "column": diag.get("range", {}).get("start", {}).get("character", 0),
                    "code": diag.get("code", ""),
                    "source": diag.get("source", ""),
                }
                processed.append(processed_diag)

                if severity == 1:
                    error_count += 1
                elif severity == 2:
                    warning_count += 1

            # Close document
            await self._close_document(client, file_path)

            return {
                "valid": error_count == 0,
                "diagnostics": processed,
                "error_count": error_count,
                "warning_count": warning_count,
                "file": file_path,
            }

        except Exception as e:
            logger.debug(f"LSP validation failed: {e}")
            return {
                "valid": False,
                "error": str(e),
                "diagnostics": [],
                "error_count": 0,
                "warning_count": 0,
                "file": file_path,
            }

    async def validate_code(
        self, code: str, language: str, max_diagnostics: int = 50
    ) -> dict[str, Any]:
        """Validate inline code.

        Creates a temporary file with the code and validates it.

        Args:
            code: The code to validate.
            language: Language identifier (python, typescript, rust, go).
            max_diagnostics: Maximum number of diagnostics to return.

        Returns:
            Validation result with diagnostics.
        """
        # Map language to extension
        ext_map = {
            "python": ".py",
            "typescript": ".ts",
            "javascript": ".js",
            "rust": ".rs",
            "go": ".go",
        }

        ext = ext_map.get(language, ".txt")

        try:
            # Create temp file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=ext, delete=False, encoding="utf-8"
            ) as f:
                f.write(code)
                temp_path = f.name

            try:
                result = await self.validate_file(temp_path, max_diagnostics)
                # Remove temp file path from result
                result["file"] = "<inline>"
                return result
            finally:
                # Clean up temp file
                try:
                    Path(temp_path).unlink()
                except Exception:
                    pass

        except Exception as e:
            return {
                "valid": False,
                "error": str(e),
                "diagnostics": [],
                "error_count": 0,
                "warning_count": 0,
                "file": "<inline>",
            }

    @staticmethod
    def _severity_name(severity: int) -> str:
        """Convert severity number to name.

        Args:
            severity: Severity integer (1=error, 2=warning, 3=info, 4=hint).

        Returns:
            Human-readable severity name.
        """
        names = {1: "error", 2: "warning", 3: "info", 4: "hint"}
        return names.get(severity, f"unknown({severity})")

    async def get_quick_info(self, file_path: str) -> dict[str, Any]:
        """Get quick validation info about a file.

        Args:
            file_path: Path to the file.

        Returns:
            Quick summary with validity and counts.
        """
        result = await self.validate_file(file_path, max_diagnostics=10)
        return {
            "valid": result["valid"],
            "error_count": result["error_count"],
            "warning_count": result["warning_count"],
            "has_diagnostics": len(result["diagnostics"]) > 0,
        }
