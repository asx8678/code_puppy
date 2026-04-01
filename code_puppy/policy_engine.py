"""Priority-based policy engine for tool permission decisions.

Evaluates tool calls against configurable rules sorted by priority.
Consolidates permission logic from shell_safety and file_permission_handler.

Inspired by Gemini CLI's PolicyEngine.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from code_puppy.permission_decision import Allow, AskUser, Deny, PermissionDecision

logger = logging.getLogger(__name__)

Decision = Literal["allow", "deny", "ask_user"]


@dataclass
class PolicyRule:
    """A single policy rule evaluated against tool calls."""

    tool_name: str  # Tool name pattern, '*' for all
    decision: Decision
    priority: int = 0
    command_pattern: str | None = None  # Regex for shell commands
    args_pattern: str | None = None  # Regex for stringified args
    source: str = "default"

    _compiled_command: re.Pattern | None = field(
        default=None, repr=False, init=False, compare=False,
    )
    _compiled_args: re.Pattern | None = field(
        default=None, repr=False, init=False, compare=False,
    )

    def __post_init__(self) -> None:
        if self.command_pattern:
            self._compiled_command = re.compile(self.command_pattern)
        if self.args_pattern:
            self._compiled_args = re.compile(self.args_pattern)


class PolicyEngine:
    """Evaluates tool calls against priority-sorted rules."""

    def __init__(self, default_decision: Decision = "ask_user") -> None:
        self._rules: list[PolicyRule] = []
        self._default_decision = default_decision

    def add_rule(self, rule: PolicyRule) -> None:
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority, reverse=True)

    def add_rules(self, rules: list[PolicyRule]) -> None:
        self._rules.extend(rules)
        self._rules.sort(key=lambda r: r.priority, reverse=True)

    def remove_rules_by_source(self, source: str) -> None:
        self._rules = [r for r in self._rules if r.source != source]

    @property
    def rules(self) -> list[PolicyRule]:
        return list(self._rules)

    def check(
        self,
        tool_name: str,
        args: dict | None = None,
    ) -> PermissionDecision:
        """Evaluate a tool call against policy rules.

        Returns Allow(), Deny(), or AskUser() based on the first matching
        rule. Falls back to default_decision if no rule matches.
        """
        stringified = json.dumps(args, sort_keys=True) if args else None
        command = (args or {}).get("command", "")

        for rule in self._rules:
            if not self._matches_tool(rule, tool_name):
                continue
            if rule._compiled_command and not rule._compiled_command.search(
                str(command)
            ):
                continue
            if (
                rule._compiled_args
                and stringified
                and not rule._compiled_args.search(stringified)
            ):
                continue
            return self._to_decision(rule.decision, rule)

        return self._to_decision(self._default_decision)

    def check_explicit(
        self,
        tool_name: str,
        args: dict | None = None,
    ) -> "PermissionDecision | None":
        """Check only explicit rules; return None if no rule matched.

        Unlike ``check()``, this method does **not** fall back to the
        configured default decision.  It returns ``None`` when no rule
        matches, signalling "I have no opinion" to the caller.

        Use this in callbacks that have their own fallback logic (e.g.
        the shell-safety LLM risk assessor) and only want to short-circuit
        on an explicit allow/deny policy rule.
        """
        stringified = json.dumps(args, sort_keys=True) if args else None
        command = (args or {}).get("command", "")

        for rule in self._rules:
            if not self._matches_tool(rule, tool_name):
                continue
            if rule._compiled_command and not rule._compiled_command.search(
                str(command)
            ):
                continue
            if (
                rule._compiled_args
                and stringified
                and not rule._compiled_args.search(stringified)
            ):
                continue
            return self._to_decision(rule.decision, rule)

        return None  # no explicit rule matched

    def check_shell_command_explicit(
        self, command: str, cwd: str | None = None
    ) -> "PermissionDecision | None":
        """Check a shell command against explicit rules only; return None if no rule matched.

        Like ``check_explicit()`` but handles compound commands the same way
        ``check_shell_command()`` does: splits on ``&&``, ``||``, and ``;``
        and returns the most restrictive explicit decision across sub-commands.
        Returns ``None`` if no explicit rule matched any sub-command.
        """
        from code_puppy.utils.shell_split import split_compound_command
        sub_commands = split_compound_command(command)

        most_restrictive: PermissionDecision | None = None
        for sub_cmd in sub_commands:
            result = self.check_explicit(
                "run_shell_command", {"command": sub_cmd.strip(), "cwd": cwd}
            )
            if isinstance(result, Deny):
                return result
            if isinstance(result, Allow) and not isinstance(most_restrictive, Deny):
                most_restrictive = result

        return most_restrictive  # None or Allow

    def check_shell_command(
        self, command: str, cwd: str | None = None
    ) -> PermissionDecision:
        """Check a shell command, splitting compounds.

        For compound commands (&&, ||, ;), each sub-command is checked
        independently. The most restrictive decision wins (Deny > AskUser > Allow).
        """
        from code_puppy.utils.shell_split import split_compound_command
        sub_commands = split_compound_command(command)

        if len(sub_commands) <= 1:
            return self.check(
                "run_shell_command", {"command": command, "cwd": cwd}
            )

        most_restrictive: PermissionDecision = Allow()
        for sub_cmd in sub_commands:
            result = self.check(
                "run_shell_command", {"command": sub_cmd.strip(), "cwd": cwd}
            )
            if isinstance(result, Deny):
                return result
            if isinstance(result, AskUser) and isinstance(most_restrictive, Allow):
                most_restrictive = result

        return most_restrictive

    def load_rules_from_file(
        self, path: Path, source: str | None = None
    ) -> int:
        """Load rules from a JSON file. Returns count loaded."""
        if not path.exists():
            return 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            rules_list = data if isinstance(data, list) else data.get("rules", [])
            count = 0
            for r in rules_list:
                if not isinstance(r, dict) or "tool_name" not in r:
                    continue
                self.add_rule(PolicyRule(
                    tool_name=r["tool_name"],
                    decision=r.get("decision", "ask_user"),
                    priority=r.get("priority", 0),
                    command_pattern=r.get("command_pattern"),
                    args_pattern=r.get("args_pattern"),
                    source=source or str(path),
                ))
                count += 1
            logger.info("Loaded %d policy rules from %s", count, path)
            return count
        except Exception as exc:
            logger.warning("Failed to load policy rules from %s: %s", path, exc)
            return 0

    def load_default_rules(self) -> None:
        """Load from standard locations: user then project (project wins)."""
        self.load_rules_from_file(
            Path.home() / ".code_puppy" / "policy.json", source="user"
        )
        self.load_rules_from_file(
            Path.cwd() / ".code_puppy" / "policy.json", source="project"
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _matches_tool(rule: PolicyRule, tool_name: str) -> bool:
        if rule.tool_name == "*":
            return True
        return rule.tool_name == tool_name

    @staticmethod
    def _to_decision(
        decision: Decision, rule: PolicyRule | None = None
    ) -> PermissionDecision:
        src = f" (rule from {rule.source})" if rule else ""
        if decision == "allow":
            return Allow()
        if decision == "deny":
            return Deny(reason=f"Denied by policy{src}")
        return AskUser(prompt=f"Policy requires user approval{src}")


# ── Singleton ──────────────────────────────────────────────────────────
_engine: PolicyEngine | None = None


def get_policy_engine() -> PolicyEngine:
    """Get or create the singleton PolicyEngine."""
    global _engine
    if _engine is None:
        from code_puppy.config import get_yolo_mode
        from code_puppy.policy_config import load_policy_rules

        default: Decision = "allow" if get_yolo_mode() else "ask_user"
        _engine = PolicyEngine(default_decision=default)
        load_policy_rules(_engine)
    return _engine


def reset_policy_engine() -> None:
    """Reset the singleton (useful for testing)."""
    global _engine
    _engine = None
