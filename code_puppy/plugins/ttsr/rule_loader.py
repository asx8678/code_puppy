"""Rule loading utilities for the TTSR plugin.

Parses Markdown files with YAML frontmatter into TtsrRule objects.

File format::

    ---
    name: my-rule
    trigger: "some_pattern|another"
    scope: text          # text | thinking | tool | all  (default: text)
    repeat: once         # once | gap:N                  (default: once)
    ---

    Rule body content (Markdown).  This is injected into the system
    prompt as a ``<system-rule>`` block when the trigger fires.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

_VALID_SCOPES = {"text", "thinking", "tool", "all"}
_VALID_REPEAT_PATTERN = re.compile(r"^once$|^gap:\d+$")


@dataclass
class TtsrRule:
    """A single TTSR rule loaded from a Markdown+frontmatter file.

    Attributes:
        name: Human-readable identifier for the rule.
        trigger: Compiled regex that watches the stream.
        content: Markdown body injected when the rule fires.
        scope: Which stream content to watch: ``"text"``, ``"thinking"``,
            ``"tool"``, or ``"all"``.
        repeat: When the rule may fire again: ``"once"`` (never re-fires
            after the first injection) or ``"gap:N"`` (re-fires after N
            turns have elapsed since the last injection).
        source_path: Path of the file the rule was loaded from.
        triggered_at_turn: Turn number when this rule was last injected,
            or ``None`` if it has never been injected.
        pending: ``True`` when the rule has been triggered and is waiting
            to be injected on the next ``load_prompt`` call.
    """

    name: str
    trigger: re.Pattern  # type: ignore[type-arg]
    content: str
    scope: str
    repeat: str
    source_path: Path
    triggered_at_turn: int | None = field(default=None)
    pending: bool = field(default=False)

    def __repr__(self) -> str:
        return (
            f"TtsrRule(name={self.name!r}, scope={self.scope!r}, "
            f"repeat={self.repeat!r}, pending={self.pending})"
        )


# ---------------------------------------------------------------------------
# Frontmatter parser (no external YAML dependency)
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(
    r"^\s*---\s*\n(.*?)\n\s*---\s*\n(.*)",
    re.DOTALL,
)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str] | None:
    """Split YAML frontmatter from body.

    Returns ``(fields, body)`` or ``None`` if no frontmatter is found.
    Only handles simple ``key: value`` pairs (no nesting, no lists).
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None

    raw_fm, body = m.group(1), m.group(2)
    fields: dict[str, str] = {}

    for line in raw_fm.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        # Strip optional inline comments and surrounding quotes
        val = val.strip()
        # Remove inline comments (anything after a bare `#` that is not inside quotes)
        val = re.sub(r"\s+#.*$", "", val)
        val = val.strip().strip('"').strip("'")
        fields[key.strip()] = val

    return fields, body.strip()


# ---------------------------------------------------------------------------
# Rule parsing
# ---------------------------------------------------------------------------


def parse_rule_file(path: Path) -> TtsrRule | None:
    """Parse a single rule file into a :class:`TtsrRule`.

    Returns ``None`` and logs a warning when the file is invalid (missing
    required fields, bad regex, etc.) so callers can skip broken rules
    without crashing.

    Args:
        path: Path to a Markdown file with YAML frontmatter.

    Returns:
        A :class:`TtsrRule` or ``None``.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("ttsr: cannot read rule file %s: %s", path, exc)
        return None

    result = _parse_frontmatter(text)
    if result is None:
        logger.warning(
            "ttsr: rule file %s has no YAML frontmatter block, skipping", path
        )
        return None

    fields, body = result

    # ---- required: name --------------------------------------------------
    name = fields.get("name", "").strip()
    if not name:
        # Fall back to the stem of the file
        name = path.stem
        logger.debug("ttsr: rule file %s has no 'name', using %r", path, name)

    # ---- required: trigger -----------------------------------------------
    trigger_src = fields.get("trigger", "").strip()
    if not trigger_src:
        logger.warning("ttsr: rule file %s has no 'trigger' field, skipping", path)
        return None

    try:
        compiled_trigger = re.compile(trigger_src)
    except re.error as exc:
        logger.warning(
            "ttsr: rule %r in %s has invalid regex %r: %s, skipping",
            name,
            path,
            trigger_src,
            exc,
        )
        return None

    # ---- optional: scope (default "text") --------------------------------
    scope = fields.get("scope", "text").strip().lower()
    if scope not in _VALID_SCOPES:
        logger.warning(
            "ttsr: rule %r has unknown scope %r, defaulting to 'text'", name, scope
        )
        scope = "text"

    # ---- optional: repeat (default "once") --------------------------------
    repeat = fields.get("repeat", "once").strip().lower()
    if not _VALID_REPEAT_PATTERN.match(repeat):
        logger.warning(
            "ttsr: rule %r has invalid repeat %r, defaulting to 'once'", name, repeat
        )
        repeat = "once"

    # ---- body (content) --------------------------------------------------
    if not body:
        logger.warning("ttsr: rule %r in %s has empty body content", name, path)
        # Allow empty-body rules; they'll inject an empty system-rule block.

    return TtsrRule(
        name=name,
        trigger=compiled_trigger,
        content=body,
        scope=scope,
        repeat=repeat,
        source_path=path,
    )


# ---------------------------------------------------------------------------
# Directory loader
# ---------------------------------------------------------------------------


def load_rules_from_dir(directory: Path) -> list[TtsrRule]:
    """Load all ``*.md`` rule files from *directory*.

    Non-existent directories are silently ignored (returns empty list).
    Invalid rule files are skipped with a warning.

    Args:
        directory: Path to scan for ``*.md`` files.

    Returns:
        List of successfully parsed :class:`TtsrRule` objects.
    """
    if not directory.is_dir():
        logger.debug("ttsr: rules dir %s does not exist, skipping", directory)
        return []

    rules: list[TtsrRule] = []
    for md_file in sorted(directory.glob("*.md")):
        rule = parse_rule_file(md_file)
        if rule is not None:
            rules.append(rule)
            logger.debug("ttsr: loaded rule %r from %s", rule.name, md_file)

    return rules
