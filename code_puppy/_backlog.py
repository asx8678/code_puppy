"""Event backlog for callbacks fired before listeners register.

During plugin startup, callbacks may fire for phases that have no listeners
yet (because the plugin that registers the listener hasn't loaded). This
module buffers those calls and replays them once listeners are available.

Inspired by Gemini CLI's CoreEventEmitter._emitOrQueue() pattern.
"""

# Lazy-import PhaseType to avoid circular deps at module scope
_MAX_BACKLOG_PER_PHASE = 100

# phase -> list of (args_tuple, kwargs_dict) that were fired with no listeners
_backlog: dict[str, list[tuple[tuple, dict]]] = {}


def buffer_event(phase: str, args: tuple, kwargs: dict) -> None:
    """Buffer an event that had no listeners when fired."""
    buf = _backlog.setdefault(phase, [])
    if len(buf) >= _MAX_BACKLOG_PER_PHASE:
        buf.pop(0)  # evict oldest to cap memory
    buf.append((args, kwargs))


def drain_backlog(phase: str) -> list[tuple[tuple, dict]]:
    """Pop and return all buffered events for *phase*."""
    return _backlog.pop(phase, [])


def drain_all() -> dict[str, list[tuple[tuple, dict]]]:
    """Pop and return buffered events for every phase that has any."""
    result = {p: events for p, events in _backlog.items() if events}
    _backlog.clear()
    return result


def pending_count(phase: str | None = None) -> int:
    """Return number of buffered events, optionally filtered by phase."""
    if phase is not None:
        return len(_backlog.get(phase, []))
    return sum(len(v) for v in _backlog.values())


def clear(phase: str | None = None) -> None:
    """Clear buffered events."""
    if phase is None:
        _backlog.clear()
    else:
        _backlog.pop(phase, None)
