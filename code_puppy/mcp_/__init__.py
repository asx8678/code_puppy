"""MCP (Model Context Protocol) management system for Fast Puppy.

Note: Be careful not to create circular imports with config_wizard.py.
config_wizard.py imports ServerConfig and get_mcp_manager directly from
.manager to avoid circular dependencies with this package __init__.py
"""

from __future__ import annotations

from .config_wizard import MCPConfigWizard, run_add_wizard
from .managed_server import ManagedMCPServer, ServerConfig, ServerState
from .manager import MCPManager, ServerInfo, get_mcp_manager
from .mcp_logs import (
    clear_logs,
    get_log_file_path,
    get_log_stats,
    get_mcp_logs_dir,
    list_servers_with_logs,
    read_logs,
    write_log,
)
from .registry import ServerRegistry
from .status_tracker import Event, ServerStatusTracker

__all__ = [
    "ManagedMCPServer",
    "ServerConfig",
    "ServerState",
    "ServerStatusTracker",
    "Event",
    "MCPManager",
    "ServerInfo",
    "get_mcp_manager",
    "ServerRegistry",
    "MCPConfigWizard",
    "run_add_wizard",
    # Log management
    "get_mcp_logs_dir",
    "get_log_file_path",
    "read_logs",
    "write_log",
    "clear_logs",
    "list_servers_with_logs",
    "get_log_stats",
]
