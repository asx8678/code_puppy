"""Code intelligence context injection plugin.

Auto-injects relevant code context into agent prompts via the load_prompt hook.
Uses the context engine to discover, score, and format relevant code symbols.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from code_puppy.callbacks import register_callback

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Plugin state
_config = {
    "enabled": True,
    "max_context_chars": 6000,
    "max_symbols": 5,
    "min_relevance_score": 3.0,
    "include_source": True,
    "verbose": False,
}

_engine: object | None = None
_conversation_buffer: list[str] = []


def _load_config() -> dict:
    """Load configuration from environment variables."""
    return {
        "enabled": os.getenv("CODE_INTEL_ENABLED", "true").lower() in ("true", "1", "yes"),
        "max_context_chars": int(os.getenv("CODE_INTEL_MAX_CHARS", "6000")),
        "max_symbols": int(os.getenv("CODE_INTEL_MAX_SYMBOLS", "5")),
        "min_relevance_score": float(os.getenv("CODE_INTEL_MIN_RELEVANCE", "3.0")),
        "include_source": os.getenv("CODE_INTEL_INCLUDE_SOURCE", "true").lower()
        in ("true", "1", "yes"),
        "verbose": os.getenv("CODE_INTEL_VERBOSE", "false").lower() in ("true", "1", "yes"),
    }


def _get_engine():
    """Lazy-load the context engine."""
    global _engine

    if _engine is not None:
        return _engine

    try:
        from code_puppy.code_intel import ContextEngine, ContextEngineConfig

        cfg = _load_config()

        if not cfg["enabled"]:
            logger.debug("Code intelligence context: disabled")
            return None

        config = ContextEngineConfig(
            enabled=True,
            max_symbols_per_prompt=cfg["max_symbols"],
            max_chars_per_prompt=cfg["max_context_chars"],
            min_relevance_score=cfg["min_relevance_score"],
            include_source_code=cfg["include_source"],
        )

        _engine = ContextEngine(config)
        _engine.initialize()

        logger.debug("Code intelligence context: engine initialized")
        return _engine

    except ImportError as e:
        logger.debug(f"Code intelligence context: import error - {e}")
        return None
    except Exception as e:
        logger.debug(f"Code intelligence context: init error - {e}")
        return None


def _get_recent_files() -> list[str]:
    """Get list of recently modified files in the project.

    Uses git if available, otherwise falls back to file system mtime.
    """
    try:
        # Try git first
        import subprocess

        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~10", "HEAD"],
            capture_output=True,
            text=True,
            cwd=Path.cwd(),
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
            return [f for f in files if Path(f).exists()]
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass

    # Fallback: files modified in last hour
    try:
        import time

        cwd = Path.cwd()
        recent = []
        cutoff = time.time() - 3600  # 1 hour ago

        for pattern in ["*.py", "*.js", "*.ts", "*.java"]:
            for path in cwd.rglob(pattern):
                try:
                    if path.stat().st_mtime > cutoff:
                        recent.append(str(path))
                        if len(recent) >= 20:
                            break
                except (OSError, PermissionError):
                    continue
            if len(recent) >= 20:
                break

        return recent
    except (OSError, PermissionError):
        pass

    return []


def _load_code_intel_prompt() -> str | None:
    """Build and return code intelligence prompt addition.

    Called on the load_prompt hook to inject relevant code context.
    Returns None if no relevant context or if disabled.
    """
    engine = _get_engine()
    if engine is None:
        return None

    # Update recent files
    try:
        recent_files = _get_recent_files()
        engine.set_recent_files(recent_files)
    except Exception as e:
        logger.debug(f"Code intelligence: error getting recent files - {e}")

    # Add buffered conversation
    if _conversation_buffer:
        for msg in _conversation_buffer:
            engine.add_conversation_turn(msg)
        _conversation_buffer.clear()

    # Build context
    try:
        context = engine.build_context()
        if context and _config.get("verbose"):
            logger.debug(f"Code intelligence: injected {len(context)} chars of context")
        return context
    except Exception as e:
        logger.debug(f"Code intelligence: error building context - {e}")
        return None


def _on_agent_run_start(agent_name: str, model_name: str, session_id: str | None = None) -> None:
    """Hook into agent run start to reset state."""
    global _conversation_buffer
    _conversation_buffer = []

    # Refresh config at start of each run
    global _config
    _config = _load_config()

    logger.debug(f"Code intelligence: reset for agent {agent_name}")


def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: Exception | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Hook into agent run end to capture assistant responses.

    Stores the assistant's response for context in future prompts.
    """
    engine = _get_engine()
    if engine is None:
        return

    if response_text:
        try:
            # Extract code-related content
            engine.add_conversation_turn("", response_text)
        except Exception as e:
            logger.debug(f"Code intelligence: error capturing response - {e}")


def _custom_command_help() -> list[tuple[str, str]]:
    """Return help for custom commands."""
    return [("code-intel", "Show code intelligence context status")]


def _on_custom_command(command: str, name: str) -> bool | None:
    """Handle /code-intel command."""
    if name != "code-intel":
        return None

    try:
        from code_puppy.messaging import emit_info, emit_warning
    except ImportError:
        emit_info = print  # type: ignore[assignment]
        emit_warning = print  # type: ignore[assignment]

    parts = command.strip().split()
    subcmd = parts[1] if len(parts) > 1 else "status"

    if subcmd == "status":
        cfg = _load_config()
        engine = _get_engine()

        status = "🟢 enabled" if cfg["enabled"] and engine else "🔴 disabled"

        info_lines = [
            f"Code Intelligence Context: {status}",
            f"  Max symbols: {cfg['max_symbols']}",
            f"  Max chars: {cfg['max_context_chars']}",
            f"  Min relevance: {cfg['min_relevance_score']}",
            f"  Include source: {cfg['include_source']}",
        ]

        if engine:
            try:
                cached = engine.get_cached_symbols()
                info_lines.append(f"  Cached symbols: {len(cached)}")
            except Exception:
                pass

        emit_info("\n".join(info_lines))
        return True

    elif subcmd == "clear":
        engine = _get_engine()
        if engine:
            try:
                engine.clear_cache()
                from code_puppy.messaging import emit_info

                emit_info("🧹 Code intelligence cache cleared")
            except Exception as e:
                from code_puppy.messaging import emit_warning

                emit_warning(f"Error clearing cache: {e}")
        return True

    else:
        from code_puppy.messaging import emit_info

        emit_info("Usage: /code-intel [status|clear]")
        return True


# Register callbacks
register_callback("agent_run_start", _on_agent_run_start)
register_callback("agent_run_end", _on_agent_run_end)
register_callback("load_prompt", _load_code_intel_prompt)
register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _custom_command_help)

logger.debug("code_intel_context plugin registered")
