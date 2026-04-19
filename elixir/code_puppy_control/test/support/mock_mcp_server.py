#!/usr/bin/env python3
"""Mock MCP server for testing the Elixir MCP client.

Implements the MCP JSON-RPC protocol over stdio:
- initialize / initialized handshake
- tools/list → returns a list of test tools
- tools/call → calls a tool and returns results

Reads newline-delimited JSON-RPC from stdin, writes to stdout.
"""

import json
import sys
import signal

# Ignore broken pipe so the server shuts down cleanly when the client disconnects
signal.signal(signal.SIGPIPE, signal.SIG_DFL)

def handle_initialize(params):
    """Handle the initialize request."""
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {}
        },
        "serverInfo": {
            "name": "mock-mcp-server",
            "version": "1.0.0"
        }
    }

def handle_tools_list(params):
    """Handle the tools/list request."""
    return {
        "tools": [
            {
                "name": "echo",
                "description": "Echoes back the input",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "The message to echo"
                        }
                    },
                    "required": ["message"]
                }
            },
            {
                "name": "add",
                "description": "Adds two numbers",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "number"},
                        "b": {"type": "number"}
                    },
                    "required": ["a", "b"]
                }
            }
        ]
    }

def handle_tools_call(params):
    """Handle the tools/call request."""
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    if tool_name == "echo":
        message = arguments.get("message", "")
        return {
            "content": [
                {"type": "text", "text": message}
            ]
        }
    elif tool_name == "add":
        a = arguments.get("a", 0)
        b = arguments.get("b", 0)
        return {
            "content": [
                {"type": "text", "text": str(a + b)}
            ]
        }
    else:
        return {
            "isError": True,
            "content": [
                {"type": "text", "text": f"Unknown tool: {tool_name}"}
            ]
        }

def main():
    """Main loop: read JSON-RPC from stdin, process, write to stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue

        jsonrpc = message.get("jsonrpc", "")
        method = message.get("method", "")
        msg_id = message.get("id")
        params = message.get("params", {})

        # Handle requests (have an id)
        if method and msg_id is not None:
            result = None
            error = None

            if method == "initialize":
                result = handle_initialize(params)
            elif method == "tools/list":
                result = handle_tools_list(params)
            elif method == "tools/call":
                result = handle_tools_call(params)
            else:
                error = {"code": -32601, "message": f"Method not found: {method}"}

            if error:
                response = {"jsonrpc": "2.0", "id": msg_id, "error": error}
            else:
                response = {"jsonrpc": "2.0", "id": msg_id, "result": result}

            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

        # Handle notifications (no id)
        elif method == "notifications/initialized":
            # Acknowledge the initialized notification — no response needed
            pass

if __name__ == "__main__":
    main()
