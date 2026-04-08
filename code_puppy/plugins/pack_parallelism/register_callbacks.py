"""
Pack Leader max-parallelism constraint plugin.

Reads a configured ``max_parallelism`` value and injects it into every
agent system prompt via the ``load_prompt`` hook, and exposes a
``/pack-parallel N`` slash command to override it per-session.

Permanent config (TOML):
    ~/.code_puppy/pack_parallelism.toml

    [pack_leader]
    max_parallelism = 2          # default: 2

Per-session override (slash command):
    /pack-parallel 4             # set to 4 for this session
    /pack-parallel               # show current value
"""

import logging
from pathlib import Path

from code_puppy.callbacks import register_callback

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path.home() / ".code_puppy" / "pack_parallelism.toml"
_BUILTIN_DEFAULT = 2

# Module-level per-session override; None means "use config file value"
_session_max: int | None = None

# Cached result of reading the config file so we only parse it once per session
_cached_config: int | None = None


def _read_config_max() -> int:
    """Read max_parallelism from the TOML config, with graceful fallback.

    The result is cached after the first read so the file is not parsed on
    every prompt injection.
    """
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    result = _BUILTIN_DEFAULT
    if not _CONFIG_PATH.exists():
        _cached_config = result
        return _cached_config
    try:
        import tomllib  # Python 3.11+

        with open(_CONFIG_PATH, "rb") as fh:
            data = tomllib.load(fh)
        result = int(
            data.get("pack_leader", {}).get("max_parallelism", _BUILTIN_DEFAULT)
        )
    except Exception as exc:
        logger.warning(
            "pack_parallelism: could not read config %s: %s", _CONFIG_PATH, exc
        )
        result = _BUILTIN_DEFAULT

    _cached_config = result
    return _cached_config


def _effective_max() -> int:
    """Return the currently active max (session override > config file > builtin default)."""
    if _session_max is not None:
        return _session_max
    return _read_config_max()


# ---------------------------------------------------------------------------
# load_prompt hook — injected into every agent's system prompt
# ---------------------------------------------------------------------------


def _prompt_addition() -> str | None:
    """Return a parallelism constraint block for the Pack Leader system prompt."""
    max_p = _effective_max()
    return (
        f"\n\n## ⚡ Pack Leader Parallelism Limit\n"
        f"**`MAX_PARALLEL_AGENTS = {max_p}`**\n\n"
        f"Never invoke more than **{max_p}** agent(s) simultaneously.\n"
        f"When `bd ready` returns more than {max_p} issues, work through them\n"
        f"in batches of {max_p}, waiting for each batch to complete before\n"
        f"starting the next.\n\n"
        f"*(Override for this session with `/pack-parallel N`)*"
    )


register_callback("load_prompt", _prompt_addition)


# ---------------------------------------------------------------------------
# custom_command hook — /pack-parallel N
# ---------------------------------------------------------------------------

_COMMAND_NAMES = {"pack-parallel", "pack-par"}


def _invalidate_agent_caches(previous_val: int | None, new_val: int) -> None:
    """Invalidate agent caches to ensure new MAX_PARALLEL_AGENTS is reflected.

    Busts both the Rust-path cached system prompt and rebuilds the PydanticAgent
    instance with fresh instructions containing the updated value.
    """
    # Optimization: skip heavy reload if value hasn't actually changed
    if previous_val is not None and previous_val == new_val:
        return

    # Lazy import to avoid circular dependencies
    try:
        from code_puppy.agents.agent_manager import get_current_agent
    except ImportError:
        return  # Agent manager not available, skip cache invalidation

    try:
        agent = get_current_agent()
    except Exception:
        # No active agent or other error - cache invalidation is best-effort
        return

    if agent is None:
        return

    try:
        # Bust Rust-path cached system prompt (base_agent.py:1477-1483)
        if hasattr(agent, "_state") and hasattr(agent._state, "cached_system_prompt"):
            agent._state.cached_system_prompt = None

        # Rebuild PydanticAgent with fresh instructions (base_agent.py:1846-1878)
        if hasattr(agent, "reload_code_generation_agent"):
            agent.reload_code_generation_agent()
    except Exception:
        # Best-effort: never crash the slash command due to cache invalidation
        logger.debug(
            "pack_parallelism: cache invalidation failed (non-critical)", exc_info=True
        )


def _handle_command(command: str, name: str):
    """Handle /pack-parallel [N] slash command."""
    global _session_max

    if name not in _COMMAND_NAMES:
        return None  # not ours

    try:
        from code_puppy.messaging import emit_error, emit_info
    except ImportError:
        emit_info = print  # type: ignore[assignment]
        emit_error = print  # type: ignore[assignment]

    parts = command.strip().split()

    if len(parts) < 2:
        # No argument → show current value
        current = _effective_max()
        config_val = _read_config_max()
        source = (
            "session override"
            if _session_max is not None
            else f"config ({_CONFIG_PATH})"
        )
        emit_info(
            f"🐺 Pack Leader max parallelism: **{current}** (from {source})\n"
            f"   Config file default: {config_val}\n"
            f"   Usage: /pack-parallel <N>  (e.g. /pack-parallel 4)"
        )
        return True

    try:
        new_val = int(parts[1])
    except ValueError:
        emit_error(f"pack-parallel: '{parts[1]}' is not a valid integer")
        return True

    if new_val < 1:
        emit_error("pack-parallel: value must be at least 1")
        return True

    if new_val > 32:
        emit_info(f"⚠️ /pack-parallel: {new_val} is very high, capping at 32")
        new_val = 32

    # Remember previous value for optimization
    previous_val = _session_max
    _session_max = new_val

    # Invalidate agent caches so the new value is reflected in prompts
    _invalidate_agent_caches(previous_val, new_val)

    emit_info(
        f"🐺 Pack Leader max parallelism → **{new_val}** (session only)\n"
        f"   To make this permanent, edit {_CONFIG_PATH}:\n"
        f"   [pack_leader]\n"
        f"   max_parallelism = {new_val}"
    )
    return True


register_callback("custom_command", _handle_command)


# ---------------------------------------------------------------------------
# custom_command_help hook
# ---------------------------------------------------------------------------


def _command_help() -> list[tuple[str, str]]:
    max_p = _effective_max()
    return [
        (
            "pack-parallel",
            f"Get/set Pack Leader max parallel agents (current: {max_p}). "
            f"Usage: /pack-parallel N",
        ),
        ("pack-par", "Alias for /pack-parallel"),
    ]


register_callback("custom_command_help", _command_help)

logger.info("pack_parallelism plugin loaded (effective max=%d)", _effective_max())
