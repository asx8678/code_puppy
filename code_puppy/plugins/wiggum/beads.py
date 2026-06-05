"""``/wiggum bd`` — drain the ready ``bd`` (beads) queue one bead at a time.

Extension of the wiggum plugin (no core change): rides the existing
``interactive_turn_end`` continuation loop and reuses ``WiggumState`` for the
active/stop lifecycle (so ``/wiggum_stop`` + Ctrl+C work). The agent claims,
verifies, and closes each bead itself; we only route to the next ready bead,
verify the previous one closed, show a per-bead summary, and stop when empty.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from code_puppy.messaging import emit_info, emit_success, emit_warning

from . import state

_current: str | None = None  # bead last dispatched
_seen: set[str] = set()  # beads dispatched this run (guards forgot-to-claim spins)
_done: int = 0  # beads verified closed this run


def _bd(args: list[str]) -> Any:
    """Run ``bd <args> --json`` and parse it, or ``None`` on any failure."""
    try:
        out = subprocess.run(
            ["bd", *args, "--json"], capture_output=True, text=True, timeout=30
        ).stdout
        return json.loads(out) if out.strip() else None
    except Exception:
        return None


def _ready() -> list[dict]:
    """Ready beads not already dispatched this run (in_progress are excluded by bd)."""
    return [b for b in (_bd(["ready", "-n", "1000"]) or []) if b.get("id") not in _seen]


def _status(bid: str) -> str | None:
    rec = _bd(["show", bid]) or [{}]
    return (rec[0] if isinstance(rec, list) else rec or {}).get("status")


def _remaining() -> int:
    """Total not-yet-closed beads (incl. blocked), for the 'to go' count."""
    d = _bd(["count", "--by-status"]) or {}
    g = {x.get("group"): x.get("count", 0) for x in d.get("groups", [])}
    return d.get("total", 0) - g.get("closed", 0)


def _prompt(b: dict) -> str:
    bid, title = b.get("id"), b.get("title", "")
    return (
        f"You are working bd bead {bid}: {title}.\n"
        f"1. `bd show {bid}` — read the full description and acceptance criteria.\n"
        f"2. `bd update {bid} --claim` — atomically claim it (race-safe across puppies).\n"
        f"3. Do the work and verify it (run tests/build if relevant).\n"
        f'4. If genuinely done: `bd close {bid} --reason "<what you did>"`.\n'
        f'   Else `bd note {bid} "<why>"`, leave it open, and stop.\n'
        f"Then stop — the next bead is dispatched automatically."
    )


def _dispatch(ready: list[dict], *, finished: str | None) -> str:
    """Advance the cursor to ready[0], print the progress summary, return its prompt."""
    global _current
    cur, nxt = ready[0], (ready[1] if len(ready) > 1 else None)
    _current = cur.get("id")
    _seen.add(_current)
    head = (
        f"🍩 Bead done ✓ — finished {finished}"
        if finished
        else "🍩 WIGGUM BD MODE — working ready beads one at a time until done."
    )
    nxt_txt = f"{nxt.get('id')} — {nxt.get('title', '')}" if nxt else "— (last one)"
    emit_info(
        f"{head}\n"
        f"   Progress: {_done} done · {_remaining()} to go\n"
        f"   ▶ Now running: {cur.get('id')} — {cur.get('title', '')}\n"
        f"   ⏭ Up next:     {nxt_txt}"
    )
    return _prompt(cur)


def start() -> str | bool:
    """Begin a ``/wiggum bd`` run: dispatch the top bead, or ``True`` if none ready."""
    global _current, _seen, _done
    _seen, _done, _current = set(), 0, None
    ready = _ready()
    if not ready:
        emit_info("🍩 No ready beads — nothing to do.")
        return True
    state.start("bd", mode="wiggum_bd")
    return _dispatch(ready, finished=None)


def on_turn_end() -> dict | None:
    """After a bead finishes: verify it closed, then dispatch the next or stop."""
    global _done
    prev = _current
    if prev and _status(prev) == "closed":
        _done += 1
    elif prev:
        emit_warning(f"🍩 {prev} left open — moving on.")  # reported, not retried
    ready = _ready()
    if not ready:
        left = _remaining()
        tail = f" ({left} blocked/open remain — not actionable.)" if left else ""
        emit_success(f"🍩 ALL READY BEADS DONE — finished {_done} this run.{tail}")
        state.stop()
        return None
    return {
        "prompt": _dispatch(ready, finished=prev),
        "clear_context": True,
        "delay": 0.5,
        "reason": "wiggum_bd",
    }
