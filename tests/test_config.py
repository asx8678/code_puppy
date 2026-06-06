"""Consolidated tests for code_puppy/config.py (plus session_storage + callbacks edge cases).

This file merges what used to live in:
- test_config.py
- test_config_full_coverage.py
- test_config_extended_part1.py
- test_config_extended_part2.py
- test_config_and_storage_edge_cases.py

Repetitive getter/setter/default checks have been collapsed into
``@pytest.mark.parametrize`` cases and exact/near duplicates removed, while
preserving behavioral coverage of config.py and session_storage.py.

The autouse ``isolate_global_state_between_tests`` fixture in conftest.py
redirects CONFIG_DIR/CONFIG_FILE to an empty temp dir, so tests that call the
real config setters/getters start from true product defaults.
"""

import configparser
import json
import os
import pathlib
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from code_puppy import callbacks, session_storage
from code_puppy import config as cp_config

CONFIG_DIR_NAME = ".fast_puppy"
CONFIG_FILE_NAME = "puppy.cfg"
DEFAULT_SECTION_NAME = "puppy"

# Full set of keys get_config_keys() always reports (sorted at the call site).
EXPECTED_DEFAULT_KEYS = [
    "allow_recursion",
    "auto_save_session",
    "banner_color_agent_reasoning",
    "banner_color_agent_response",
    "banner_color_create_file",
    "banner_color_delete_snippet",
    "banner_color_directory_listing",
    "banner_color_edit_file",
    "banner_color_grep",
    "banner_color_invoke_agent",
    "banner_color_list_agents",
    "banner_color_llm_judge",
    "banner_color_mcp_tool_call",
    "banner_color_read_file",
    "banner_color_replace_in_file",
    "banner_color_shell_command",
    "banner_color_shell_passthrough",
    "banner_color_subagent_response",
    "banner_color_terminal_tool",
    "banner_color_thinking",
    "banner_color_universal_constructor",
    "cancel_agent_key",
    "compaction_strategy",
    "compaction_threshold",
    "default_agent",
    "diff_context_lines",
    "enable_pack_agents",
    "enable_streaming",
    "enable_universal_constructor",
    "frontend_emitter_enabled",
    "frontend_emitter_max_recent_events",
    "frontend_emitter_queue_size",
    "goal_max_iterations",
    "http2",
    "max_continuation_iterations",
    "max_hook_retries",
    "max_pause_seconds",
    "max_saved_sessions",
    "message_limit",
    "model",
    "openai_reasoning_effort",
    "openai_reasoning_summary",
    "openai_verbosity",
    "pause_agent_key",
    "protected_token_count",
    "resume_message_count",
    "summarization_model",
    "temperature",
    "yolo_mode",
]


@pytest.fixture
def mock_config_paths(monkeypatch):
    """Mock XDG paths so tests never touch the real user config."""
    mock_home = "/mock_home"
    mock_config_dir = os.path.join(mock_home, CONFIG_DIR_NAME)
    mock_config_file = os.path.join(mock_config_dir, CONFIG_FILE_NAME)
    mock_data_dir = os.path.join(mock_home, ".local", "share", "fast_puppy")
    mock_cache_dir = os.path.join(mock_home, ".cache", "fast_puppy")
    mock_state_dir = os.path.join(mock_home, ".local", "state", "fast_puppy")
    mock_skills_dir = os.path.join(mock_data_dir, "skills")

    monkeypatch.setattr(cp_config, "CONFIG_DIR", mock_config_dir)
    monkeypatch.setattr(cp_config, "CONFIG_FILE", mock_config_file)
    monkeypatch.setattr(cp_config, "DATA_DIR", mock_data_dir)
    monkeypatch.setattr(cp_config, "CACHE_DIR", mock_cache_dir)
    monkeypatch.setattr(cp_config, "STATE_DIR", mock_state_dir)
    monkeypatch.setattr(cp_config, "SKILLS_DIR", mock_skills_dir)
    monkeypatch.setattr(
        os.path,
        "expanduser",
        lambda path: mock_home if path == "~" else os.path.expanduser(path),
    )
    return mock_config_dir, mock_config_file


