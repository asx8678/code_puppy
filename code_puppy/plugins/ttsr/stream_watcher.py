"""Stream watcher for the TTSR plugin.

Watches streaming events for regex trigger matches and flags matched
rules for next-turn injection.
"""

from __future__ import annotations

import logging
from typing import Any

from code_puppy.utils import RingBuffer

from .rule_loader import TtsrRule

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scope → delta-type mapping
# ---------------------------------------------------------------------------

# pydantic-ai delta class names we classify under each scope
_TEXT_DELTA_TYPES = {"TextPartDelta"}
_THINKING_DELTA_TYPES = {"ThinkingPartDelta"}
_TOOL_DELTA_TYPES = {"ToolCallPartDelta"}

# How many characters to keep in the sliding window to catch matches that
# straddle two consecutive streaming chunks.
_BUFFER_CAPACITY = 512


def _scope_matches_delta_type(scope: str, delta_type: str) -> bool:
    """Return ``True`` when *scope* should watch a given *delta_type*.

    Args:
        scope: Rule scope: ``"text"``, ``"thinking"``, ``"tool"``, or ``"all"``.
        delta_type: Class-name of the delta (e.g. ``"TextPartDelta"``).

    Returns:
        ``True`` if the rule should receive text from this delta.
    """
    if scope == "all":
        return True
    if scope == "text":
        return delta_type in _TEXT_DELTA_TYPES
    if scope == "thinking":
        return delta_type in _THINKING_DELTA_TYPES
    if scope == "tool":
        return delta_type in _TOOL_DELTA_TYPES
    return False


def _extract_text_from_delta(delta: Any, delta_type: str) -> str:
    """Pull the relevant text fragment from a raw delta object.

    Args:
        delta: The delta object from the stream event.
        delta_type: Class-name string of the delta.

    Returns:
        The text fragment, or ``""`` if none found.
    """
    if delta_type in _TEXT_DELTA_TYPES | _THINKING_DELTA_TYPES:
        return getattr(delta, "content_delta", "") or ""
    if delta_type in _TOOL_DELTA_TYPES:
        return getattr(delta, "args_delta", "") or ""
    return ""


# ---------------------------------------------------------------------------
# TtsrStreamWatcher
# ---------------------------------------------------------------------------


