"""Tests for the Lazy TTSR (Time-Traveling Streamed Rules) plugin.

Covers:
- Rule loading from Markdown+frontmatter files
- Regex trigger matching on stream text
- Pending rules correctly flagged after match
- Repeat "once" prevents re-trigger
- Repeat "gap:5" allows re-trigger after 5 turns
- Scope filtering (text vs thinking vs tool)
- inject_triggered_rules returns rule content and clears pending
- Multiple rules, only matching ones flagged
- Invalid regex in trigger gracefully skipped
- Missing frontmatter fields use defaults
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_rule(
    tmp_path: Path,
    filename: str,
    frontmatter: str,
    body: str,
) -> Path:
    """Write a rule file to *tmp_path* and return its path."""
    path = tmp_path / filename
    path.write_text(f"---\n{frontmatter}\n---\n\n{body}")
    return path


def _make_delta_event(delta_type: str, content: str) -> dict:
    """Build a fake ``part_delta`` event_data dict."""
    delta = MagicMock()
    if delta_type == "TextPartDelta":
        delta.content_delta = content
        delta.args_delta = ""
    elif delta_type == "ThinkingPartDelta":
        delta.content_delta = content
        delta.args_delta = ""
    elif delta_type == "ToolCallPartDelta":
        delta.args_delta = content
        delta.content_delta = ""
    else:
        delta.content_delta = content
        delta.args_delta = ""
    return {"delta_type": delta_type, "delta": delta}


# ---------------------------------------------------------------------------
# rule_loader: parse_rule_file
# ---------------------------------------------------------------------------


class TestParseRuleFile:
    def test_basic_rule_loaded(self, tmp_path):
        from code_puppy.plugins.ttsr.rule_loader import parse_rule_file

        p = _write_rule(
            tmp_path,
            "test.md",
            'name: my-rule\ntrigger: "old_api"\nscope: text\nrepeat: once',
            "Do not use old_api.",
        )
        rule = parse_rule_file(p)
        assert rule is not None
        assert rule.name == "my-rule"
        assert rule.trigger.pattern == "old_api"
        assert rule.scope == "text"
        assert rule.repeat == "once"
        assert rule.content == "Do not use old_api."
        assert rule.source_path == p
        assert rule.pending is False
        assert rule.triggered_at_turn is None

    def test_defaults_used_when_optional_fields_missing(self, tmp_path):
        from code_puppy.plugins.ttsr.rule_loader import parse_rule_file

        p = _write_rule(
            tmp_path,
            "minimal.md",
            "name: minimal-rule\ntrigger: some_pattern",
            "Minimal body.",
        )
        rule = parse_rule_file(p)
        assert rule is not None
        assert rule.scope == "text"  # default
        assert rule.repeat == "once"  # default

    def test_name_falls_back_to_file_stem(self, tmp_path):
        from code_puppy.plugins.ttsr.rule_loader import parse_rule_file

        p = _write_rule(
            tmp_path,
            "fallback-name.md",
            "trigger: some_pattern",
            "Body.",
        )
        rule = parse_rule_file(p)
        assert rule is not None
        assert rule.name == "fallback-name"

    def test_invalid_regex_returns_none(self, tmp_path):
        from code_puppy.plugins.ttsr.rule_loader import parse_rule_file

        p = _write_rule(
            tmp_path,
            "bad_regex.md",
            "name: bad\ntrigger: '[unclosed'",
            "Body.",
        )
        rule = parse_rule_file(p)
        assert rule is None

    def test_missing_trigger_returns_none(self, tmp_path):
        from code_puppy.plugins.ttsr.rule_loader import parse_rule_file

        p = _write_rule(
            tmp_path,
            "no_trigger.md",
            "name: no-trigger",
            "Body.",
        )
        rule = parse_rule_file(p)
        assert rule is None

    def test_missing_frontmatter_returns_none(self, tmp_path):
        from code_puppy.plugins.ttsr.rule_loader import parse_rule_file

        p = tmp_path / "no_fm.md"
        p.write_text("Just markdown, no frontmatter.\n")
        rule = parse_rule_file(p)
        assert rule is None

    def test_invalid_scope_defaults_to_text(self, tmp_path):
        from code_puppy.plugins.ttsr.rule_loader import parse_rule_file

        p = _write_rule(
            tmp_path,
            "bad_scope.md",
            "name: s\ntrigger: foo\nscope: banana",
            "Body.",
        )
        rule = parse_rule_file(p)
        assert rule is not None
        assert rule.scope == "text"

    def test_invalid_repeat_defaults_to_once(self, tmp_path):
        from code_puppy.plugins.ttsr.rule_loader import parse_rule_file

        p = _write_rule(
            tmp_path,
            "bad_repeat.md",
            "name: r\ntrigger: foo\nrepeat: every-day",
            "Body.",
        )
        rule = parse_rule_file(p)
        assert rule is not None
        assert rule.repeat == "once"

    def test_gap_repeat_accepted(self, tmp_path):
        from code_puppy.plugins.ttsr.rule_loader import parse_rule_file

        p = _write_rule(
            tmp_path,
            "gap.md",
            "name: g\ntrigger: foo\nrepeat: gap:5",
            "Body.",
        )
        rule = parse_rule_file(p)
        assert rule is not None
        assert rule.repeat == "gap:5"

    def test_scope_thinking_accepted(self, tmp_path):
        from code_puppy.plugins.ttsr.rule_loader import parse_rule_file

        p = _write_rule(
            tmp_path,
            "think.md",
            "name: t\ntrigger: foo\nscope: thinking",
            "Body.",
        )
        rule = parse_rule_file(p)
        assert rule is not None
        assert rule.scope == "thinking"

    def test_scope_tool_accepted(self, tmp_path):
        from code_puppy.plugins.ttsr.rule_loader import parse_rule_file

        p = _write_rule(
            tmp_path,
            "tool.md",
            "name: tool-rule\ntrigger: exec\nscope: tool",
            "Body.",
        )
        rule = parse_rule_file(p)
        assert rule is not None
        assert rule.scope == "tool"

    def test_scope_all_accepted(self, tmp_path):
        from code_puppy.plugins.ttsr.rule_loader import parse_rule_file

        p = _write_rule(
            tmp_path,
            "all.md",
            "name: all-rule\ntrigger: exec\nscope: all",
            "Body.",
        )
        rule = parse_rule_file(p)
        assert rule is not None
        assert rule.scope == "all"

    def test_nonexistent_file_returns_none(self, tmp_path):
        from code_puppy.plugins.ttsr.rule_loader import parse_rule_file

        result = parse_rule_file(tmp_path / "doesnotexist.md")
        assert result is None

    def test_trigger_without_quotes(self, tmp_path):
        from code_puppy.plugins.ttsr.rule_loader import parse_rule_file

        p = _write_rule(
            tmp_path,
            "noquote.md",
            "name: nq\ntrigger: raw_pattern",
            "Body.",
        )
        rule = parse_rule_file(p)
        assert rule is not None
        assert rule.trigger.pattern == "raw_pattern"

    def test_inline_comment_stripped_from_scope(self, tmp_path):
        from code_puppy.plugins.ttsr.rule_loader import parse_rule_file

        p = _write_rule(
            tmp_path,
            "inline_comment.md",
            "name: ic\ntrigger: foo\nscope: text  # text, thinking, tool, or all",
            "Body.",
        )
        rule = parse_rule_file(p)
        assert rule is not None
        assert rule.scope == "text"


# ---------------------------------------------------------------------------
# rule_loader: load_rules_from_dir
# ---------------------------------------------------------------------------


class TestLoadRulesFromDir:
    def test_loads_multiple_rules(self, tmp_path):
        from code_puppy.plugins.ttsr.rule_loader import load_rules_from_dir

        _write_rule(tmp_path, "a.md", "name: a\ntrigger: aaa", "Body A.")
        _write_rule(tmp_path, "b.md", "name: b\ntrigger: bbb", "Body B.")

        rules = load_rules_from_dir(tmp_path)
        assert len(rules) == 2
        names = {r.name for r in rules}
        assert names == {"a", "b"}

    def test_skips_invalid_rules(self, tmp_path):
        from code_puppy.plugins.ttsr.rule_loader import load_rules_from_dir

        _write_rule(tmp_path, "good.md", "name: good\ntrigger: ok", "Body.")
        _write_rule(tmp_path, "bad.md", "name: bad\ntrigger: [bad", "Body.")

        rules = load_rules_from_dir(tmp_path)
        assert len(rules) == 1
        assert rules[0].name == "good"

    def test_nonexistent_dir_returns_empty(self, tmp_path):
        from code_puppy.plugins.ttsr.rule_loader import load_rules_from_dir

        rules = load_rules_from_dir(tmp_path / "nosuchdir")
        assert rules == []

    def test_empty_dir_returns_empty(self, tmp_path):
        from code_puppy.plugins.ttsr.rule_loader import load_rules_from_dir

        rules = load_rules_from_dir(tmp_path)
        assert rules == []


# ---------------------------------------------------------------------------
# stream_watcher: TtsrStreamWatcher
# ---------------------------------------------------------------------------


class TestTtsrStreamWatcher:
    def _make_rule(
        self,
        name: str,
        trigger_src: str,
        scope: str = "text",
        repeat: str = "once",
    ):
        from code_puppy.plugins.ttsr.rule_loader import TtsrRule

        return TtsrRule(
            name=name,
            trigger=re.compile(trigger_src),
            content=f"Content for {name}.",
            scope=scope,
            repeat=repeat,
            source_path=Path(f"/fake/{name}.md"),
        )

    def test_text_trigger_on_text_delta(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher

        rule = self._make_rule("r", "deprecated_func", scope="text")
        watcher = TtsrStreamWatcher([rule])

        event_data = _make_delta_event("TextPartDelta", "calling deprecated_func here")
        watcher.watch("part_delta", event_data)

        assert rule.pending is True

    def test_no_trigger_without_match(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher

        rule = self._make_rule("r", "deprecated_func", scope="text")
        watcher = TtsrStreamWatcher([rule])

        event_data = _make_delta_event("TextPartDelta", "calling some_safe_func here")
        watcher.watch("part_delta", event_data)

        assert rule.pending is False

    def test_thinking_scope_triggers_on_thinking_delta(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher

        rule = self._make_rule("r", "secret_logic", scope="thinking")
        watcher = TtsrStreamWatcher([rule])

        watcher.watch("part_delta", _make_delta_event("ThinkingPartDelta", "using secret_logic"))
        assert rule.pending is True

    def test_thinking_scope_does_not_trigger_on_text_delta(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher

        rule = self._make_rule("r", "secret_logic", scope="thinking")
        watcher = TtsrStreamWatcher([rule])

        watcher.watch("part_delta", _make_delta_event("TextPartDelta", "using secret_logic"))
        assert rule.pending is False

    def test_tool_scope_triggers_on_tool_delta(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher

        rule = self._make_rule("r", "rm -rf", scope="tool")
        watcher = TtsrStreamWatcher([rule])

        watcher.watch("part_delta", _make_delta_event("ToolCallPartDelta", "rm -rf /tmp"))
        assert rule.pending is True

    def test_tool_scope_does_not_trigger_on_text(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher

        rule = self._make_rule("r", "rm -rf", scope="tool")
        watcher = TtsrStreamWatcher([rule])

        watcher.watch("part_delta", _make_delta_event("TextPartDelta", "rm -rf /tmp"))
        assert rule.pending is False

    def test_all_scope_triggers_on_any_delta(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher

        for delta_type in ("TextPartDelta", "ThinkingPartDelta", "ToolCallPartDelta"):
            rule = self._make_rule("r", "keyword", scope="all")
            watcher = TtsrStreamWatcher([rule])
            watcher.watch("part_delta", _make_delta_event(delta_type, "keyword"))
            assert rule.pending is True, f"Expected pending for {delta_type}"

    def test_non_part_delta_events_ignored(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher

        rule = self._make_rule("r", "keyword")
        watcher = TtsrStreamWatcher([rule])

        watcher.watch("part_start", {"something": "keyword"})
        watcher.watch("part_end", {"something": "keyword"})
        assert rule.pending is False

    def test_repeat_once_prevents_re_trigger(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher

        rule = self._make_rule("r", "keyword", repeat="once")
        watcher = TtsrStreamWatcher([rule])

        # Fire and mark injected
        watcher.watch("part_delta", _make_delta_event("TextPartDelta", "keyword"))
        assert rule.pending is True
        watcher.mark_injected(rule, 1)
        assert rule.pending is False
        assert rule.triggered_at_turn == 1

        # Advance turn and try again
        watcher.increment_turn()
        watcher.watch("part_delta", _make_delta_event("TextPartDelta", "keyword"))
        assert rule.pending is False  # "once" — should NOT re-trigger

    def test_repeat_gap_allows_retrigger_after_n_turns(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher

        rule = self._make_rule("r", "keyword", repeat="gap:3")
        watcher = TtsrStreamWatcher([rule])

        # First trigger
        watcher.watch("part_delta", _make_delta_event("TextPartDelta", "keyword"))
        assert rule.pending is True
        watcher.mark_injected(rule, watcher.turn_count)

        # Not eligible right away (gap=3, turns_since=0)
        watcher.watch("part_delta", _make_delta_event("TextPartDelta", "keyword"))
        assert rule.pending is False

        # Advance 2 turns — still not eligible (turns_since=2 < 3)
        watcher.increment_turn()
        watcher.increment_turn()
        watcher.watch("part_delta", _make_delta_event("TextPartDelta", "keyword"))
        assert rule.pending is False

        # Advance 1 more — now turns_since=3 >= 3, eligible
        watcher.increment_turn()
        watcher.watch("part_delta", _make_delta_event("TextPartDelta", "keyword"))
        assert rule.pending is True

    def test_get_pending_rules_returns_only_pending(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher

        rule_a = self._make_rule("a", "alpha")
        rule_b = self._make_rule("b", "beta")
        watcher = TtsrStreamWatcher([rule_a, rule_b])

        watcher.watch("part_delta", _make_delta_event("TextPartDelta", "alpha here"))

        pending = watcher.get_pending_rules()
        assert len(pending) == 1
        assert pending[0].name == "a"

    def test_mark_injected_clears_pending_and_sets_turn(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher

        rule = self._make_rule("r", "trigger_me")
        watcher = TtsrStreamWatcher([rule])

        watcher.watch("part_delta", _make_delta_event("TextPartDelta", "trigger_me"))
        assert rule.pending is True

        watcher.mark_injected(rule, 42)
        assert rule.pending is False
        assert rule.triggered_at_turn == 42

    def test_turn_count_increments(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher

        watcher = TtsrStreamWatcher([])
        assert watcher.turn_count == 0
        watcher.increment_turn()
        assert watcher.turn_count == 1
        watcher.increment_turn()
        assert watcher.turn_count == 2

    def test_already_pending_rule_not_duplicated(self):
        """A pending rule should not be re-flagged redundantly."""
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher

        rule = self._make_rule("r", "keyword")
        watcher = TtsrStreamWatcher([rule])

        watcher.watch("part_delta", _make_delta_event("TextPartDelta", "keyword"))
        assert rule.pending is True

        # Second watch call should keep it pending (not break anything)
        watcher.watch("part_delta", _make_delta_event("TextPartDelta", "keyword"))
        assert rule.pending is True

    def test_multiple_rules_only_matching_flagged(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher

        rule_a = self._make_rule("a", "alpha")
        rule_b = self._make_rule("b", "beta")
        rule_c = self._make_rule("c", "gamma")
        watcher = TtsrStreamWatcher([rule_a, rule_b, rule_c])

        watcher.watch("part_delta", _make_delta_event("TextPartDelta", "beta is here"))

        assert rule_a.pending is False
        assert rule_b.pending is True
        assert rule_c.pending is False

    def test_empty_delta_content_does_not_trigger(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher

        rule = self._make_rule("r", "keyword")
        watcher = TtsrStreamWatcher([rule])

        watcher.watch("part_delta", _make_delta_event("TextPartDelta", ""))
        assert rule.pending is False

    def test_none_delta_does_not_crash(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher

        rule = self._make_rule("r", "keyword")
        watcher = TtsrStreamWatcher([rule])

        # None delta should be handled gracefully
        watcher.watch("part_delta", {"delta_type": "TextPartDelta", "delta": None})
        assert rule.pending is False

    def test_non_dict_event_data_ignored(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher

        rule = self._make_rule("r", "keyword")
        watcher = TtsrStreamWatcher([rule])

        watcher.watch("part_delta", "not a dict")
        assert rule.pending is False

    def test_partial_match_across_chunks(self):
        """Trigger spanning two chunks should still match via ring buffer."""
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher

        rule = self._make_rule("r", "cross_chunk")
        watcher = TtsrStreamWatcher([rule])

        # Split the matching text across two consecutive deltas
        watcher.watch("part_delta", _make_delta_event("TextPartDelta", "using cross_"))
        assert rule.pending is False  # Incomplete so far

        watcher.watch("part_delta", _make_delta_event("TextPartDelta", "chunk here"))
        assert rule.pending is True  # Ring buffer concatenates them


# ---------------------------------------------------------------------------
# inject_triggered_rules (via register_callbacks)
# ---------------------------------------------------------------------------


class TestInjectTriggeredRules:
    def _make_rule(self, name, trigger_src="trigger", pending=False):
        from code_puppy.plugins.ttsr.rule_loader import TtsrRule

        rule = TtsrRule(
            name=name,
            trigger=re.compile(trigger_src),
            content=f"Rule content for {name}.",
            scope="text",
            repeat="once",
            source_path=Path(f"/fake/{name}.md"),
        )
        rule.pending = pending
        return rule

    def test_no_pending_returns_none(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher
        import code_puppy.plugins.ttsr.register_callbacks as rc

        watcher = TtsrStreamWatcher([self._make_rule("r", pending=False)])
        with patch.object(rc, "_watcher", watcher):
            result = rc.inject_triggered_rules()
        assert result is None

    def test_pending_rule_injected_in_system_rule_block(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher
        import code_puppy.plugins.ttsr.register_callbacks as rc

        rule = self._make_rule("my-rule", pending=True)
        watcher = TtsrStreamWatcher([rule])
        with patch.object(rc, "_watcher", watcher):
            result = rc.inject_triggered_rules()

        assert result is not None
        assert '<system-rule name="my-rule">' in result
        assert "Rule content for my-rule." in result
        assert "</system-rule>" in result

    def test_inject_clears_pending(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher
        import code_puppy.plugins.ttsr.register_callbacks as rc

        rule = self._make_rule("r", pending=True)
        watcher = TtsrStreamWatcher([rule])
        with patch.object(rc, "_watcher", watcher):
            rc.inject_triggered_rules()

        assert rule.pending is False

    def test_inject_sets_triggered_at_turn(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher
        import code_puppy.plugins.ttsr.register_callbacks as rc

        rule = self._make_rule("r", pending=True)
        watcher = TtsrStreamWatcher([rule])
        # Advance to turn 7
        for _ in range(7):
            watcher.increment_turn()

        with patch.object(rc, "_watcher", watcher):
            rc.inject_triggered_rules()

        assert rule.triggered_at_turn == 7

    def test_multiple_pending_all_injected(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher
        import code_puppy.plugins.ttsr.register_callbacks as rc

        rules = [self._make_rule(f"rule-{i}", pending=True) for i in range(3)]
        watcher = TtsrStreamWatcher(rules)
        with patch.object(rc, "_watcher", watcher):
            result = rc.inject_triggered_rules()

        assert result is not None
        for i in range(3):
            assert f'name="rule-{i}"' in result
        for rule in rules:
            assert rule.pending is False

    def test_only_pending_rules_injected(self):
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher
        import code_puppy.plugins.ttsr.register_callbacks as rc

        pending_rule = self._make_rule("pending", pending=True)
        quiet_rule = self._make_rule("quiet", pending=False)
        watcher = TtsrStreamWatcher([pending_rule, quiet_rule])
        with patch.object(rc, "_watcher", watcher):
            result = rc.inject_triggered_rules()

        assert 'name="pending"' in result
        assert 'name="quiet"' not in result


# ---------------------------------------------------------------------------
# load_rules (startup hook)
# ---------------------------------------------------------------------------


class TestLoadRules:
    def test_loads_from_project_and_user_dirs(self, tmp_path):
        import code_puppy.plugins.ttsr.register_callbacks as rc

        project_rules = tmp_path / ".code_puppy" / "rules"
        user_rules = tmp_path / "home" / ".code_puppy" / "rules"
        project_rules.mkdir(parents=True)
        user_rules.mkdir(parents=True)

        _write_rule(project_rules, "proj.md", "name: proj\ntrigger: proj_pat", "Project rule.")
        _write_rule(user_rules, "user.md", "name: user\ntrigger: user_pat", "User rule.")

        with (
            patch("code_puppy.plugins.ttsr.register_callbacks._rule_directories",
                  return_value=[project_rules, user_rules]),
        ):
            rc.load_rules()

        watcher = rc._get_watcher()
        names = {r.name for r in watcher.rules}
        assert "proj" in names
        assert "user" in names

    def test_no_rules_dirs_leaves_empty_watcher(self, tmp_path):
        import code_puppy.plugins.ttsr.register_callbacks as rc

        with patch(
            "code_puppy.plugins.ttsr.register_callbacks._rule_directories",
            return_value=[tmp_path / "nonexistent"],
        ):
            rc.load_rules()

        watcher = rc._get_watcher()
        assert watcher.rules == []


# ---------------------------------------------------------------------------
# handle_ttsr_command
# ---------------------------------------------------------------------------


class TestHandleTtsrCommand:
    def test_returns_none_for_other_commands(self):
        from code_puppy.plugins.ttsr.register_callbacks import handle_ttsr_command

        assert handle_ttsr_command("/other", "other") is None
        assert handle_ttsr_command("/help", "help") is None

    def test_returns_true_for_ttsr_command(self):
        from code_puppy.plugins.ttsr.register_callbacks import handle_ttsr_command
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher
        import code_puppy.plugins.ttsr.register_callbacks as rc

        watcher = TtsrStreamWatcher([])
        with (
            patch.object(rc, "_watcher", watcher),
            patch("code_puppy.plugins.ttsr.register_callbacks.emit_info") if False
            else patch("code_puppy.messaging.emit_info"),
            patch("code_puppy.messaging.emit_warning"),
        ):
            result = handle_ttsr_command("/ttsr", "ttsr")

        assert result is True

    def test_shows_rule_info(self):
        import re as re_mod
        from code_puppy.plugins.ttsr.rule_loader import TtsrRule
        from code_puppy.plugins.ttsr.register_callbacks import handle_ttsr_command
        from code_puppy.plugins.ttsr.stream_watcher import TtsrStreamWatcher
        import code_puppy.plugins.ttsr.register_callbacks as rc

        rule = TtsrRule(
            name="show-me",
            trigger=re_mod.compile("some_trigger"),
            content="Content.",
            scope="text",
            repeat="once",
            source_path=Path("/fake/show-me.md"),
        )
        watcher = TtsrStreamWatcher([rule])

        emitted: list[str] = []
        with (
            patch.object(rc, "_watcher", watcher),
            patch("code_puppy.messaging.emit_info", side_effect=lambda x: emitted.append(str(x))),
            patch("code_puppy.messaging.emit_warning"),
        ):
            handle_ttsr_command("/ttsr", "ttsr")

        combined = " ".join(emitted)
        assert "show-me" in combined
        assert "some_trigger" in combined


# ---------------------------------------------------------------------------
# ttsr_help
# ---------------------------------------------------------------------------


class TestTtsrHelp:
    def test_returns_ttsr_help_entry(self):
        from code_puppy.plugins.ttsr.register_callbacks import ttsr_help

        result = ttsr_help()
        assert isinstance(result, list)
        assert len(result) == 1
        name, desc = result[0]
        assert name == "ttsr"
        assert "rule" in desc.lower() or "ttsr" in desc.lower()


# ---------------------------------------------------------------------------
# Callback registrations
# ---------------------------------------------------------------------------


class TestCallbackRegistrations:
    def test_callbacks_registered(self):
        from code_puppy import callbacks

        # Import the module to ensure registrations fire
        import code_puppy.plugins.ttsr.register_callbacks  # noqa: F401

        assert callbacks.count_callbacks("startup") > 0
        assert callbacks.count_callbacks("stream_event") > 0
        assert callbacks.count_callbacks("load_prompt") > 0
        assert callbacks.count_callbacks("agent_run_end") > 0
        assert callbacks.count_callbacks("custom_command") > 0
        assert callbacks.count_callbacks("custom_command_help") > 0