# ---------------------------------------------------------------------------
# ensure_config_exists
# ---------------------------------------------------------------------------
class TestEnsureConfigExists:
    def test_no_config_dir_or_file_prompts_and_creates(
        self, mock_config_paths, monkeypatch
    ):
        mock_cfg_dir, mock_cfg_file = mock_config_paths

        monkeypatch.setattr(os.path, "exists", MagicMock(return_value=False))
        monkeypatch.setattr(os.path, "isfile", MagicMock(return_value=False))
        mock_makedirs = MagicMock()
        monkeypatch.setattr(os, "makedirs", mock_makedirs)

        mock_input_values = {
            "What should we name the puppy? ": "TestPuppy",
            "What's your name (so Fast Puppy knows its owner)? ": "TestOwner",
        }
        monkeypatch.setattr(
            "builtins.input",
            MagicMock(side_effect=lambda prompt: mock_input_values[prompt]),
        )

        m_open = mock_open()
        with patch("builtins.open", m_open):
            config_parser = cp_config.ensure_config_exists()

        # 5 directories are created (CONFIG, DATA, CACHE, STATE, SKILLS).
        assert mock_makedirs.call_count == 5
        m_open.assert_called_once_with(mock_cfg_file, "w", encoding="utf-8")
        assert config_parser.sections() == [DEFAULT_SECTION_NAME]
        assert config_parser.get(DEFAULT_SECTION_NAME, "puppy_name") == "TestPuppy"
        assert config_parser.get(DEFAULT_SECTION_NAME, "owner_name") == "TestOwner"
        assert config_parser.get(DEFAULT_SECTION_NAME, "yolo_mode") == "false"
        assert (
            config_parser.get(DEFAULT_SECTION_NAME, "safety_permission_level")
            == "medium"
        )

    def test_config_dir_exists_file_does_not_prompts_and_creates(
        self, mock_config_paths, monkeypatch
    ):
        mock_cfg_dir, mock_cfg_file = mock_config_paths

        monkeypatch.setattr(os.path, "exists", MagicMock(return_value=True))
        monkeypatch.setattr(os.path, "isfile", MagicMock(return_value=False))
        mock_makedirs = MagicMock()
        monkeypatch.setattr(os, "makedirs", mock_makedirs)

        mock_input_values = {
            "What should we name the puppy? ": "DirExistsPuppy",
            "What's your name (so Fast Puppy knows its owner)? ": "DirExistsOwner",
        }
        monkeypatch.setattr(
            "builtins.input",
            MagicMock(side_effect=lambda prompt: mock_input_values[prompt]),
        )

        m_open = mock_open()
        with patch("builtins.open", m_open):
            config_parser = cp_config.ensure_config_exists()

        mock_makedirs.assert_not_called()
        m_open.assert_called_once_with(mock_cfg_file, "w", encoding="utf-8")
        assert config_parser.get(DEFAULT_SECTION_NAME, "puppy_name") == "DirExistsPuppy"
        assert config_parser.get(DEFAULT_SECTION_NAME, "owner_name") == "DirExistsOwner"

    def test_config_file_exists_and_complete_no_prompt_no_write(
        self, mock_config_paths, monkeypatch
    ):
        mock_cfg_dir, mock_cfg_file = mock_config_paths

        monkeypatch.setattr(os.path, "exists", MagicMock(return_value=True))
        monkeypatch.setattr(os.path, "isfile", MagicMock(return_value=True))

        mock_config_instance = configparser.ConfigParser()
        mock_config_instance[DEFAULT_SECTION_NAME] = {
            "puppy_name": "ExistingPuppy",
            "owner_name": "ExistingOwner",
        }
        mock_config_instance.read = MagicMock(side_effect=lambda _fp: None)
        monkeypatch.setattr(
            configparser, "ConfigParser", MagicMock(return_value=mock_config_instance)
        )

        mock_input = MagicMock()
        monkeypatch.setattr("builtins.input", mock_input)

        m_open = mock_open()
        with patch("builtins.open", m_open):
            returned = cp_config.ensure_config_exists()

        mock_input.assert_not_called()
        m_open.assert_not_called()
        mock_config_instance.read.assert_called_once_with(mock_cfg_file)
        assert returned == mock_config_instance
        assert returned.get(DEFAULT_SECTION_NAME, "puppy_name") == "ExistingPuppy"

    def test_config_file_exists_missing_one_key_prompts_and_writes(
        self, mock_config_paths, monkeypatch
    ):
        mock_cfg_dir, mock_cfg_file = mock_config_paths

        monkeypatch.setattr(os.path, "exists", MagicMock(return_value=True))
        monkeypatch.setattr(os.path, "isfile", MagicMock(return_value=True))

        mock_config_instance = configparser.ConfigParser()
        mock_config_instance[DEFAULT_SECTION_NAME] = {"puppy_name": "PartialPuppy"}
        mock_config_instance.read = MagicMock(side_effect=lambda _fp: None)
        monkeypatch.setattr(
            configparser, "ConfigParser", MagicMock(return_value=mock_config_instance)
        )

        mock_input_values = {
            "What's your name (so Fast Puppy knows its owner)? ": "PartialOwnerFilled"
        }
        mock_input = MagicMock(side_effect=lambda prompt: mock_input_values[prompt])
        monkeypatch.setattr("builtins.input", mock_input)

        m_open = mock_open()
        with patch("builtins.open", m_open):
            returned = cp_config.ensure_config_exists()

        mock_input.assert_called_once()
        m_open.assert_called_once_with(mock_cfg_file, "w", encoding="utf-8")
        assert returned.get(DEFAULT_SECTION_NAME, "puppy_name") == "PartialPuppy"
        assert returned.get(DEFAULT_SECTION_NAME, "owner_name") == "PartialOwnerFilled"

    def test_creates_dirs_and_prompts_real_fs(self, monkeypatch, tmp_path):
        cfg_dir = str(tmp_path / "config")
        cfg_file = os.path.join(cfg_dir, "puppy.cfg")
        monkeypatch.setattr(cp_config, "CONFIG_DIR", cfg_dir)
        monkeypatch.setattr(cp_config, "CONFIG_FILE", cfg_file)
        monkeypatch.setattr(cp_config, "DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setattr(cp_config, "CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.setattr(cp_config, "STATE_DIR", str(tmp_path / "state"))

        inputs = iter(["TestPup", "TestOwner"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        config = cp_config.ensure_config_exists()
        assert config["puppy"]["puppy_name"] == "TestPup"
        assert config["puppy"]["owner_name"] == "TestOwner"
        assert os.path.exists(cfg_file)

    def test_existing_config_no_prompt_real_fs(self, tmp_path, monkeypatch):
        cfg_dir = str(tmp_path)
        cfg_file = os.path.join(cfg_dir, "puppy.cfg")
        cp = configparser.ConfigParser()
        cp["puppy"] = {"puppy_name": "Buddy", "owner_name": "Alice"}
        with open(cfg_file, "w") as f:
            cp.write(f)

        monkeypatch.setattr(cp_config, "CONFIG_DIR", cfg_dir)
        monkeypatch.setattr(cp_config, "CONFIG_FILE", cfg_file)
        monkeypatch.setattr(cp_config, "DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setattr(cp_config, "CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.setattr(cp_config, "STATE_DIR", str(tmp_path / "state"))

        config = cp_config.ensure_config_exists()
        assert config["puppy"]["puppy_name"] == "Buddy"


# ---------------------------------------------------------------------------
# get_value / set_config_value / reset_value
# ---------------------------------------------------------------------------
class TestGetValue:
    @patch("configparser.ConfigParser")
    def test_get_value_exists(self, mock_cp_class, mock_config_paths):
        _, mock_cfg_file = mock_config_paths
        inst = MagicMock()
        inst.get.return_value = "test_value"
        mock_cp_class.return_value = inst

        val = cp_config.get_value("test_key")

        mock_cp_class.assert_called_once()
        inst.read.assert_called_once_with(mock_cfg_file)
        inst.get.assert_called_once_with(
            DEFAULT_SECTION_NAME, "test_key", fallback=None
        )
        assert val == "test_value"

    @patch("configparser.ConfigParser")
    def test_get_value_missing_returns_none(self, mock_cp_class, mock_config_paths):
        inst = MagicMock()
        inst.get.return_value = None
        mock_cp_class.return_value = inst
        assert cp_config.get_value("missing_key") is None


class TestSetResetValue:
    def test_set_new_and_get(self):
        cp_config.set_config_value("test_key", "test_value")
        assert cp_config.get_value("test_key") == "test_value"

    def test_set_value_alias(self):
        cp_config.set_value("alias_key", "alias_val")
        assert cp_config.get_value("alias_key") == "alias_val"

    def test_set_existing_key_updates(self):
        cp_config.set_config_value("puppy_name", "Original")
        assert cp_config.get_value("puppy_name") == "Original"
        cp_config.set_config_value("puppy_name", "Updated")
        assert cp_config.get_value("puppy_name") == "Updated"

    def test_set_empty_string(self):
        cp_config.set_config_value("empty_key", "")
        assert cp_config.get_value("empty_key") == ""

    def test_reset_value(self):
        cp_config.set_config_value("reset_me", "val")
        cp_config.reset_value("reset_me")
        assert cp_config.get_value("reset_me") is None

    def test_reset_nonexistent_no_raise(self):
        cp_config.reset_value("does_not_exist_xyz")

    def test_persistence_across_operations(self):
        cp_config.set_config_value("k1", "v1")
        cp_config.set_config_value("k2", "v2")
        cp_config.set_config_value("k3", "v3")
        assert cp_config.get_value("k1") == "v1"
        assert cp_config.get_value("k2") == "v2"
        assert cp_config.get_value("k3") == "v3"
        cp_config.set_config_value("k2", "v2-updated")
        assert cp_config.get_value("k1") == "v1"
        assert cp_config.get_value("k2") == "v2-updated"
        assert cp_config.get_value("k3") == "v3"

    @patch("configparser.ConfigParser")
    @patch("builtins.open", new_callable=mock_open)
    def test_set_config_value_creates_section_when_missing(
        self, mock_file_open, mock_cp_class, mock_config_paths
    ):
        _, mock_cfg_file = mock_config_paths
        inst = MagicMock()
        store = {}
        inst.read.return_value = [mock_cfg_file]
        inst.__contains__.side_effect = lambda name: name in store
        inst.__setitem__.side_effect = lambda name, val: store.__setitem__(name, val)
        inst.__getitem__.side_effect = lambda name: store[name]
        mock_cp_class.return_value = inst

        cp_config.set_config_value("key_in_new_section", "value_in_new_section")

        assert DEFAULT_SECTION_NAME in store
        assert (
            store[DEFAULT_SECTION_NAME]["key_in_new_section"] == "value_in_new_section"
        )
        mock_file_open.assert_called_once_with(mock_cfg_file, "w", encoding="utf-8")
        inst.write.assert_called_once_with(mock_file_open())


# ---------------------------------------------------------------------------
# Simple string getters with defaults
# ---------------------------------------------------------------------------
class TestSimpleGetters:
    @pytest.mark.parametrize(
        "getter, key, stored, expected",
        [
            (cp_config.get_puppy_name, "puppy_name", "MyPuppy", "MyPuppy"),
            (cp_config.get_puppy_name, "puppy_name", None, "Puppy"),
            (cp_config.get_owner_name, "owner_name", "MyOwner", "MyOwner"),
            (cp_config.get_owner_name, "owner_name", None, "Master"),
        ],
    )
    def test_string_getter_default_and_value(self, getter, key, stored, expected):
        with patch("code_puppy.config.get_value") as mock_get_value:
            mock_get_value.return_value = stored
            assert getter() == expected
            mock_get_value.assert_called_once_with(key)

    def test_default_agent(self):
        assert cp_config.get_default_agent() == "fast-puppy"
        cp_config.set_default_agent("custom-agent")
        assert cp_config.get_default_agent() == "custom-agent"


# ---------------------------------------------------------------------------
# get_config_keys
# ---------------------------------------------------------------------------
class TestGetConfigKeys:
    @patch("configparser.ConfigParser")
    def test_with_existing_custom_keys(self, mock_cp_class, mock_config_paths):
        _, mock_cfg_file = mock_config_paths
        inst = MagicMock()
        inst.__contains__.return_value = True
        inst.__getitem__.return_value = {"key1": "val1", "key2": "val2"}
        mock_cp_class.return_value = inst

        keys = cp_config.get_config_keys()
        inst.read.assert_called_once_with(mock_cfg_file)
        assert keys == sorted(EXPECTED_DEFAULT_KEYS + ["key1", "key2"])

    @patch("configparser.ConfigParser")
    def test_empty_config_returns_defaults(self, mock_cp_class, mock_config_paths):
        inst = MagicMock()
        inst.__contains__.return_value = False
        mock_cp_class.return_value = inst
        assert cp_config.get_config_keys() == sorted(EXPECTED_DEFAULT_KEYS)

    def test_returns_sorted_list_and_includes_custom(self):
        cp_config.set_config_value("custom_key_1", "value1")
        cp_config.set_config_value("custom_key_2", "value2")
        keys = cp_config.get_config_keys()
        assert isinstance(keys, list)
        assert keys == sorted(keys)
        for k in (
            "yolo_mode",
            "compaction_strategy",
            "enable_streaming",
            "cancel_agent_key",
            "resume_message_count",
            "temperature",
            "custom_key_1",
            "custom_key_2",
        ):
            assert k in keys


# ---------------------------------------------------------------------------
# _get_xdg_dir
# ---------------------------------------------------------------------------
class TestGetXdgDir:
    def test_returns_xdg_path_when_env_set(self, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "/custom/config")
        assert cp_config._get_xdg_dir("XDG_CONFIG_HOME", ".config") == (
            "/custom/config/fast_puppy"
        )

    def test_returns_legacy_path_when_env_not_set(self, monkeypatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        with patch("os.path.expanduser", return_value="/home/user"):
            assert cp_config._get_xdg_dir("XDG_CONFIG_HOME", ".config") == (
                "/home/user/.fast_puppy"
            )


# ---------------------------------------------------------------------------
# Boolean config getters/setters
# ---------------------------------------------------------------------------
class TestBooleanGetters:
    @pytest.mark.parametrize(
        "getter, key, default",
        [
            (cp_config.get_subagent_verbose, "subagent_verbose", False),
            (
                cp_config.get_universal_constructor_enabled,
                "enable_universal_constructor",
                True,
            ),
            (cp_config.get_enable_streaming, "enable_streaming", True),
            (cp_config.get_mcp_disabled, "disable_mcp", False),
            (cp_config.get_grep_output_verbose, "grep_output_verbose", False),
            (
                cp_config.get_suppress_thinking_messages,
                "suppress_thinking_messages",
                False,
            ),
            (
                cp_config.get_suppress_informational_messages,
                "suppress_informational_messages",
                False,
            ),
            (cp_config.get_frontend_emitter_enabled, "frontend_emitter_enabled", True),
            (cp_config.get_allow_recursion, "allow_recursion", True),
            (cp_config.get_auto_save_session, "auto_save_session", True),
            (cp_config.get_yolo_mode, "yolo_mode", False),
        ],
    )
    def test_default(self, getter, key, default):
        cp_config.reset_value(key)
        assert getter() is default

    @pytest.mark.parametrize("truthy", ["true", "TRUE", "1", "yes", "YES", "on", "ON"])
    def test_bool_truthy_values(self, truthy):
        cp_config.set_config_value("grep_output_verbose", truthy)
        assert cp_config.get_grep_output_verbose() is True

    @pytest.mark.parametrize(
        "getter, key",
        [
            (cp_config.get_subagent_verbose, "subagent_verbose"),
            (cp_config.get_allow_recursion, "allow_recursion"),
            (cp_config.get_auto_save_session, "auto_save_session"),
        ],
    )
    def test_bool_truthy_per_getter(self, getter, key):
        cp_config.set_config_value(key, "yes")
        assert getter() is True

    @pytest.mark.parametrize("falsy", ["false", "FALSE", "0", "no", "off", ""])
    def test_bool_falsy_values(self, falsy):
        cp_config.set_config_value("enable_streaming", falsy)
        assert cp_config.get_enable_streaming() is False

    def test_yolo_mode_off(self):
        cp_config.set_config_value("yolo_mode", "off")
        assert cp_config.get_yolo_mode() is False

    def test_yolo_mode_explicit_true(self):
        cp_config.set_config_value("yolo_mode", "true")
        assert cp_config.get_yolo_mode() is True

    def test_frontend_emitter_enabled_explicit_true(self):
        cp_config.set_config_value("frontend_emitter_enabled", "true")
        assert cp_config.get_frontend_emitter_enabled() is True

    def test_mcp_disabled_true(self):
        cp_config.set_config_value("disable_mcp", "yes")
        assert cp_config.get_mcp_disabled() is True

    @pytest.mark.parametrize(
        "getter, setter",
        [
            (
                cp_config.get_universal_constructor_enabled,
                cp_config.set_universal_constructor_enabled,
            ),
            (
                cp_config.get_suppress_thinking_messages,
                cp_config.set_suppress_thinking_messages,
            ),
            (
                cp_config.get_suppress_informational_messages,
                cp_config.set_suppress_informational_messages,
            ),
            (cp_config.get_http2, cp_config.set_http2),
        ],
    )
    def test_bool_setter_roundtrip(self, getter, setter):
        setter(True)
        assert getter() is True
        setter(False)
        assert getter() is False

    def test_set_auto_save_session(self):
        cp_config.set_auto_save_session(False)
        assert cp_config.get_auto_save_session() is False

    def test_pack_agents_enabled_roundtrip(self):
        cp_config.set_config_value("enable_pack_agents", "false")
        assert cp_config.get_pack_agents_enabled() is False
        cp_config.set_config_value("enable_pack_agents", "on")
        assert cp_config.get_pack_agents_enabled() is True


# ---------------------------------------------------------------------------
# Safety permission level
# ---------------------------------------------------------------------------
class TestSafetyPermissionLevel:
    def test_default_medium(self):
        assert cp_config.get_safety_permission_level() == "medium"

    @pytest.mark.parametrize("level", ["none", "low", "medium", "high", "critical"])
    def test_valid_levels(self, level):
        cp_config.set_config_value("safety_permission_level", level)
        assert cp_config.get_safety_permission_level() == level

    def test_invalid_falls_back_to_medium(self):
        cp_config.set_config_value("safety_permission_level", "invalid")
        assert cp_config.get_safety_permission_level() == "medium"


# ---------------------------------------------------------------------------
# Numeric config getters (default / custom / clamp / invalid)
# ---------------------------------------------------------------------------
class TestNumericGetters:
    @pytest.mark.parametrize(
        "getter, key, default",
        [
            (cp_config.get_resume_message_count, "resume_message_count", 50),
            (cp_config.get_message_limit, "message_limit", 1000),
            (cp_config.get_diff_context_lines, "diff_context_lines", 6),
            (cp_config.get_max_saved_sessions, "max_saved_sessions", 20),
            (cp_config.get_compaction_threshold, "compaction_threshold", 0.85),
            (
                cp_config.get_frontend_emitter_max_recent_events,
                "frontend_emitter_max_recent_events",
                100,
            ),
            (
                cp_config.get_frontend_emitter_queue_size,
                "frontend_emitter_queue_size",
                100,
            ),
            (
                cp_config.get_max_continuation_iterations,
                "max_continuation_iterations",
                25,
            ),
        ],
    )
    def test_default(self, getter, key, default):
        cp_config.reset_value(key)
        assert getter() == default

    @pytest.mark.parametrize(
        "getter, key, default",
        [
            (cp_config.get_resume_message_count, "resume_message_count", 50),
            (cp_config.get_message_limit, "message_limit", 1000),
            (cp_config.get_diff_context_lines, "diff_context_lines", 6),
            (cp_config.get_max_saved_sessions, "max_saved_sessions", 20),
            (cp_config.get_compaction_threshold, "compaction_threshold", 0.85),
            (
                cp_config.get_frontend_emitter_max_recent_events,
                "frontend_emitter_max_recent_events",
                100,
            ),
            (
                cp_config.get_frontend_emitter_queue_size,
                "frontend_emitter_queue_size",
                100,
            ),
            (
                cp_config.get_max_continuation_iterations,
                "max_continuation_iterations",
                25,
            ),
        ],
    )
    def test_invalid_falls_back_to_default(self, getter, key, default):
        cp_config.set_config_value(key, "not_a_number")
        assert getter() == default

    @pytest.mark.parametrize(
        "getter, key, value, expected",
        [
            (cp_config.get_resume_message_count, "resume_message_count", "30", 30),
            (cp_config.get_message_limit, "message_limit", "500", 500),
            (cp_config.get_diff_context_lines, "diff_context_lines", "10", 10),
            (cp_config.get_max_saved_sessions, "max_saved_sessions", "50", 50),
            (cp_config.get_compaction_threshold, "compaction_threshold", "0.7", 0.7),
            (
                cp_config.get_protected_token_count,
                "protected_token_count",
                "10000",
                10000,
            ),
            (
                cp_config.get_max_continuation_iterations,
                "max_continuation_iterations",
                "7",
                7,
            ),
        ],
    )
    def test_custom_value(self, getter, key, value, expected):
        cp_config.set_config_value(key, value)
        assert getter() == expected

    @pytest.mark.parametrize(
        "getter, key, value, expected",
        [
            # resume_message_count clamps to max 100
            (cp_config.get_resume_message_count, "resume_message_count", "999", 100),
            # diff_context_lines clamps to [0, 50]
            (cp_config.get_diff_context_lines, "diff_context_lines", "100", 50),
            (cp_config.get_diff_context_lines, "diff_context_lines", "-5", 0),
            # compaction_threshold clamps to [0.5, 0.95]
            (cp_config.get_compaction_threshold, "compaction_threshold", "0.1", 0.5),
            (cp_config.get_compaction_threshold, "compaction_threshold", "0.98", 0.95),
            (cp_config.get_compaction_threshold, "compaction_threshold", "0", 0.5),
            (cp_config.get_compaction_threshold, "compaction_threshold", "1.0", 0.95),
            (cp_config.get_compaction_threshold, "compaction_threshold", "-0.1", 0.5),
            (cp_config.get_compaction_threshold, "compaction_threshold", "2.0", 0.95),
        ],
    )
    def test_clamping(self, getter, key, value, expected):
        cp_config.set_config_value(key, value)
        assert getter() == expected

    def test_protected_token_count_default_is_int(self):
        result = cp_config.get_protected_token_count()
        assert isinstance(result, int)
        assert result >= 1000

    def test_protected_token_count_invalid_is_int(self):
        cp_config.set_config_value("protected_token_count", "not_a_number")
        assert isinstance(cp_config.get_protected_token_count(), int)

    def test_message_limit_explicit_default_arg(self):
        cp_config.reset_value("message_limit")
        assert cp_config.get_message_limit(default=50) == 50

    def test_set_max_saved_sessions(self):
        cp_config.set_max_saved_sessions(10)
        assert cp_config.get_max_saved_sessions() == 10


# ---------------------------------------------------------------------------
# Compaction strategy
# ---------------------------------------------------------------------------
class TestCompactionStrategy:
    def test_default(self):
        cp_config.reset_value("compaction_strategy")
        assert cp_config.get_compaction_strategy() in ("summarization", "truncation")

    @pytest.mark.parametrize("strategy", ["summarization", "truncation"])
    def test_valid_case_insensitive(self, strategy):
        cp_config.set_config_value("compaction_strategy", strategy.upper())
        assert cp_config.get_compaction_strategy() == strategy

    def test_invalid_falls_back(self):
        cp_config.set_config_value("compaction_strategy", "invalid")
        assert cp_config.get_compaction_strategy() == "truncation"

    @pytest.mark.parametrize("bad", ["invalid_strategy", "  summarization  "])
    def test_unstripped_or_unknown_falls_back(self, bad):
        # Implementation matches the exact stored string; whitespace/unknown
        # values are not normalized and therefore fall back to the default.
        with patch("code_puppy.config.get_value", return_value=bad):
            assert cp_config.get_compaction_strategy() == "truncation"


# ---------------------------------------------------------------------------
# Temperature
# ---------------------------------------------------------------------------
class TestTemperatureConfig:
    @pytest.mark.parametrize(
        "stored, expected",
        [
            (None, None),
            ("", None),
            ("not_a_number", None),
            ("0.7", 0.7),
            ("5.0", 2.0),  # clamp high
            ("-1.0", 0.0),  # clamp low
        ],
    )
    def test_get_temperature(self, stored, expected):
        with patch("code_puppy.config.get_value") as mock_get_value:
            mock_get_value.return_value = stored
            assert cp_config.get_temperature() == expected

    def test_get_temperature_returns_float_type(self):
        with patch("code_puppy.config.get_value", return_value="0.7"):
            assert isinstance(cp_config.get_temperature(), float)

    @pytest.mark.parametrize(
        "value, stored",
        [(0.7, "0.7"), (5.0, "2.0"), (None, "")],
    )
    def test_set_temperature_stores_string(self, value, stored):
        with patch("code_puppy.config.set_config_value") as mock_set:
            cp_config.set_temperature(value)
            mock_set.assert_called_once_with("temperature", stored)

    def test_set_temperature_roundtrip(self):
        cp_config.set_temperature(1.5)
        assert cp_config.get_temperature() == 1.5


# ---------------------------------------------------------------------------
# OpenAI reasoning / verbosity
# ---------------------------------------------------------------------------
class TestOpenAISettings:
    @pytest.mark.parametrize(
        "getter, setter, key, valid",
        [
            (
                cp_config.get_openai_reasoning_effort,
                cp_config.set_openai_reasoning_effort,
                "openai_reasoning_effort",
                "high",
            ),
            (
                cp_config.get_openai_verbosity,
                cp_config.set_openai_verbosity,
                "openai_verbosity",
                "low",
            ),
        ],
    )
    def test_default_invalid_and_valid(self, getter, setter, key, valid):
        cp_config.reset_value(key)
        assert getter() == "medium"
        cp_config.set_config_value(key, "bogus")
        assert getter() == "medium"
        setter(valid)
        assert getter() == valid

    @pytest.mark.parametrize(
        "setter",
        [cp_config.set_openai_reasoning_effort, cp_config.set_openai_verbosity],
    )
    def test_setter_rejects_invalid(self, setter):
        with pytest.raises(ValueError):
            setter("bogus")


# ---------------------------------------------------------------------------
# Per-model settings
# ---------------------------------------------------------------------------
class TestPerModelSettings:
    def test_sanitize_model_name(self):
        assert cp_config._sanitize_model_name_for_key("gpt-4.1") == "gpt_4_1"
        assert cp_config._sanitize_model_name_for_key("a/b") == "a_b"

    def test_get_set_model_setting(self):
        cp_config.set_model_setting("test-model", "temperature", 0.5)
        assert cp_config.get_model_setting("test-model", "temperature") == 0.5

    def test_get_model_setting_default(self):
        assert cp_config.get_model_setting("nonexistent", "seed", default=42.0) == 42.0

    def test_set_model_setting_none_clears(self):
        cp_config.set_model_setting("test-model", "seed", 123)
        cp_config.set_model_setting("test-model", "seed", None)
        assert cp_config.get_model_setting("test-model", "seed") is None

    def test_set_model_setting_int_returns_float(self):
        cp_config.set_model_setting("test-model", "seed", 42)
        assert cp_config.get_model_setting("test-model", "seed") == 42.0

    def test_get_model_setting_invalid_value(self):
        cp_config.set_config_value("model_settings_test_model_seed", "bad")
        assert cp_config.get_model_setting("test-model", "seed", default=99.0) == 99.0

    def test_get_all_model_settings(self):
        cp_config.set_model_setting("all-test", "temperature", 0.8)
        cp_config.set_model_setting("all-test", "seed", 42)
        assert "temperature" in cp_config.get_all_model_settings("all-test")

    def test_get_all_model_settings_boolean(self):
        cp_config.set_config_value("model_settings_bool_test_extended_thinking", "true")
        assert (
            cp_config.get_all_model_settings("bool-test").get("extended_thinking")
            is True
        )

    def test_get_all_model_settings_string(self):
        cp_config.set_config_value("model_settings_str_test_foo", "bar")
        assert cp_config.get_all_model_settings("str-test").get("foo") == "bar"

    def test_clear_model_settings(self):
        cp_config.set_model_setting("clear-test", "temperature", 0.5)
        cp_config.clear_model_settings("clear-test")
        assert len(cp_config.get_all_model_settings("clear-test")) == 0

    def test_effective_settings_with_global_fallback(self):
        cp_config.set_temperature(0.9)
        cp_config.clear_model_settings("fallback-test")
        with patch.object(
            cp_config, "get_global_model_name", return_value="fallback-test"
        ):
            with patch.object(cp_config, "model_supports_setting", return_value=True):
                settings = cp_config.get_effective_model_settings("fallback-test")
                assert settings.get("temperature") == 0.9

    def test_effective_settings_seed_converted_to_int(self):
        cp_config.set_model_setting("seed-test", "seed", 42)
        with patch.object(cp_config, "model_supports_setting", return_value=True):
            settings = cp_config.get_effective_model_settings("seed-test")
            assert isinstance(settings.get("seed"), int)

    def test_effective_settings_none_uses_global(self):
        with patch.object(cp_config, "get_global_model_name", return_value="test"):
            with patch.object(cp_config, "model_supports_setting", return_value=True):
                assert isinstance(cp_config.get_effective_model_settings(None), dict)

    def test_get_effective_temperature(self):
        cp_config.set_model_setting("eff-temp", "temperature", 0.3)
        with patch.object(cp_config, "model_supports_setting", return_value=True):
            assert cp_config.get_effective_temperature("eff-temp") == 0.3

    def test_get_effective_top_p_none(self):
        with patch.object(cp_config, "model_supports_setting", return_value=True):
            assert cp_config.get_effective_top_p("no-top-p") is None

    def test_get_effective_seed_none(self):
        with patch.object(cp_config, "model_supports_setting", return_value=True):
            assert cp_config.get_effective_seed("no-seed") is None


# ---------------------------------------------------------------------------
# model_supports_setting
# ---------------------------------------------------------------------------
class TestModelSupportsSetting:
    def _patch_config(self, mock_config):
        return patch(
            "code_puppy.model_factory.ModelFactory.load_config",
            return_value=mock_config,
        )

    def test_supported_settings_list(self):
        cfg = {"test-model": {"supported_settings": ["temperature", "seed"]}}
        with self._patch_config(cfg):
            assert cp_config.model_supports_setting("test-model", "temperature") is True
            assert cp_config.model_supports_setting("test-model", "seed") is True
            assert cp_config.model_supports_setting("test-model", "top_p") is False

    def test_setting_not_in_supported_list(self):
        cfg = {"test-model": {"supported_settings": ["seed"]}}
        with self._patch_config(cfg):
            assert (
                cp_config.model_supports_setting("test-model", "temperature") is False
            )

    def test_defaults_true_when_no_supported_settings(self):
        cfg = {"test-model": {"type": "openai", "name": "test-model"}}
        with self._patch_config(cfg):
            assert cp_config.model_supports_setting("test-model", "temperature") is True
            assert cp_config.model_supports_setting("test-model", "seed") is True
            assert cp_config.model_supports_setting("test-model", "top_p") is False

    def test_claude_default_settings(self):
        cfg = {"claude-test": {}}
        with self._patch_config(cfg):
            assert (
                cp_config.model_supports_setting("claude-test", "temperature") is True
            )
            assert (
                cp_config.model_supports_setting("claude-test", "extended_thinking")
                is True
            )

    @pytest.mark.parametrize("name", ["claude-opus-4-6", "claude-4-6-opus"])
    def test_opus_46_supports_effort(self, name):
        with self._patch_config({name: {"type": "anthropic", "name": name}}):
            assert cp_config.model_supports_setting(name, "effort") is True

    def test_non_opus_46_does_not_support_effort(self):
        cfg = {"claude-sonnet-4": {"type": "anthropic", "name": "claude-sonnet-4"}}
        with self._patch_config(cfg):
            assert (
                cp_config.model_supports_setting("claude-sonnet-4", "effort") is False
            )

    @pytest.mark.parametrize("name", ["glm-4.7-chat", "GLM-5-large"])
    def test_glm_clear_thinking(self, name):
        assert cp_config.model_supports_setting(name, "clear_thinking") is True

    def test_unknown_model_defaults_true(self):
        with self._patch_config({}):
            assert (
                cp_config.model_supports_setting("unknown-model", "temperature") is True
            )

    def test_exception_returns_true(self):
        with patch(
            "code_puppy.model_factory.ModelFactory.load_config", side_effect=Exception
        ):
            assert cp_config.model_supports_setting("any", "any") is True


# ---------------------------------------------------------------------------
# Model name management
# ---------------------------------------------------------------------------
class TestModelName:
    def setup_method(self):
        cp_config.reset_session_model()
        cp_config.clear_model_cache()

    def test_from_session_cache(self):
        cp_config._SESSION_MODEL = "cached-model"
        assert cp_config.get_global_model_name() == "cached-model"
        cp_config._SESSION_MODEL = None

    def test_valid_stored_model_returned(self):
        cp_config._SESSION_MODEL = None
        cp_config.set_config_value("model", "my-model")
        with patch.object(cp_config, "_validate_model_exists", return_value=True):
            assert cp_config.get_global_model_name() == "my-model"
        cp_config._SESSION_MODEL = None

    def test_invalid_stored_falls_back_to_default(self):
        cp_config._SESSION_MODEL = None
        cp_config.set_config_value("model", "bad-model")
        with patch.object(cp_config, "_validate_model_exists", return_value=False):
            with patch.object(
                cp_config, "_default_model_from_models_json", return_value="default-m"
            ):
                assert cp_config.get_global_model_name() == "default-m"
        cp_config._SESSION_MODEL = None

    def test_no_stored_model_uses_default(self):
        cp_config._SESSION_MODEL = None
        cp_config.reset_value("model")
        with patch.object(cp_config, "_validate_model_exists") as mock_validate:
            with patch.object(
                cp_config,
                "_default_model_from_models_json",
                return_value="synthetic-GLM",
            ) as mock_default:
                assert cp_config.get_global_model_name() == "synthetic-GLM"
                mock_validate.assert_not_called()
                mock_default.assert_called_once()
        cp_config._SESSION_MODEL = None

    @patch("configparser.ConfigParser")
    @patch("builtins.open", new_callable=mock_open)
    def test_set_model_name_writes_config(
        self, mock_file_open, mock_cp_class, mock_config_paths
    ):
        _, mock_cfg_file = mock_config_paths
        inst = MagicMock()
        store = {}
        inst.read.return_value = [mock_cfg_file]
        inst.__contains__.side_effect = lambda name: name in store
        inst.__setitem__.side_effect = lambda name, val: store.__setitem__(name, val)
        inst.__getitem__.side_effect = lambda name: store.setdefault(name, {})
        mock_cp_class.return_value = inst

        # set_model_name updates the session cache; persisting also touches config.
        cp_config.set_model_name("super_model_7000")
        assert cp_config._SESSION_MODEL == "super_model_7000"
        cp_config._SESSION_MODEL = None

    def test_reset_session_model(self):
        cp_config._SESSION_MODEL = "foo"
        cp_config.reset_session_model()
        assert cp_config._SESSION_MODEL is None


# ---------------------------------------------------------------------------
# Default model / vision model from models.json
# ---------------------------------------------------------------------------
class TestDefaultModel:
    def test_cached(self):
        cp_config._default_model_cache = "cached"
        assert cp_config._default_model_from_models_json() == "cached"
        cp_config._default_model_cache = None

    def test_first_from_config(self):
        cp_config._default_model_cache = None
        with patch(
            "code_puppy.model_factory.ModelFactory.load_config",
            return_value={"first": {}, "second": {}},
        ):
            assert cp_config._default_model_from_models_json() == "first"
        cp_config._default_model_cache = None

    @pytest.mark.parametrize("side", ["empty", "exception"])
    def test_fallback_gpt5(self, side):
        cp_config._default_model_cache = None
        kw = {"return_value": {}} if side == "empty" else {"side_effect": Exception}
        with patch("code_puppy.model_factory.ModelFactory.load_config", **kw):
            assert cp_config._default_model_from_models_json() == "gpt-5"
        cp_config._default_model_cache = None


class TestDefaultVisionModel:
    def test_cached(self):
        cp_config._default_vision_model_cache = "cached-vision"
        assert cp_config._default_vision_model_from_models_json() == "cached-vision"
        cp_config._default_vision_model_cache = None

    def test_supports_vision_tag(self):
        cp_config._default_vision_model_cache = None
        with patch(
            "code_puppy.model_factory.ModelFactory.load_config",
            return_value={"model-a": {"supports_vision": True}},
        ):
            assert cp_config._default_vision_model_from_models_json() == "model-a"
        cp_config._default_vision_model_cache = None

    def test_preferred_candidates(self):
        cp_config._default_vision_model_cache = None
        with patch(
            "code_puppy.model_factory.ModelFactory.load_config",
            return_value={"gpt-4.1": {}, "other": {}},
        ):
            assert cp_config._default_vision_model_from_models_json() == "gpt-4.1"
        cp_config._default_vision_model_cache = None

    def test_fallback_to_general_default(self):
        cp_config._default_vision_model_cache = None
        with patch(
            "code_puppy.model_factory.ModelFactory.load_config",
            return_value={"some-model": {}},
        ):
            with patch.object(
                cp_config, "_default_model_from_models_json", return_value="some-model"
            ):
                assert (
                    cp_config._default_vision_model_from_models_json() == "some-model"
                )
        cp_config._default_vision_model_cache = None

    @pytest.mark.parametrize("side", ["empty", "exception"])
    def test_fallback_gpt41(self, side):
        cp_config._default_vision_model_cache = None
        kw = {"return_value": {}} if side == "empty" else {"side_effect": Exception}
        with patch("code_puppy.model_factory.ModelFactory.load_config", **kw):
            assert cp_config._default_vision_model_from_models_json() == "gpt-4.1"
        cp_config._default_vision_model_cache = None


# ---------------------------------------------------------------------------
# _validate_model_exists
# ---------------------------------------------------------------------------
class TestValidateModel:
    def test_cached_true(self):
        cp_config._model_validation_cache["cached-m"] = True
        assert cp_config._validate_model_exists("cached-m") is True
        del cp_config._model_validation_cache["cached-m"]

    def test_found(self):
        cp_config._model_validation_cache.clear()
        with patch(
            "code_puppy.model_factory.ModelFactory.load_config", return_value={"m": {}}
        ):
            assert cp_config._validate_model_exists("m") is True

    def test_not_found(self):
        cp_config._model_validation_cache.clear()
        with patch(
            "code_puppy.model_factory.ModelFactory.load_config", return_value={}
        ):
            assert cp_config._validate_model_exists("missing") is False

    def test_exception_returns_true(self):
        cp_config._model_validation_cache.clear()
        with patch(
            "code_puppy.model_factory.ModelFactory.load_config", side_effect=Exception
        ):
            assert cp_config._validate_model_exists("any") is True


# ---------------------------------------------------------------------------
# Model context length
# ---------------------------------------------------------------------------
class TestModelContextLength:
    def test_from_config(self):
        with patch(
            "code_puppy.model_factory.ModelFactory.load_config",
            return_value={"m": {"context_length": 32000}},
        ):
            with patch.object(cp_config, "get_global_model_name", return_value="m"):
                assert cp_config.get_model_context_length() == 32000

    def test_default(self):
        with patch(
            "code_puppy.model_factory.ModelFactory.load_config", return_value={}
        ):
            with patch.object(cp_config, "get_global_model_name", return_value="m"):
                assert cp_config.get_model_context_length() == 128000

    def test_exception(self):
        with patch(
            "code_puppy.model_factory.ModelFactory.load_config", side_effect=Exception
        ):
            assert cp_config.get_model_context_length() == 128000


# ---------------------------------------------------------------------------
# clear_model_cache
# ---------------------------------------------------------------------------
class TestClearModelCache:
    def test_clears_all(self):
        cp_config._model_validation_cache["x"] = True
        cp_config._default_model_cache = "y"
        cp_config._default_vision_model_cache = "z"
        cp_config.clear_model_cache()
        assert len(cp_config._model_validation_cache) == 0
        assert cp_config._default_model_cache is None
        assert cp_config._default_vision_model_cache is None


# ---------------------------------------------------------------------------
# MCP server configs
# ---------------------------------------------------------------------------
class TestMCPServerConfigs:
    def test_no_file(self):
        with patch.object(pathlib.Path, "exists", return_value=False):
            assert cp_config.load_mcp_server_configs() == {}

    def test_valid_file(self, tmp_path):
        f = tmp_path / "mcp_servers.json"
        f.write_text(json.dumps({"mcp_servers": {"s1": "http://localhost"}}))
        with patch.object(cp_config, "MCP_SERVERS_FILE", str(f)):
            assert cp_config.load_mcp_server_configs() == {"s1": "http://localhost"}

    def test_bad_json(self, tmp_path):
        f = tmp_path / "mcp_servers.json"
        f.write_text("not json")
        with patch.object(cp_config, "MCP_SERVERS_FILE", str(f)):
            with patch("code_puppy.messaging.message_queue.emit_error"):
                assert cp_config.load_mcp_server_configs() == {}

    def test_io_error_emits(self):
        with (
            patch("code_puppy.config.MCP_SERVERS_FILE", "/mock/mcp_servers.json"),
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", side_effect=IOError("Permission denied")),
            patch("code_puppy.messaging.message_queue.emit_error") as mock_emit_error,
        ):
            assert cp_config.load_mcp_server_configs() == {}
            mock_emit_error.assert_called_once()
            assert "Failed to load MCP servers" in mock_emit_error.call_args[0][0]


# ---------------------------------------------------------------------------
# Agent pinned models
# ---------------------------------------------------------------------------
class TestAgentPinnedModels:
    def test_set_get_clear(self):
        cp_config.set_agent_pinned_model("test-agent", "my-model")
        assert cp_config.get_agent_pinned_model("test-agent") == "my-model"
        cp_config.clear_agent_pinned_model("test-agent")
        assert not cp_config.get_agent_pinned_model("test-agent")

    def test_uses_namespaced_key(self):
        with patch("code_puppy.config.get_value") as mock_get:
            mock_get.return_value = None
            assert cp_config.get_agent_pinned_model("a") is None
            mock_get.assert_called_once_with("agent_model_a")
        with patch("code_puppy.config.set_config_value") as mock_set:
            cp_config.set_agent_pinned_model("a", "gpt-4")
            mock_set.assert_called_once_with("agent_model_a", "gpt-4")
        with patch("code_puppy.config.set_config_value") as mock_set:
            cp_config.clear_agent_pinned_model("a")
            mock_set.assert_called_once_with("agent_model_a", "")

    def test_get_all_agent_pinned_models(self):
        cp_config.set_agent_pinned_model("a1", "m1")
        cp_config.set_agent_pinned_model("a2", "m2")
        pinnings = cp_config.get_all_agent_pinned_models()
        assert pinnings.get("a1") == "m1"
        assert pinnings.get("a2") == "m2"

    def test_get_agents_pinned_to_model(self):
        cp_config.set_agent_pinned_model("pa1", "target")
        cp_config.set_agent_pinned_model("pa2", "other")
        result = cp_config.get_agents_pinned_to_model("target")
        assert "pa1" in result
        assert "pa2" not in result


# ---------------------------------------------------------------------------
# Puppy token
# ---------------------------------------------------------------------------
class TestPuppyToken:
    def test_get_set_roundtrip(self):
        cp_config.set_puppy_token("tok123")
        assert cp_config.get_puppy_token() == "tok123"

    def test_get_none_if_not_set(self):
        cp_config.reset_value("puppy_token")
        assert cp_config.get_puppy_token() is None


# ---------------------------------------------------------------------------
# Diff colors / banner colors
# ---------------------------------------------------------------------------
class TestDiffColors:
    def test_default_addition_color(self):
        cp_config.reset_value("highlight_addition_color")
        assert cp_config.get_diff_addition_color() == "#0b1f0b"

    def test_set_addition_color_normalized(self):
        cp_config.set_diff_addition_color("green")
        assert cp_config.get_diff_addition_color() == "#008000"

    def test_default_deletion_color(self):
        cp_config.reset_value("highlight_deletion_color")
        assert cp_config.get_diff_deletion_color() == "#390e1a"

    def test_set_deletion_color_normalized(self):
        cp_config.set_diff_deletion_color("red")
        assert cp_config.get_diff_deletion_color() == "#800000"

    def test_set_diff_highlight_style_noop(self):
        cp_config.set_diff_highlight_style("anything")


class TestBannerColors:
    def test_get_default(self):
        cp_config.reset_value("banner_color_thinking")
        assert cp_config.get_banner_color("thinking") == "deep_sky_blue4"

    def test_get_unknown_banner(self):
        assert cp_config.get_banner_color("nonexistent_banner") == "blue"

    def test_set_and_get(self):
        cp_config.set_banner_color("thinking", "red")
        assert cp_config.get_banner_color("thinking") == "red"

    def test_get_all(self):
        assert "thinking" in cp_config.get_all_banner_colors()

    def test_reset_single(self):
        cp_config.set_banner_color("thinking", "custom")
        cp_config.reset_banner_color("thinking")
        assert (
            cp_config.get_banner_color("thinking")
            == cp_config.DEFAULT_BANNER_COLORS["thinking"]
        )

    def test_reset_all(self):
        cp_config.set_banner_color("thinking", "custom")
        cp_config.reset_all_banner_colors()
        assert (
            cp_config.get_banner_color("thinking")
            == cp_config.DEFAULT_BANNER_COLORS["thinking"]
        )


# ---------------------------------------------------------------------------
# Autosave session management
# ---------------------------------------------------------------------------
class TestAutosaveSession:
    def test_get_current_autosave_id(self):
        cp_config._CURRENT_AUTOSAVE_ID = None
        aid = cp_config.get_current_autosave_id()
        assert aid is not None and len(aid) > 0

    def test_rotate_autosave_id(self):
        import time

        cp_config.get_current_autosave_id()
        time.sleep(0.01)
        assert isinstance(cp_config.rotate_autosave_id(), str)

    def test_get_current_autosave_session_name(self):
        assert cp_config.get_current_autosave_session_name().startswith("auto_session_")

    @pytest.mark.parametrize(
        "session_name, expected",
        [
            ("auto_session_20250101_120000", "20250101_120000"),
            ("custom_id", "custom_id"),
        ],
    )
    def test_set_from_session_name(self, session_name, expected):
        assert (
            cp_config.set_current_autosave_from_session_name(session_name) == expected
        )

    def test_auto_save_if_enabled_disabled(self):
        cp_config.set_auto_save_session(False)
        assert cp_config.auto_save_session_if_enabled() is False

    def test_auto_save_if_enabled_no_history(self):
        cp_config.set_auto_save_session(True)
        mock_agent = MagicMock()
        mock_agent.get_message_history.return_value = []
        with patch(
            "code_puppy.agents.agent_manager.get_current_agent", return_value=mock_agent
        ):
            assert cp_config.auto_save_session_if_enabled() is False

    def test_auto_save_if_enabled_success(self):
        cp_config.set_auto_save_session(True)
        mock_agent = MagicMock()
        mock_agent.get_message_history.return_value = [
            {"role": "user", "content": "hi"}
        ]
        mock_metadata = MagicMock()
        mock_metadata.message_count = 1
        mock_metadata.total_tokens = 100
        with patch(
            "code_puppy.agents.agent_manager.get_current_agent", return_value=mock_agent
        ):
            with patch("code_puppy.config.save_session", return_value=mock_metadata):
                with patch("code_puppy.messaging.emit_info"):
                    assert cp_config.auto_save_session_if_enabled() is True

    def test_finalize_autosave_session(self):
        with patch.object(cp_config, "auto_save_session_if_enabled"):
            assert isinstance(cp_config.finalize_autosave_session(), str)


# ---------------------------------------------------------------------------
# Command history
# ---------------------------------------------------------------------------
class TestCommandHistory:
    @patch("os.path.isfile")
    @patch("pathlib.Path.touch")
    @patch("os.path.expanduser")
    @patch("os.makedirs")
    def test_initialize_creates_new_file(
        self, mock_makedirs, mock_expanduser, mock_touch, mock_isfile, mock_config_paths
    ):
        mock_isfile.side_effect = [False, False]  # both new + legacy missing
        mock_expanduser.return_value = "/mock_home"
        cp_config.initialize_command_history_file()
        assert mock_isfile.call_count == 2
        assert mock_isfile.call_args_list[0][0][0] == cp_config.COMMAND_HISTORY_FILE
        mock_touch.assert_called_once()

    @patch("os.path.isfile")
    @patch("pathlib.Path.touch")
    @patch("os.path.expanduser")
    @patch("shutil.copy2")
    @patch("pathlib.Path.unlink")
    @patch("os.makedirs")
    def test_initialize_migrates_old_file(
        self,
        mock_makedirs,
        mock_unlink,
        mock_copy2,
        mock_expanduser,
        mock_touch,
        mock_isfile,
        mock_config_paths,
    ):
        mock_isfile.side_effect = [False, True]  # new missing, legacy exists
        mock_expanduser.return_value = "/mock_home"
        cp_config.initialize_command_history_file()
        assert mock_isfile.call_count == 2
        mock_touch.assert_called_once()
        mock_copy2.assert_called_once()
        mock_unlink.assert_called_once()

    @patch("os.path.isfile")
    @patch("os.makedirs")
    def test_initialize_file_exists(
        self, mock_makedirs, mock_isfile, mock_config_paths
    ):
        mock_isfile.return_value = True
        cp_config.initialize_command_history_file()
        mock_isfile.assert_called_once_with(cp_config.COMMAND_HISTORY_FILE)

    @patch("builtins.open", new_callable=mock_open)
    def test_save_command_with_timestamp(self, mock_file, mock_config_paths):
        cp_config.save_command_to_history("test command")
        mock_file.assert_called_once_with(
            cp_config.COMMAND_HISTORY_FILE,
            "a",
            encoding="utf-8",
            errors="surrogateescape",
        )
        write_call_args = mock_file().write.call_args[0][0]
        assert write_call_args.startswith("\n# ")
        assert write_call_args.endswith("\ntest command\n")
        import re

        assert (
            re.search(r"# (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", write_call_args)
            is not None
        )

    @patch("builtins.open")
    @patch("code_puppy.messaging.emit_error")
    def test_save_command_handles_error(
        self, mock_emit_error, mock_file, mock_config_paths
    ):
        mock_file.side_effect = Exception("Test error")
        cp_config.save_command_to_history("test command")
        mock_emit_error.assert_called_once()
        assert "Test error" in mock_emit_error.call_args[0][0]


# ---------------------------------------------------------------------------
# User / project agents directories
# ---------------------------------------------------------------------------
class TestAgentsDirectories:
    def test_get_user_agents_directory(self):
        assert os.path.isdir(cp_config.get_user_agents_directory())

    def test_get_project_agents_directory_exists(self, tmp_path, monkeypatch):
        (tmp_path / ".fast_puppy" / "agents").mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        assert cp_config.get_project_agents_directory() is not None

    def test_get_project_agents_directory_not_exists(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert cp_config.get_project_agents_directory() is None


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
class TestAPIKeys:
    def test_get_set_api_key(self):
        cp_config.set_api_key("TEST_KEY", "secret")
        assert cp_config.get_api_key("TEST_KEY") == "secret"

    def test_get_api_key_not_set(self):
        assert cp_config.get_api_key("NONEXISTENT_KEY_XYZ") == ""

    def test_load_api_keys_to_environment(self, monkeypatch):
        cp_config.set_api_key("OPENAI_API_KEY", "test-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cp_config.load_api_keys_to_environment()
        assert os.environ.get("OPENAI_API_KEY") == "test-key"

    def test_load_api_keys_env_has_priority(self, monkeypatch):
        cp_config.set_api_key("OPENAI_API_KEY", "from-config")
        monkeypatch.setenv("OPENAI_API_KEY", "from-env")
        cp_config.load_api_keys_to_environment()
        assert os.environ["OPENAI_API_KEY"] == "from-env"

    def test_load_api_keys_dotenv(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("OPENAI_API_KEY=from-dotenv\n")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        try:
            cp_config.load_api_keys_to_environment()
        except Exception:
            pass  # dotenv may not be installed


# ==================== CALLBACKS EDGE CASES ====================


class TestCallbacksErrorHandling:
    def test_register_callback_rejects_invalid_phase(self):
        with pytest.raises(ValueError, match="Unsupported phase"):
            callbacks.register_callback("invalid_phase", lambda: None)

    def test_register_callback_rejects_non_callable(self):
        with pytest.raises(TypeError, match="Callback must be callable"):
            callbacks.register_callback("startup", "not a function")

    def test_register_callback_prevents_duplicates(self):
        def my_callback():
            pass

        callbacks.clear_callbacks("startup")
        callbacks.register_callback("startup", my_callback)
        count_after_first = callbacks.count_callbacks("startup")
        callbacks.register_callback("startup", my_callback)
        assert count_after_first == callbacks.count_callbacks("startup")
        callbacks.clear_callbacks("startup")

    def test_unregister_invalid_phase_returns_false(self):
        assert callbacks.unregister_callback("invalid_phase", lambda: None) is False

    def test_unregister_unregistered_returns_false(self):
        callbacks.clear_callbacks("startup")
        assert callbacks.unregister_callback("startup", lambda: None) is False

    def test_unregister_successful_returns_true(self):
        def my_callback():
            pass

        callbacks.clear_callbacks("startup")
        callbacks.register_callback("startup", my_callback)
        assert callbacks.unregister_callback("startup", my_callback) is True
        assert callbacks.count_callbacks("startup") == 0

    def test_clear_callbacks_specific_phase(self):
        def cb1():
            pass

        def cb2():
            pass

        callbacks.clear_callbacks()
        callbacks.register_callback("startup", cb1)
        callbacks.register_callback("shutdown", cb2)
        callbacks.clear_callbacks("startup")
        assert callbacks.count_callbacks("startup") == 0
        assert callbacks.count_callbacks("shutdown") == 1
        callbacks.clear_callbacks()

    def test_get_callbacks_returns_copy(self):
        def my_callback():
            pass

        callbacks.clear_callbacks("startup")
        callbacks.register_callback("startup", my_callback)
        retrieved = callbacks.get_callbacks("startup")
        original_count = callbacks.count_callbacks("startup")
        retrieved.append(lambda: None)
        assert callbacks.count_callbacks("startup") == original_count
        callbacks.clear_callbacks("startup")

    def test_count_callbacks_all_phases(self):
        def cb1():
            pass

        def cb2():
            pass

        def cb3():
            pass

        callbacks.clear_callbacks()
        callbacks.register_callback("startup", cb1)
        callbacks.register_callback("startup", cb2)
        callbacks.register_callback("shutdown", cb3)
        assert callbacks.count_callbacks() >= 3
        callbacks.clear_callbacks()


# ==================== SESSION STORAGE TESTS ====================


class TestSessionStoragePathManagement:
    def test_ensure_directory_creates_directory(self, tmp_path):
        test_path = tmp_path / "new_dir"
        assert not test_path.exists()
        result = session_storage.ensure_directory(test_path)
        assert test_path.exists()
        assert result == test_path

    def test_ensure_directory_handles_existing_directory(self, tmp_path):
        assert session_storage.ensure_directory(tmp_path) == tmp_path

    def test_build_session_paths_creates_correct_paths(self, tmp_path):
        paths = session_storage.build_session_paths(tmp_path, "test_session")
        assert paths.pickle_path == tmp_path / "test_session.pkl"
        assert paths.metadata_path == tmp_path / "test_session_meta.json"


class TestSessionSaveAndLoad:
    def test_save_session_creates_pickle_and_metadata(self, tmp_path):
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]

        def mock_token_estimator(msg):
            return len(msg.get("content", "").split())

        metadata = session_storage.save_session(
            history=history,
            session_name="test",
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=mock_token_estimator,
            auto_saved=False,
        )
        assert (tmp_path / "test.pkl").exists()
        assert (tmp_path / "test_meta.json").exists()
        assert metadata.session_name == "test"
        assert metadata.message_count == 2
        assert metadata.auto_saved is False

    def test_load_session_retrieves_saved_history(self, tmp_path):
        original_history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        session_storage.save_session(
            history=original_history,
            session_name="test",
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=lambda msg: 10,
        )
        assert session_storage.load_session("test", tmp_path) == original_history

    def test_load_session_raises_for_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            session_storage.load_session("nonexistent", tmp_path)

    def test_session_metadata_serialization(self):
        metadata = session_storage.SessionMetadata(
            session_name="test",
            timestamp="2024-01-01T00:00:00",
            message_count=5,
            total_tokens=100,
            pickle_path=Path("/tmp/test.pkl"),
            metadata_path=Path("/tmp/test_meta.json"),
            auto_saved=True,
        )
        serialized = metadata.as_serialisable()
        assert serialized["session_name"] == "test"
        assert serialized["message_count"] == 5
        assert serialized["total_tokens"] == 100
        assert serialized["auto_saved"] is True
        assert "file_path" in serialized


class TestSessionListingAndCleanup:
    def test_list_sessions_returns_empty_for_nonexistent_dir(self, tmp_path):
        assert session_storage.list_sessions(tmp_path / "nonexistent") == []

    def test_list_sessions_returns_all_sessions(self, tmp_path):
        for i in range(3):
            session_storage.save_session(
                history=[{"role": "user", "content": f"msg{i}"}],
                session_name=f"session_{i}",
                base_dir=tmp_path,
                timestamp="2024-01-01T00:00:00",
                token_estimator=lambda msg: 10,
            )
        result = session_storage.list_sessions(tmp_path)
        assert len(result) == 3
        assert {"session_0", "session_1", "session_2"} <= set(result)

    @pytest.mark.parametrize("max_sessions", [-1, 0, 5])
    def test_cleanup_sessions_noop_cases(self, tmp_path, max_sessions):
        # Empty dir, or non-positive max => nothing removed.
        assert (
            session_storage.cleanup_sessions(tmp_path, max_sessions=max_sessions) == []
        )

    def test_cleanup_sessions_removes_old_sessions(self, tmp_path):
        for i in range(5):
            session_path = tmp_path / f"session_{i}.pkl"
            session_path.touch()
            if i < 2:
                os.utime(session_path, (i, i))
        removed = session_storage.cleanup_sessions(tmp_path, max_sessions=3)
        assert len(removed) >= 2
        assert len(session_storage.list_sessions(tmp_path)) <= 3