class TtsrStreamWatcher:
    """Watches streaming output and flags TTSR rules for injection.

    Rules are matched against a sliding window (ring buffer) of recent
    stream text to avoid missing patterns that straddle chunk boundaries.

    Usage::

        watcher = TtsrStreamWatcher(rules)
        watcher.watch("part_delta", event_data, session_id)

        # After the turn ends:
        pending = watcher.get_pending_rules()
        for rule in pending:
            watcher.mark_injected(rule, current_turn)

    Attributes:
        turn_count: Number of turns that have been completed.  Increment
            this externally (via :meth:`increment_turn`) at the end of
            each model turn.
    """

    def __init__(self, rules: list[TtsrRule]) -> None:
        """Initialise the watcher with a list of rules.

        Args:
            rules: The loaded :class:`~.rule_loader.TtsrRule` objects.
        """
        self._rules = rules
        self._turn_count: int = 0
        # Per-scope ring buffers for partial-match protection
        self._buffers: dict[str, RingBuffer] = {
            "text": RingBuffer(_BUFFER_CAPACITY),
            "thinking": RingBuffer(_BUFFER_CAPACITY),
            "tool": RingBuffer(_BUFFER_CAPACITY),
        }

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def turn_count(self) -> int:
        """Number of completed turns (incremented externally)."""
        return self._turn_count

    @property
    def rules(self) -> list[TtsrRule]:
        """All loaded rules (read-only view)."""
        return self._rules

    # ------------------------------------------------------------------
    # Turn management
    # ------------------------------------------------------------------

    def increment_turn(self) -> None:
        """Advance the turn counter by one.

        Call this at the end of each model response turn (e.g. in the
        ``agent_run_end`` callback).
        """
        self._turn_count += 1
        # Reset per-scope ring buffers for the next turn
        for buf in self._buffers.values():
            buf.clear()

    # ------------------------------------------------------------------
    # Watching
    # ------------------------------------------------------------------

    def watch(
        self,
        event_type: str,
        event_data: Any,
        session_id: str | None = None,
    ) -> None:
        """Check a stream event against all loaded rules.

        Only ``"part_delta"`` events are inspected; others are silently
        ignored.

        Args:
            event_type: The stream event type string.
            event_data: The event payload dict from the stream event.
            session_id: Optional agent session identifier (unused internally
                but kept for API consistency with the callback signature).
        """
        if event_type != "part_delta":
            return

        if not isinstance(event_data, dict):
            return

        delta_type: str = event_data.get("delta_type", "")
        delta: Any = event_data.get("delta")

        if delta is None:
            return

        text_fragment = _extract_text_from_delta(delta, delta_type)
        if not text_fragment:
            return

        # Determine which scope bucket this delta belongs to
        if delta_type in _TEXT_DELTA_TYPES:
            bucket = "text"
        elif delta_type in _THINKING_DELTA_TYPES:
            bucket = "thinking"
        elif delta_type in _TOOL_DELTA_TYPES:
            bucket = "tool"
        else:
            bucket = "text"  # fallback

        # Push chars into the ring buffer for this scope.
        # We accumulate chars; the buffer keeps the most recent N chars.
        for ch in text_fragment:
            self._buffers[bucket].push(ch)

        # Build a search window from the ring buffer
        window = "".join(self._buffers[bucket])

        # Check each rule that maps to this bucket (or "all")
        for rule in self._rules:
            if rule.pending:
                continue  # Already queued, no need to re-check

            if not _scope_matches_delta_type(rule.scope, delta_type):
                continue

            if not self._rule_is_eligible(rule):
                continue

            if rule.trigger.search(window):
                logger.debug(
                    "ttsr: rule %r triggered by stream text in scope=%r",
                    rule.name,
                    rule.scope,
                )
                rule.pending = True

    # ------------------------------------------------------------------
    # Eligibility (repeat policy)
    # ------------------------------------------------------------------

    def _rule_is_eligible(self, rule: TtsrRule) -> bool:
        """Return ``True`` if *rule* is allowed to fire right now.

        Args:
            rule: The rule to check.

        Returns:
            ``True`` if the repeat policy permits firing.
        """
        if rule.triggered_at_turn is None:
            return True  # Never fired before → always eligible

        if rule.repeat == "once":
            return False  # Already fired; never fires again

        if rule.repeat.startswith("gap:"):
            try:
                gap = int(rule.repeat[4:])
            except ValueError:
                return False
            turns_since = self._turn_count - rule.triggered_at_turn
            return turns_since >= gap

        return True

    # ------------------------------------------------------------------
    # Pending rules
    # ------------------------------------------------------------------

    def get_pending_rules(self) -> list[TtsrRule]:
        """Return all rules currently flagged for next-turn injection.

        Returns:
            A list of :class:`~.rule_loader.TtsrRule` objects with
            ``pending == True``.
        """
        return [r for r in self._rules if r.pending]

    # ------------------------------------------------------------------
    # Injection bookkeeping
    # ------------------------------------------------------------------

    def mark_injected(self, rule: TtsrRule, turn: int) -> None:
        """Record that *rule* was injected at *turn*.

        Clears ``pending`` and updates ``triggered_at_turn``.

        Args:
            rule: The rule that was injected.
            turn: The turn number at which it was injected.
        """
        rule.pending = False
        rule.triggered_at_turn = turn
        logger.debug(
            "ttsr: rule %r marked injected at turn %d (repeat=%r)",
            rule.name,
            turn,
            rule.repeat,
        )
