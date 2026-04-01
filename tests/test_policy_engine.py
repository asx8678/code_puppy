"""Tests for the PolicyEngine."""

import json
import pytest
from code_puppy.permission_decision import Allow, AskUser, Deny
from code_puppy.policy_engine import PolicyEngine, PolicyRule


@pytest.fixture
def engine():
    return PolicyEngine(default_decision="ask_user")


def test_default_decision_ask_user(engine):
    result = engine.check("unknown_tool")
    assert isinstance(result, AskUser)


def test_default_decision_allow():
    eng = PolicyEngine(default_decision="allow")
    result = eng.check("anything")
    assert isinstance(result, Allow)


def test_allow_rule_matches(engine):
    engine.add_rule(PolicyRule(tool_name="read_file", decision="allow"))
    result = engine.check("read_file")
    assert isinstance(result, Allow)


def test_deny_rule_matches(engine):
    engine.add_rule(PolicyRule(tool_name="delete_file", decision="deny"))
    result = engine.check("delete_file")
    assert isinstance(result, Deny)
    assert "policy" in result.reason.lower()


def test_unmatched_tool_falls_to_default(engine):
    engine.add_rule(PolicyRule(tool_name="read_file", decision="allow"))
    result = engine.check("write_file")
    assert isinstance(result, AskUser)


def test_priority_ordering(engine):
    engine.add_rule(PolicyRule(tool_name="*", decision="deny", priority=10))
    engine.add_rule(PolicyRule(tool_name="*", decision="allow", priority=20))
    result = engine.check("anything")
    assert isinstance(result, Allow)  # priority 20 wins


def test_wildcard_matches_all(engine):
    engine.add_rule(PolicyRule(tool_name="*", decision="allow"))
    assert isinstance(engine.check("read_file"), Allow)
    assert isinstance(engine.check("write_file"), Allow)
    assert isinstance(engine.check("run_shell_command"), Allow)


def test_command_pattern_matching(engine):
    engine.add_rule(PolicyRule(
        tool_name="run_shell_command",
        command_pattern=r"^git\b",
        decision="allow",
        priority=10,
    ))
    engine.add_rule(PolicyRule(
        tool_name="run_shell_command",
        command_pattern=r"^rm\b",
        decision="deny",
        priority=10,
    ))
    assert isinstance(engine.check("run_shell_command", {"command": "git status"}), Allow)
    assert isinstance(engine.check("run_shell_command", {"command": "rm -rf /"}), Deny)
    # No pattern match → default
    assert isinstance(engine.check("run_shell_command", {"command": "ls"}), AskUser)


def test_compound_shell_deny_on_any(engine):
    engine.add_rule(PolicyRule(
        tool_name="run_shell_command",
        command_pattern=r"^sudo\b",
        decision="deny",
        priority=100,
    ))
    engine.add_rule(PolicyRule(
        tool_name="run_shell_command",
        decision="allow",
        priority=1,
    ))
    result = engine.check_shell_command("echo hi && sudo rm -rf /")
    assert isinstance(result, Deny)


def test_compound_shell_all_allowed(engine):
    engine.add_rule(PolicyRule(
        tool_name="run_shell_command",
        decision="allow",
        priority=1,
    ))
    result = engine.check_shell_command("echo a && echo b")
    assert isinstance(result, Allow)


def test_load_rules_from_file(tmp_path):
    rules_file = tmp_path / "policy.json"
    rules_file.write_text(json.dumps({"rules": [
        {"tool_name": "read_file", "decision": "allow", "priority": 5},
        {"tool_name": "delete_file", "decision": "deny", "priority": 10},
    ]}))
    engine = PolicyEngine()
    count = engine.load_rules_from_file(rules_file, source="test")
    assert count == 2
    assert len(engine.rules) == 2
    assert engine.rules[0].priority == 10  # sorted desc


def test_load_rules_missing_file():
    engine = PolicyEngine()
    from pathlib import Path
    count = engine.load_rules_from_file(Path("/nonexistent/policy.json"))
    assert count == 0


def test_remove_rules_by_source(engine):
    engine.add_rule(PolicyRule(tool_name="a", decision="allow", source="user"))
    engine.add_rule(PolicyRule(tool_name="b", decision="allow", source="project"))
    engine.remove_rules_by_source("user")
    assert len(engine.rules) == 1
    assert engine.rules[0].tool_name == "b"


def test_args_pattern_matching(engine):
    engine.add_rule(PolicyRule(
        tool_name="run_shell_command",
        args_pattern=r'"dangerous"',
        decision="deny",
    ))
    assert isinstance(
        engine.check("run_shell_command", {"command": "echo", "flag": "dangerous"}),
        Deny,
    )
    assert isinstance(
        engine.check("run_shell_command", {"command": "echo", "flag": "safe"}),
        AskUser,
    )
