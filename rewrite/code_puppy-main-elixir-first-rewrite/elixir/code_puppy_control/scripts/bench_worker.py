#!/usr/bin/env python3
"""
Bench worker for Elixir benchmark suite.

This script handles benchmark-specific commands for measuring:
- Worker spawn latency
- Request/response latency
- Concurrent worker scaling
- Fault recovery

Usage:
    python bench_worker.py --run-id <id>
"""

import sys
import json
import time
import os
import signal


def read_message():
    """Read a JSON-RPC message from stdin using Content-Length framing."""
    try:
        line = sys.stdin.readline()
        if not line:
            return None

        if not line.startswith("Content-Length:"):
            return read_message()

        length_str = line.split(":", 1)[1].strip()
        try:
            length = int(length_str)
        except ValueError:
            return None

        # Read empty separator line
        separator = sys.stdin.readline()
        if separator.strip() != "":
            pass

        # Read the JSON body
        body = sys.stdin.read(length)
        if len(body) < length:
            return None

        return json.loads(body)

    except (json.JSONDecodeError, Exception):
        return None


def write_message(msg):
    """Write a JSON-RPC message to stdout with Content-Length framing."""
    body = json.dumps(msg, separators=(',', ':'))
    framed = f"Content-Length: {len(body)}\r\n\r\n{body}"
    sys.stdout.write(framed)
    sys.stdout.flush()


def send_notification(method, params):
    """Send a JSON-RPC notification (no response expected)."""
    notification = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params
    }
    write_message(notification)


def send_response(result, msg_id):
    """Send a JSON-RPC success response."""
    response = {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": result
    }
    write_message(response)


def send_error(code, message, msg_id, data=None):
    """Send a JSON-RPC error response."""
    error = {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {
            "code": code,
            "message": message
        }
    }
    if data is not None:
        error["error"]["data"] = data
    write_message(error)


def handle_ping(params, msg_id):
    """Handle ping/health check - returns immediately for spawn latency test."""
    send_response({
        "status": "ok",
        "timestamp": int(time.time() * 1000000)  # microseconds
    }, msg_id)


def handle_echo(params, msg_id):
    """Handle echo test - returns the input for round-trip measurement."""
    send_response({
        "echo": params.get("message", ""),
        "timestamp": int(time.time() * 1000000),  # microseconds
        "worker_pid": os.getpid()
    }, msg_id)


def handle_initialize(params, msg_id):
    """Handle initialize request - signals worker is ready."""
    send_response({
        "status": "initialized",
        "capabilities": {
            "echo": True,
            "crash": True,
            "ping": True
        },
        "worker_pid": os.getpid(),
        "timestamp": int(time.time() * 1000000)
    }, msg_id)


def handle_crash(params, msg_id):
    """Handle crash command - exits the process for fault recovery test."""
    # Acknowledge the crash command before exiting
    send_response({
        "status": "crashing",
        "message": "Exiting as requested",
        "timestamp": int(time.time() * 1000000)
    }, msg_id)
    sys.stdout.flush()
    # Force exit
    os._exit(1)


def handle_stats(params, msg_id):
    """Return worker statistics."""
    send_response({
        "worker_pid": os.getpid(),
        "timestamp": int(time.time() * 1000000)
    }, msg_id)


def dispatch_request(msg):
    """Dispatch a JSON-RPC request to the appropriate handler."""
    method = msg.get("method", "")
    params = msg.get("params", {})
    msg_id = msg.get("id")

    # Handle notifications (no id)
    if msg_id is None:
        if method == "initialize":
            # Send notification response
            send_notification("initialized", {
                "status": "ready",
                "timestamp": int(time.time() * 1000000)
            })
        return True

    # Route to handler based on method
    handlers = {
        "ping": handle_ping,
        "echo": handle_echo,
        "initialize": handle_initialize,
        "crash": handle_crash,
        "stats": handle_stats,
    }

    handler = handlers.get(method)

    if handler:
        try:
            handler(params, msg_id)
        except Exception as e:
            send_error(-32603, f"Internal error: {e}", msg_id)
    else:
        send_error(-32601, f"Method not found: {method}", msg_id)

    # Check for shutdown or crash
    return method != "crash"


def main():
    """Main entry point for the bench worker."""
    run_id = "unknown"

    # Parse command line arguments
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--run-id" and i + 1 < len(args):
            run_id = args[i + 1]

    # Send startup notification
    send_notification("system.ready", {
        "status": "ready",
        "run_id": run_id,
        "worker_pid": os.getpid(),
        "timestamp": int(time.time() * 1000000)
    })

    running = True
    while running:
        msg = read_message()
        if msg is None:
            break
        running = dispatch_request(msg)

    sys.exit(0)


if __name__ == "__main__":
    main()
