"""Main entry point for Fast Puppy CLI.

This module re-exports the main_entry function from cli_runner for backwards compatibility.
All the actual logic lives in cli_runner.py.
"""

from __future__ import annotations

from code_puppy.cli_runner import main_entry

if __name__ == "__main__":
    main_entry()
