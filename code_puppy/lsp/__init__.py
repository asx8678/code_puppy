"""LSP (Language Server Protocol) integration for code_puppy.

Provides headless LSP client functionality for type-aware code generation
and validation. Supports pyright, typescript-language-server, rust-analyzer,
and gopls with lazy startup and connection pooling.
"""

from code_puppy.lsp.client import LspClient
from code_puppy.lsp.manager import LspServerManager, get_server_manager
from code_puppy.lsp.queries import LspQueries
from code_puppy.lsp.validator import LspValidator

__all__ = [
    "LspClient",
    "LspServerManager",
    "LspQueries",
    "LspValidator",
    "get_server_manager",
]
