"""Regression tests for modules that consume config paths at runtime.

These modules used to capture config paths at import time, which broke
late PUP_EX_HOME activation in tests and pup-ex mode.
"""

def _clear_config_lazy_exports(cp_config) -> None:
    for attr in (
        "CONFIG_DIR",
        "DATA_DIR",
        "CACHE_DIR",
        "STATE_DIR",
        "CONFIG_FILE",
        "MCP_SERVERS_FILE",
        "MODELS_FILE",
        "EXTRA_MODELS_FILE",
        "AGENTS_DIR",
        "SKILLS_DIR",
        "CONTEXTS_DIR",
        "CHATGPT_MODELS_FILE",
        "CLAUDE_MODELS_FILE",
        "AUTOSAVE_DIR",
        "COMMAND_HISTORY_FILE",
        "DBOS_DATABASE_URL",
    ):
        cp_config.__dict__.pop(attr, None)


def test_interactive_loop_helpers_follow_late_pup_ex_env(monkeypatch, tmp_path):
    from code_puppy import config as cp_config
    from code_puppy import interactive_loop

    monkeypatch.delenv("PUP_EX_HOME", raising=False)
    _clear_config_lazy_exports(cp_config)
    baseline_history = str(interactive_loop._command_history_file())
    baseline_autosave = str(interactive_loop._autosave_dir())

    ex_home = tmp_path / "late_interactive_home"
    monkeypatch.setenv("PUP_EX_HOME", str(ex_home))
    _clear_config_lazy_exports(cp_config)

    assert str(interactive_loop._command_history_file()).startswith(str(ex_home))
    assert str(interactive_loop._autosave_dir()).startswith(str(ex_home))
    assert str(interactive_loop._command_history_file()) != baseline_history
    assert str(interactive_loop._autosave_dir()) != baseline_autosave


def test_interactive_loop_helpers_honor_explicit_module_overrides(monkeypatch):
    from code_puppy import interactive_loop

    monkeypatch.setattr(
        interactive_loop,
        "COMMAND_HISTORY_FILE",
        "/tmp/interactive-history.txt",
        raising=False,
    )
    monkeypatch.setattr(
        interactive_loop,
        "AUTOSAVE_DIR",
        "/tmp/interactive-autosaves",
        raising=False,
    )

    assert interactive_loop._command_history_file() == "/tmp/interactive-history.txt"
    assert interactive_loop._autosave_dir() == "/tmp/interactive-autosaves"


def test_repl_session_paths_follow_late_pup_ex_env(monkeypatch, tmp_path):
    from code_puppy import config as cp_config
    from code_puppy import repl_session

    monkeypatch.delenv("PUP_EX_HOME", raising=False)
    _clear_config_lazy_exports(cp_config)
    baseline_state_dir = str(repl_session._repl_state_dir())
    baseline_state_file = str(repl_session._repl_state_file())
    baseline_history_file = str(repl_session._repl_history_file())

    ex_home = tmp_path / "late_repl_home"
    monkeypatch.setenv("PUP_EX_HOME", str(ex_home))
    _clear_config_lazy_exports(cp_config)

    assert str(repl_session._repl_state_dir()).startswith(str(ex_home))
    assert str(repl_session._repl_state_file()).startswith(str(ex_home))
    assert str(repl_session._repl_history_file()).startswith(str(ex_home))
    assert str(repl_session._repl_state_dir()) != baseline_state_dir
    assert str(repl_session._repl_state_file()) != baseline_state_file
    assert str(repl_session._repl_history_file()) != baseline_history_file


def test_repl_session_ensure_state_dir_uses_runtime_cache_dir(monkeypatch, tmp_path):
    from code_puppy import config as cp_config
    from code_puppy import repl_session

    ex_home = tmp_path / "repl_runtime_home"
    monkeypatch.setenv("PUP_EX_HOME", str(ex_home))
    _clear_config_lazy_exports(cp_config)

    state_dir = repl_session.get_repl_state_dir()

    assert state_dir == repl_session._repl_state_dir()
    assert str(state_dir).startswith(str(ex_home))
    assert state_dir.is_dir()
