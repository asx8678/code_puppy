"""Lazy TTSR (Time-Traveling Streamed Rules) plugin.

Inspired by oh-my-pi's TTSR system. Rules define regex patterns that
watch the model's output stream. When triggered, rule content is
injected into the system prompt on the next turn.

This is the "lazy" variant: instead of aborting mid-stream, triggered
rules are queued and applied at the next model call boundary.
"""
