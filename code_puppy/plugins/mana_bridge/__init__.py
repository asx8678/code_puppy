"""Mana Bridge plugin for Code Puppy.

This plugin provides a TCP bridge to Mana LiveView, forwarding agent
events (stream tokens, tool calls, agent lifecycle) over a msgpack-framed
TCP connection to localhost:9847.

Activation:
    Set the environment variable CODE_PUPPY_BRIDGE=1, or use the
    --bridge-mode CLI flag.

Protocol:
    Frame: [4-byte uint32 BE length][msgpack payload]
    Message: {id: UUID, type: "event"|"request"|"response",
               name: string, data: map}

Graceful degradation:
    If Mana is not running the plugin logs a warning and disables itself
    without affecting the rest of Code Puppy.
"""
