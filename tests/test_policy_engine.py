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


# ---------------------------------------------------------------------------
# check_explicit — only explicit rules, no default fallback
# ---------------------------------------------------------------------------

def test_check_explicit_returns_none_when_no_rule():
    """check_explicit returns None when no rule matches (no default fallback)."""
    eng = PolicyEngine(default_decision="allow")  # default irrelevant
    assert eng.check_explicit("anything") is None


def test_check_explicit_returns_allow_when_matched():
    eng = PolicyEngine()
    eng.add_rule(PolicyRule(tool_name="read_file", decision="allow"))
    result = eng.check_explicit("read_file")
    assert isinstance(result, Allow)


def test_check_explicit_returns_deny_when_matched():
    eng = PolicyEngine()
    eng.add_rule(PolicyRule(tool_name="delete_file", decision="deny"))
    result = eng.check_explicit("delete_file")
    assert isinstance(result, Deny)


def test_check_explicit_no_match_different_tool():
    eng = PolicyEngine()
    eng.add_rule(PolicyRule(tool_name="read_file", decision="allow"))
    assert eng.check_explicit("write_file") is None


def test_check_explicit_wildcard():
    eng = PolicyEngine()
    eng.add_rule(PolicyRule(tool_name="*", decision="allow"))
    assert isinstance(eng.check_explicit("anything"), Allow)


# ---------------------------------------------------------------------------
# check_shell_command_explicit — explicit rules for shell cmds
# ---------------------------------------------------------------------------

def test_check_shell_command_explicit_no_rules_returns_none():
    """With no rules, check_shell_command_explicit returns None."""
    eng = PolicyEngine(default_decision="allow")
    assert eng.check_shell_command_explicit("git status") is None


def test_check_shell_command_explicit_allow_rule():
    eng = PolicyEngine()
    eng.add_rule(PolicyRule(
        tool_name="run_shell_command",
        command_pattern=r"^git\b",
        decision="allow",
    ))
    result = eng.check_shell_command_explicit("git status")
    assert isinstance(result, Allow)


def test_check_shell_command_explicit_deny_rule():
    eng = PolicyEngine()
    eng.add_rule(PolicyRule(
        tool_name="run_shell_command",
        command_pattern=r"^rm\b",
        decision="deny",
    ))
    result = eng.check_shell_command_explicit("rm -rf /")
    assert isinstance(result, Deny)


def test_check_shell_command_explicit_compound_deny_one():
    """One sub-command denied → whole compound denied."""
    eng = PolicyEngine()
    eng.add_rule(PolicyRule(
        tool_name="run_shell_command",
        command_pattern=r"^sudo\b",
        decision="deny",
    ))
    eng.add_rule(PolicyRule(
        tool_name="run_shell_command",
        command_pattern=r"^echo\b",
        decision="allow",
    ))
    result = eng.check_shell_command_explicit("echo hi && sudo rm -rf /")
    assert isinstance(result, Deny)


def test_check_shell_command_explicit_compound_no_match():
    """No rules match any sub-command → returns None."""
    eng = PolicyEngine()
    eng.add_rule(PolicyRule(tool_name="read_file", decision="allow"))
    result = eng.check_shell_command_explicit("git status && git push")
    assert result is None


# ---------------------------------------------------------------------------
# policy_config — load rules from files
# ---------------------------------------------------------------------------

def test_policy_config_load_rules(tmp_path):
    """policy_config.load_policy_rules populates the engine from JSON files."""
    import json
    from code_puppy.policy_config import load_policy_rules

    user_file = tmp_path / "user_policy.json"
    proj_file = tmp_path / "proj_policy.json"

    user_file.write_text(json.dumps({"rules": [
        {"tool_name": "read_file", "decision": "allow", "priority": 5},
    ]}))
    proj_file.write_text(json.dumps({"rules": [
        {"tool_name": "delete_file", "decision": "deny", "priority": 10},
    ]}))

    eng = PolicyEngine()
    count = load_policy_rules(eng, user_policy=user_file, project_policy=proj_file)

    assert count == 2
    assert isinstance(eng.check("read_file"), Allow)
    assert isinstance(eng.check("delete_file"), Deny)


def test_policy_config_missing_files_ok(tmp_path):
    """load_policy_rules silently ignores missing files, returns 0."""
    from code_puppy.policy_config import load_policy_rules

    eng = PolicyEngine()
    count = load_policy_rules(
        eng,
        user_policy=tmp_path / "nonexistent.json",
        project_policy=tmp_path / "also_missing.json",
    )
    assert count == 0
    assert len(eng.rules) == 0


def test_policy_config_project_overrides_user(tmp_path):
    """Project rules (higher priority) win over user rules."""
    import json
    from code_puppy.policy_config import load_policy_rules

    user_file = tmp_path / "user.json"
    proj_file = tmp_path / "proj.json"

    # User says allow, project says deny (higher priority)
    user_file.write_text(json.dumps({"rules": [
        {"tool_name": "sensitive_tool", "decision": "allow", "priority": 5},
    ]}))
    proj_file.write_text(json.dumps({"rules": [
        {"tool_name": "sensitive_tool", "decision": "deny", "priority": 20},
    ]}))

    eng = PolicyEngine(default_decision="ask_user")
    load_policy_rules(eng, user_policy=user_file, project_policy=proj_file)

    # Higher-priority project rule wins
    assert isinstance(eng.check("sensitive_tool"), Deny)
