"""Tests for the PolicyEngine."""

import json
import pytest
from code_puppy.permission_decision import Allow, AskUser, Deny
from code_puppy.policy_engine import PolicyEngine, PolicyRule


@pytest.fixture
def engine():
    return PolicyEngine(default_decision="ask_user")


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_default_decision_ask_user(engine):
    result = engine.check("unknown_tool")
    assert isinstance(result, AskUser)


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_default_decision_allow():
    eng = PolicyEngine(default_decision="allow")
    result = eng.check("anything")
    assert isinstance(result, Allow)


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_allow_rule_matches(engine):
    engine.add_rule(PolicyRule(tool_name="read_file", decision="allow"))
    result = engine.check("read_file")
    assert isinstance(result, Allow)


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_deny_rule_matches(engine):
    engine.add_rule(PolicyRule(tool_name="delete_file", decision="deny"))
    result = engine.check("delete_file")
    assert isinstance(result, Deny)
    assert "policy" in result.reason.lower()


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_unmatched_tool_falls_to_default(engine):
    engine.add_rule(PolicyRule(tool_name="read_file", decision="allow"))
    result = engine.check("write_file")
    assert isinstance(result, AskUser)


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_priority_ordering(engine):
    engine.add_rule(PolicyRule(tool_name="*", decision="deny", priority=10))
    engine.add_rule(PolicyRule(tool_name="*", decision="allow", priority=20))
    result = engine.check("anything")
    assert isinstance(result, Allow)  # priority 20 wins


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_wildcard_matches_all(engine):
    engine.add_rule(PolicyRule(tool_name="*", decision="allow"))
    assert isinstance(engine.check("read_file"), Allow)
    assert isinstance(engine.check("write_file"), Allow)
    assert isinstance(engine.check("run_shell_command"), Allow)


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_command_pattern_matching(engine):
    engine.add_rule(
        PolicyRule(
            tool_name="run_shell_command",
            command_pattern=r"^git\b",
            decision="allow",
            priority=10,
        )
    )
    engine.add_rule(
        PolicyRule(
            tool_name="run_shell_command",
            command_pattern=r"^rm\b",
            decision="deny",
            priority=10,
        )
    )
    assert isinstance(
        engine.check("run_shell_command", {"command": "git status"}), Allow
    )
    assert isinstance(engine.check("run_shell_command", {"command": "rm -rf /"}), Deny)
    # No pattern match → default
    assert isinstance(engine.check("run_shell_command", {"command": "ls"}), AskUser)


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_compound_shell_deny_on_any(engine):
    engine.add_rule(
        PolicyRule(
            tool_name="run_shell_command",
            command_pattern=r"^sudo\b",
            decision="deny",
            priority=100,
        )
    )
    engine.add_rule(
        PolicyRule(
            tool_name="run_shell_command",
            decision="allow",
            priority=1,
        )
    )
    result = engine.check_shell_command("echo hi && sudo rm -rf /")
    assert isinstance(result, Deny)


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_compound_shell_all_allowed(engine):
    engine.add_rule(
        PolicyRule(
            tool_name="run_shell_command",
            decision="allow",
            priority=1,
        )
    )
    result = engine.check_shell_command("echo a && echo b")
    assert isinstance(result, Allow)


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_load_rules_from_file(tmp_path):
    rules_file = tmp_path / "policy.json"
    rules_file.write_text(
        json.dumps(
            {
                "rules": [
                    {"tool_name": "read_file", "decision": "allow", "priority": 5},
                    {"tool_name": "delete_file", "decision": "deny", "priority": 10},
                ]
            }
        )
    )
    engine = PolicyEngine()
    count = engine.load_rules_from_file(rules_file, source="test")
    assert count == 2
    assert len(engine.rules) == 2
    assert engine.rules[0].priority == 10  # sorted desc


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_load_rules_missing_file():
    engine = PolicyEngine()
    from pathlib import Path

    count = engine.load_rules_from_file(Path("/nonexistent/policy.json"))
    assert count == 0


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_remove_rules_by_source(engine):
    engine.add_rule(PolicyRule(tool_name="a", decision="allow", source="user"))
    engine.add_rule(PolicyRule(tool_name="b", decision="allow", source="project"))
    engine.remove_rules_by_source("user")
    assert len(engine.rules) == 1
    assert engine.rules[0].tool_name == "b"


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_args_pattern_matching(engine):
    engine.add_rule(
        PolicyRule(
            tool_name="run_shell_command",
            args_pattern=r'"dangerous"',
            decision="deny",
        )
    )
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


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_check_explicit_returns_none_when_no_rule():
    """check_explicit returns None when no rule matches (no default fallback)."""
    eng = PolicyEngine(default_decision="allow")  # default irrelevant
    assert eng.check_explicit("anything") is None


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_check_explicit_returns_allow_when_matched():
    eng = PolicyEngine()
    eng.add_rule(PolicyRule(tool_name="read_file", decision="allow"))
    result = eng.check_explicit("read_file")
    assert isinstance(result, Allow)


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_check_explicit_returns_deny_when_matched():
    eng = PolicyEngine()
    eng.add_rule(PolicyRule(tool_name="delete_file", decision="deny"))
    result = eng.check_explicit("delete_file")
    assert isinstance(result, Deny)


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_check_explicit_no_match_different_tool():
    eng = PolicyEngine()
    eng.add_rule(PolicyRule(tool_name="read_file", decision="allow"))
    assert eng.check_explicit("write_file") is None


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_check_explicit_wildcard():
    eng = PolicyEngine()
    eng.add_rule(PolicyRule(tool_name="*", decision="allow"))
    assert isinstance(eng.check_explicit("anything"), Allow)


