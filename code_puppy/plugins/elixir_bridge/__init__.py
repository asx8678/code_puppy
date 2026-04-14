"""Elixir Bridge Plugin - Bridge mode for Elixir Port communication.

This plugin enables Code Puppy to run as a child process controlled by Elixir
via JSON-RPC over stdio. When CODE_PUPPY_BRIDGE=1 environment variable is set,
the bridge activates and:

1. Emits events to stdout in JSON-RPC format
2. Receives commands from stdin in JSON-RPC format
3. Translates between Python message types and Elixir wire protocol

This prepares Python to be controlled by Elixir for the migration.

Environment:
    CODE_PUPPY_BRIDGE=1    Enable bridge mode
    CODE_PUPPY_BRIDGE_LOG  Optional log file path for debugging

Example Elixir Port usage:
    # Elixir side
    port = Port.open({:spawn, "python -m code_puppy"}, [:binary, :exit_status])
    # Send command
    Port.command(port, ~s({"jsonrpc": "2.0", "id": "1", "method": "invoke_agent", "params": {...}}\\n))
    # Receive event
    receive do
      {^port, {:data, data}} ->
        # data contains JSON-RPC notification
    end

Architecture:
    ┌─────────────┐       stdio (JSON-RPC)       ┌─────────────┐
    │   Elixir    │  ───────────────────────────▶│   Python    │
    │  (Port)     │◀───────────────────────────────│  (Bridge)   │
    └─────────────┘                                  └─────────────┘
                                                          │
                            ┌──────────────────────────────┘
                            ▼
                    ┌─────────────────┐
                    │  Agent Tools    │
                    │  File Ops       │
                    │  Shell Commands │
                    └─────────────────┘

See: docs/architecture/python-singleton-audit.md for migration context.
"""

from __future__ import annotations

import os

# Bridge mode detection - used by register_callbacks to decide whether to activate
BRIDGE_ENABLED = os.environ.get("CODE_PUPPY_BRIDGE", "").strip() == "1"
BRIDGE_LOG_FILE = os.environ.get("CODE_PUPPY_BRIDGE_LOG")

__all__ = ["BRIDGE_ENABLED", "BRIDGE_LOG_FILE"]