# ---------------------------------------------------------------------------
# check_shell_command_explicit — explicit rules for shell cmds
# ---------------------------------------------------------------------------


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_check_shell_command_explicit_no_rules_returns_none():
    """With no rules, check_shell_command_explicit returns None."""
    eng = PolicyEngine(default_decision="allow")
    assert eng.check_shell_command_explicit("git status") is None


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_check_shell_command_explicit_allow_rule():
    eng = PolicyEngine()
    eng.add_rule(
        PolicyRule(
            tool_name="run_shell_command",
            command_pattern=r"^git\b",
            decision="allow",
        )
    )
    result = eng.check_shell_command_explicit("git status")
    assert isinstance(result, Allow)


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_check_shell_command_explicit_deny_rule():
    eng = PolicyEngine()
    eng.add_rule(
        PolicyRule(
            tool_name="run_shell_command",
            command_pattern=r"^rm\b",
            decision="deny",
        )
    )
    result = eng.check_shell_command_explicit("rm -rf /")
    assert isinstance(result, Deny)


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_check_shell_command_explicit_compound_deny_one():
    """One sub-command denied → whole compound denied."""
    eng = PolicyEngine()
    eng.add_rule(
        PolicyRule(
            tool_name="run_shell_command",
            command_pattern=r"^sudo\b",
            decision="deny",
        )
    )
    eng.add_rule(
        PolicyRule(
            tool_name="run_shell_command",
            command_pattern=r"^echo\b",
            decision="allow",
        )
    )
    result = eng.check_shell_command_explicit("echo hi && sudo rm -rf /")
    assert isinstance(result, Deny)


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_check_shell_command_explicit_compound_no_match():
    """No rules match any sub-command → returns None."""
    eng = PolicyEngine()
    eng.add_rule(PolicyRule(tool_name="read_file", decision="allow"))
    result = eng.check_shell_command_explicit("git status && git push")
    assert result is None


# ---------------------------------------------------------------------------
# policy_config — load rules from files
# ---------------------------------------------------------------------------


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_policy_config_load_rules(tmp_path):
    """policy_config.load_policy_rules populates the engine from JSON files."""
    import json
    from code_puppy.policy_config import load_policy_rules

    user_file = tmp_path / "user_policy.json"
    proj_file = tmp_path / "proj_policy.json"

    user_file.write_text(
        json.dumps(
            {
                "rules": [
                    {"tool_name": "read_file", "decision": "allow", "priority": 5},
                ]
            }
        )
    )
    proj_file.write_text(
        json.dumps(
            {
                "rules": [
                    {"tool_name": "delete_file", "decision": "deny", "priority": 10},
                ]
            }
        )
    )

    eng = PolicyEngine()
    count = load_policy_rules(eng, user_policy=user_file, project_policy=proj_file)

    assert count == 2
    assert isinstance(eng.check("read_file"), Allow)
    assert isinstance(eng.check("delete_file"), Deny)


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
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


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_policy_config_project_overrides_user(tmp_path):
    """Project rules (higher priority) win over user rules."""
    import json
    from code_puppy.policy_config import load_policy_rules

    user_file = tmp_path / "user.json"
    proj_file = tmp_path / "proj.json"

    # User says allow, project says deny (higher priority)
    user_file.write_text(
        json.dumps(
            {
                "rules": [
                    {"tool_name": "sensitive_tool", "decision": "allow", "priority": 5},
                ]
            }
        )
    )
    proj_file.write_text(
        json.dumps(
            {
                "rules": [
                    {"tool_name": "sensitive_tool", "decision": "deny", "priority": 20},
                ]
            }
        )
    )

    eng = PolicyEngine(default_decision="ask_user")
    load_policy_rules(eng, user_policy=user_file, project_policy=proj_file)

    # Higher-priority project rule wins
    assert isinstance(eng.check("sensitive_tool"), Deny)


# ---------------------------------------------------------------------------
# PolicyRule regex compilation tests
# ---------------------------------------------------------------------------


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_policy_rule_with_regex_pattern_compiles():
    """Regression test: PolicyRule with command_pattern should compile without error."""
    rule = PolicyRule(
        tool_name="run_shell_command",
        command_pattern=r"^git\b",
        decision="allow",
    )
    assert rule._compiled_command is not None


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_policy_rule_with_args_pattern_compiles():
    """Regression test: PolicyRule with args_pattern should compile without error."""
    rule = PolicyRule(
        tool_name="run_shell_command",
        args_pattern=r"dangerous",
        decision="deny",
    )
    assert rule._compiled_args is not None


# ---------------------------------------------------------------------------
# Concurrency regression test — singleton thread-safety
# ---------------------------------------------------------------------------


@pytest.mark.serial
@pytest.mark.xdist_group(name="timing")
def test_get_policy_engine_singleton_thread_safety(tmp_path, monkeypatch):
    """
    Regression test for code_puppy-68x.4: publication order bug.

    Proves that:
    1. Multiple threads calling get_policy_engine() get the same instance
    2. No thread can observe an engine before policy loading completes
    3. All threads see fully initialized engine with all rules loaded
    """
    import json
    import threading
    import time
    from code_puppy import policy_engine
    from code_puppy.policy_config import load_policy_rules

    # Reset singleton state before test
    policy_engine._engine = None

    # Create a policy file with one rule
    proj_file = tmp_path / "policy.json"
    proj_file.write_text(
        json.dumps(
            {
                "rules": [
                    {"tool_name": "test_tool", "decision": "allow", "priority": 10},
                ]
            }
        )
    )

    # Mock load_policy_rules at the policy_config module level
    # (that's where get_policy_engine imports it from)
    original_load = load_policy_rules
    load_started = threading.Event()
    load_completed = threading.Event()

    def slow_load_policy_rules(engine, user_policy=None, project_policy=None):
        load_started.set()
        # Small delay to widen the race window
        time.sleep(0.05)
        result = original_load(
            engine, user_policy=user_policy, project_policy=project_policy or proj_file
        )
        load_completed.set()
        return result

    monkeypatch.setattr(
        "code_puppy.policy_config.load_policy_rules", slow_load_policy_rules
    )

    # Track what each thread observes
    results = {"instances": [], "rule_counts": [], "second_call_instances": []}
    results_lock = threading.Lock()
    barrier = threading.Barrier(5)  # 5 threads start simultaneously

    def racer():
        # All threads wait here, then race to call get_policy_engine()
        barrier.wait()
        engine = policy_engine.get_policy_engine()
        with results_lock:
            results["instances"].append(id(engine))
            results["rule_counts"].append(len(engine.rules))
        # Second call should return same instance
        engine2 = policy_engine.get_policy_engine()
        with results_lock:
            results["second_call_instances"].append(id(engine2))

    threads = [threading.Thread(target=racer) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Verify all threads got the SAME instance
    unique_instances = set(results["instances"])
    assert len(unique_instances) == 1, f"Expected 1 instance, got {len(unique_instances)}"

    # Verify all threads saw the fully initialized engine with 1 rule
    for i, count in enumerate(results["rule_counts"]):
        assert count == 1, f"Thread {i} saw {count} rules, expected 1 (partial init bug!)"

    # Verify second calls return same instance
    for i, inst_id in enumerate(results["second_call_instances"]):
        assert inst_id == results["instances"][i], f"Thread {i} got different instance on second call"

    # Verify load_policy_rules was actually called
    assert load_started.is_set(), "load_policy_rules was never called"
    assert load_completed.is_set(), "load_policy_rules did not complete"

    # Cleanup: reset singleton for other tests
    policy_engine._engine = None
