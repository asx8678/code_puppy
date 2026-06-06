"""Tests for agent tools functionality (consolidated)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart

from code_puppy.tools.agent_tools import (
    AgentInfo,
    AgentInvokeOutput,
    ListAgentsOutput,
    _generate_session_hash_suffix,
    _get_subagent_sessions_dir,
    _load_session_history,
    _sanitize_for_session_id,
    _save_session_history,
    _validate_session_id,
    register_invoke_agent,
    register_list_agents,
)


# --------------------------------------------------------------------------- #
# Tool registration / prompt wiring
# --------------------------------------------------------------------------- #
class TestRegistration:
    @pytest.mark.parametrize("register", [register_list_agents, register_invoke_agent])
    def test_register_does_not_raise(self, register):
        register(MagicMock())

    def test_invoke_agent_includes_prompt_additions(self):
        """invoke_agent path relies on file-permission prompt additions existing."""
        from code_puppy import callbacks
        from code_puppy.plugins.file_permission_handler.register_callbacks import (
            get_file_permission_prompt_additions,
        )

        with patch(
            "code_puppy.plugins.file_permission_handler.register_callbacks.get_yolo_mode",
            return_value=False,
        ):
            callbacks.register_callback(
                "load_prompt", get_file_permission_prompt_additions
            )
            prompt_additions = callbacks.on_load_prompt()
            assert len(prompt_additions) > 0
            file_permission_text = "".join(prompt_additions)
            assert "User Approval System" in file_permission_text
            assert "user_feedback" in file_permission_text

    def test_invoke_agent_imports_load_puppy_rules_from_builder(self):
        """Regression: ``load_puppy_rules`` is a free function in ``_builder``,
        not a method on the agent config. Pin the actual contract."""
        from code_puppy.agents import _builder
        from code_puppy.agents.base_agent import BaseAgent

        assert not hasattr(BaseAgent, "load_puppy_rules")
        assert callable(_builder.load_puppy_rules)


# --------------------------------------------------------------------------- #
# _generate_session_hash_suffix
# --------------------------------------------------------------------------- #
class TestGenerateSessionHashSuffix:
    def test_hash_format(self):
        suffix = _generate_session_hash_suffix()
        assert len(suffix) == 6
        assert all(c in "0123456789abcdef" for c in suffix)

    def test_different_calls_different_hashes(self):
        # uuid4-based, so successive calls differ without needing a delay.
        suffixes = {_generate_session_hash_suffix() for _ in range(10)}
        assert len(suffixes) == 10

    def test_result_is_valid_for_kebab_case(self):
        _validate_session_id(f"test-session-{_generate_session_hash_suffix()}")


# --------------------------------------------------------------------------- #
# _sanitize_for_session_id
# --------------------------------------------------------------------------- #
class TestSanitizeForSessionId:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("LPZ-Main-Coder", "lpz-main-coder"),  # capitalised (reported bug)
            ("qa-expert", "qa-expert"),  # already kebab-case
            ("my_agent_name", "my-agent-name"),  # underscores
            ("My Agent Name", "my-agent-name"),  # spaces
            ("foo!!@@bar", "foo-bar"),  # special chars collapsed
            ("--foo--", "foo"),  # leading/trailing hyphens
            ("__foo__", "foo"),
            ("!!!", ""),  # all invalid
            ("", ""),  # empty
        ],
    )
    def test_sanitize(self, raw, expected):
        assert _sanitize_for_session_id(raw) == expected

    def test_result_passes_session_id_validation(self):
        sanitized = _sanitize_for_session_id("LPZ-Main-Coder")
        suffix = _generate_session_hash_suffix()
        _validate_session_id(f"{sanitized}-session-{suffix}")  # should not raise


# --------------------------------------------------------------------------- #
# _validate_session_id
# --------------------------------------------------------------------------- #
class TestSessionIdValidation:
    @pytest.mark.parametrize(
        "session_id",
        [
            # single words
            "session",
            "test",
            "a",
            "1",
            # multi-word kebab-case
            "my-session",
            "agent-session-1",
            "discussion-about-code",
            "very-long-session-name-with-many-words",
            # numbers
            "session1",
            "session-123",
            "test-2024-01-01",
            "123-session",
            "123456789",
            # boundary
            "a" * 128,
        ],
    )
    def test_valid(self, session_id):
        _validate_session_id(session_id)  # should not raise

    @pytest.mark.parametrize(
        "session_id",
        [
            # uppercase
            "MySession",
            "my-Session",
            "MY-SESSION",
            # underscores
            "my_session",
            "my-session_name",
            # spaces
            "my session",
            "session name",
            # special characters
            "my@session",
            "session!",
            "session.name",
            "session#1",
            # double hyphens
            "my--session",
            "session--name",
            # leading/trailing hyphens
            "-session",
            "-my-session",
            "session-",
            "my-session-",
        ],
    )
    def test_invalid_kebab_case(self, session_id):
        with pytest.raises(ValueError, match="must be kebab-case"):
            _validate_session_id(session_id)

    def test_invalid_empty_string(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            _validate_session_id("")

    def test_invalid_too_long(self):
        with pytest.raises(ValueError, match="must be 128 characters or less"):
            _validate_session_id("a" * 129)


# --------------------------------------------------------------------------- #
# _get_subagent_sessions_dir
# --------------------------------------------------------------------------- #
class TestGetSubagentSessionsDir:
    def test_creates_dir_with_correct_name_and_perms(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("code_puppy.tools.agent_tools.DATA_DIR", tmpdir):
                result = _get_subagent_sessions_dir()
                assert isinstance(result, Path)
                assert result.name == "subagent_sessions"
                assert result.exists() and result.is_dir()
                assert (result.stat().st_mode & 0o777) == 0o700

    def test_returns_same_path_on_multiple_calls(self):
        with patch("code_puppy.tools.agent_tools.DATA_DIR", tempfile.gettempdir()):
            assert _get_subagent_sessions_dir() == _get_subagent_sessions_dir()


# --------------------------------------------------------------------------- #
# session save/load
# --------------------------------------------------------------------------- #
class TestSessionSaveLoad:
    @pytest.fixture
    def temp_session_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def mock_messages(self):
        return [
            ModelRequest(parts=[TextPart(content="Hello, can you help?")]),
            ModelResponse(parts=[TextPart(content="Sure, I can help!")]),
            ModelRequest(parts=[TextPart(content="What is 2+2?")]),
            ModelResponse(parts=[TextPart(content="2+2 equals 4.")]),
        ]

    @pytest.fixture(autouse=True)
    def _patch_dir(self, temp_session_dir):
        with patch(
            "code_puppy.tools.agent_tools._get_subagent_sessions_dir",
            return_value=temp_session_dir,
        ):
            yield

    def test_save_and_load_roundtrip(self, temp_session_dir, mock_messages):
        _save_session_history(
            session_id="test-session",
            message_history=mock_messages,
            agent_name="test-agent",
            initial_prompt="Hello, can you help?",
        )
        loaded_messages = _load_session_history("test-session")
        assert len(loaded_messages) == len(mock_messages)
        for loaded, original in zip(loaded_messages, mock_messages):
            assert type(loaded) is type(original)
            assert loaded.parts == original.parts

    def test_load_nonexistent_session_returns_empty_list(self):
        assert _load_session_history("nonexistent-session") == []

    def test_load_handles_corrupted_pickle(self, temp_session_dir):
        pkl_file = temp_session_dir / "corrupted-session.pkl"
        pkl_file.write_bytes(b"This is not a valid pickle file!")
        assert _load_session_history("corrupted-session") == []

    @pytest.mark.parametrize("op", ["save", "load"])
    def test_invalid_session_id_raises(self, op, mock_messages):
        with pytest.raises(ValueError, match="must be kebab-case"):
            if op == "save":
                _save_session_history(
                    session_id="Invalid_Session",
                    message_history=mock_messages,
                    agent_name="test-agent",
                )
            else:
                _load_session_history("Invalid_Session")

    def test_save_creates_pkl_and_txt_with_metadata(
        self, temp_session_dir, mock_messages
    ):
        _save_session_history(
            session_id="test-session",
            message_history=mock_messages,
            agent_name="test-agent",
            initial_prompt="Test prompt",
        )
        pkl_file = temp_session_dir / "test-session.pkl"
        txt_file = temp_session_dir / "test-session.txt"
        assert pkl_file.exists()
        assert txt_file.exists()

        metadata = json.loads(txt_file.read_text())
        assert metadata["session_id"] == "test-session"
        assert metadata["agent_name"] == "test-agent"
        assert metadata["initial_prompt"] == "Test prompt"
        assert metadata["message_count"] == len(mock_messages)
        assert "created_at" in metadata

    def test_txt_file_updates_on_subsequent_saves(
        self, temp_session_dir, mock_messages
    ):
        _save_session_history(
            session_id="test-session",
            message_history=mock_messages[:2],
            agent_name="test-agent",
            initial_prompt="Test prompt",
        )
        # Second save without initial_prompt must not overwrite it.
        _save_session_history(
            session_id="test-session",
            message_history=mock_messages,
            agent_name="test-agent",
            initial_prompt=None,
        )
        metadata = json.loads((temp_session_dir / "test-session.txt").read_text())
        assert metadata["initial_prompt"] == "Test prompt"
        assert metadata["message_count"] == len(mock_messages)
        assert "last_updated" in metadata

    def test_save_metadata_update_error_is_swallowed(self, temp_session_dir):
        """Corrupt metadata txt on subsequent save must not raise."""
        _save_session_history("test-session", ["msg1"], "agent1", "initial")
        (temp_session_dir / "test-session.txt").write_text("not json")
        _save_session_history("test-session", ["msg1", "msg2"], "agent1")  # no raise

    def test_save_without_initial_prompt_then_load(self, mock_messages):
        _save_session_history(
            session_id="test-session",
            message_history=mock_messages[:2],
            agent_name="test-agent",
            initial_prompt="First prompt",
        )
        _save_session_history(
            session_id="test-session",
            message_history=mock_messages,
            agent_name="test-agent",
            initial_prompt=None,
        )
        assert len(_load_session_history("test-session")) == len(mock_messages)

    def test_multiple_sessions_dont_interfere(self, mock_messages):
        _save_session_history(
            session_id="session-one",
            message_history=mock_messages[:1],
            agent_name="test-agent",
            initial_prompt="First",
        )
        _save_session_history(
            session_id="session-two",
            message_history=mock_messages[:2],
            agent_name="test-agent",
            initial_prompt="Second",
        )
        loaded1 = _load_session_history("session-one")
        loaded2 = _load_session_history("session-two")
        assert len(loaded1) == 1
        assert len(loaded2) == 2
        assert loaded1 != loaded2

    def test_empty_session_history_save_and_load(self, temp_session_dir):
        _save_session_history(
            session_id="empty-session",
            message_history=[],
            agent_name="test-agent",
            initial_prompt="Test",
        )
        assert _load_session_history("empty-session") == []
        metadata = json.loads((temp_session_dir / "empty-session.txt").read_text())
        assert metadata["message_count"] == 0


# --------------------------------------------------------------------------- #
# Auto-generated session ID format
# --------------------------------------------------------------------------- #
class TestAutoGeneratedSessionIds:
    @pytest.mark.parametrize(
        "agent_name",
        [
            "qa-expert",
            "code-reviewer",
            "test-agent",
            "agent123",
            "my-custom-agent",
            "simple-agent",
        ],
    )
    def test_session_id_format_is_valid_kebab(self, agent_name):
        hash_suffix = _generate_session_hash_suffix()
        session_id = f"{agent_name}-session-{hash_suffix}"
        _validate_session_id(session_id)  # should not raise
        assert session_id.startswith(f"{agent_name}-session-")
        assert len(hash_suffix) == 6
        assert all(c in "0123456789abcdef" for c in hash_suffix)

    def test_session_id_uniqueness(self):
        session_ids = {
            f"test-agent-session-{_generate_session_hash_suffix()}" for _ in range(10)
        }
        assert len(session_ids) == 10


# --------------------------------------------------------------------------- #
# Pydantic models
# --------------------------------------------------------------------------- #
class TestModels:
    def test_agent_info_create_and_serialize(self):
        info = AgentInfo(
            name="code-reviewer",
            display_name="Code Reviewer",
            description="Reviews code for quality",
        )
        assert info.name == "code-reviewer"
        assert info.display_name == "Code Reviewer"
        assert info.description == "Reviews code for quality"
        data = info.model_dump()
        assert data["name"] == "code-reviewer"
        json_str = info.model_dump_json()
        assert "code-reviewer" in json_str
        assert "Code Reviewer" in json_str

    def test_list_agents_output(self):
        agents = [
            AgentInfo(name="agent1", display_name="Agent One", description="First"),
            AgentInfo(name="agent2", display_name="Agent Two", description="Second"),
        ]
        output = ListAgentsOutput(agents=agents)
        assert len(output.agents) == 2
        assert output.error is None
        # error and empty defaults
        err = ListAgentsOutput(agents=[], error="Something went wrong")
        assert err.agents == []
        assert err.error == "Something went wrong"
        assert ListAgentsOutput(agents=[]).error is None

    def test_agent_invoke_output(self):
        ok = AgentInvokeOutput(
            response="Hello!", agent_name="greeter", session_id="session-123"
        )
        assert ok.response == "Hello!"
        assert ok.agent_name == "greeter"
        assert ok.session_id == "session-123"
        assert ok.error is None
        assert ok.model_dump()["session_id"] == "session-123"
        # error response
        err = AgentInvokeOutput(
            response=None, agent_name="failing-agent", error="Agent crashed"
        )
        assert err.response is None
        assert err.error == "Agent crashed"
        # defaults
        default = AgentInvokeOutput(response="response", agent_name="agent")
        assert default.session_id is None
        assert default.error is None


# --------------------------------------------------------------------------- #
# register_list_agents execution
# --------------------------------------------------------------------------- #
def _capture_registered(register):
    """Register a tool against a mock agent and return the captured function."""
    mock_agent = MagicMock()
    captured = {}

    def capture_tool(func):
        captured["func"] = func
        return func

    mock_agent.tool = capture_tool
    register(mock_agent)
    return captured["func"]


class TestRegisterListAgentsExecution:
    def test_returns_available_agents(self):
        registered_func = _capture_registered(register_list_agents)
        with (
            patch("code_puppy.config.get_banner_color", return_value="blue"),
            patch("code_puppy.tools.agent_tools.emit_info"),
            patch(
                "code_puppy.tools.agent_tools.generate_group_id",
                return_value="test-group",
            ),
            patch("code_puppy.agents.get_available_agents") as mock_available,
            patch("code_puppy.agents.get_agent_descriptions") as mock_descriptions,
        ):
            mock_available.return_value = {
                "code-reviewer": "Code Reviewer",
                "qa-expert": "QA Expert",
            }
            mock_descriptions.return_value = {
                "code-reviewer": "Reviews code quality",
                "qa-expert": "QA testing expert",
            }
            result = registered_func(MagicMock())
            assert isinstance(result, ListAgentsOutput)
            assert len(result.agents) == 2
            assert result.error is None
            agent_names = [a.name for a in result.agents]
            assert "code-reviewer" in agent_names
            assert "qa-expert" in agent_names

    def test_handles_exception(self):
        registered_func = _capture_registered(register_list_agents)
        with (
            patch("code_puppy.config.get_banner_color", return_value="blue"),
            patch("code_puppy.tools.agent_tools.emit_info"),
            patch("code_puppy.tools.agent_tools.emit_error") as mock_emit_error,
            patch(
                "code_puppy.tools.agent_tools.generate_group_id",
                return_value="test-group",
            ),
            patch(
                "code_puppy.agents.get_available_agents",
                side_effect=RuntimeError("Database connection failed"),
            ),
        ):
            result = registered_func(MagicMock())
            assert isinstance(result, ListAgentsOutput)
            assert len(result.agents) == 0
            assert "Database connection failed" in result.error
            assert mock_emit_error.called

    def test_missing_description_uses_default(self):
        registered_func = _capture_registered(register_list_agents)
        with (
            patch("code_puppy.config.get_banner_color", return_value="blue"),
            patch("code_puppy.tools.agent_tools.emit_info"),
            patch(
                "code_puppy.tools.agent_tools.generate_group_id",
                return_value="test-group",
            ),
            patch("code_puppy.agents.get_available_agents") as mock_available,
            patch("code_puppy.agents.get_agent_descriptions") as mock_descriptions,
        ):
            mock_available.return_value = {"new-agent": "New Agent"}
            mock_descriptions.return_value = {}
            result = registered_func(MagicMock())
            assert len(result.agents) == 1
            assert result.agents[0].description == "No description available"

    def test_emits_banner_and_info(self):
        registered_func = _capture_registered(register_list_agents)
        with (
            patch(
                "code_puppy.config.get_banner_color", return_value="green"
            ) as mock_banner_color,
            patch("code_puppy.tools.agent_tools.emit_info") as mock_emit_info,
            patch(
                "code_puppy.tools.agent_tools.generate_group_id",
                return_value="banner-group",
            ),
            patch("code_puppy.agents.get_available_agents", return_value={}),
            patch("code_puppy.agents.get_agent_descriptions", return_value={}),
        ):
            registered_func(MagicMock())
            mock_banner_color.assert_called_once_with("list_agents")
            assert mock_emit_info.called


# --------------------------------------------------------------------------- #
# register_invoke_agent execution
# --------------------------------------------------------------------------- #
class TestRegisterInvokeAgentExecution:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "session_id,match",
        [
            ("Invalid_Session", "must be kebab-case"),
            ("my session", "must be kebab-case"),
            ("session@123", "must be kebab-case"),
            ("", "cannot be empty"),
            ("a" * 129, "128 characters or less"),
        ],
    )
    async def test_invalid_session_id_returns_error(self, session_id, match):
        invoke_agent = _capture_registered(register_invoke_agent)
        with (
            patch("code_puppy.tools.agent_tools.emit_error") as mock_emit_error,
            patch(
                "code_puppy.tools.agent_tools.generate_group_id",
                return_value="test-group",
            ),
        ):
            result = await invoke_agent(
                MagicMock(),
                agent_name="test-agent",
                prompt="Hello",
                session_id=session_id,
            )
            assert isinstance(result, AgentInvokeOutput)
            assert result.response is None
            assert result.error is not None
            assert match in result.error
            assert mock_emit_error.called

    @pytest.mark.asyncio
    async def test_model_not_found_error(self):
        invoke_agent = _capture_registered(register_invoke_agent)
        mock_agent_config = MagicMock()
        mock_agent_config.get_model_name.return_value = "nonexistent-model"
        with (
            patch(
                "code_puppy.tools.agent_tools.generate_group_id",
                return_value="test-group",
            ),
            patch("code_puppy.tools.agent_tools.get_message_bus") as mock_bus,
            patch(
                "code_puppy.tools.agent_tools.get_session_context",
                return_value="parent",
            ),
            patch("code_puppy.tools.agent_tools.set_session_context"),
            patch("code_puppy.tools.agent_tools.emit_error") as mock_emit_error,
            patch(
                "code_puppy.agents.agent_manager.load_agent",
                return_value=mock_agent_config,
            ),
            patch("code_puppy.model_factory.ModelFactory.load_config", return_value={}),
            patch(
                "code_puppy.tools.agent_tools._load_session_history", return_value=[]
            ),
            patch(
                "code_puppy.tools.agent_tools._generate_session_hash_suffix",
                return_value="abc123",
            ),
        ):
            mock_bus.return_value.emit = MagicMock()
            result = await invoke_agent(
                MagicMock(),
                agent_name="test-agent",
                prompt="Hello",
                session_id=None,
            )
            assert result.error is not None
            assert "nonexistent-model" in result.error
            assert mock_emit_error.called

    @pytest.mark.asyncio
    async def test_session_context_restored_on_error(self):
        invoke_agent = _capture_registered(register_invoke_agent)
        mock_agent_config = MagicMock()
        mock_agent_config.get_model_name.return_value = "test-model"
        mock_agent_config.get_system_prompt.return_value = "Test"
        set_context_calls = []
        with (
            patch(
                "code_puppy.tools.agent_tools.generate_group_id",
                return_value="test-group",
            ),
            patch("code_puppy.tools.agent_tools.get_message_bus") as mock_bus,
            patch(
                "code_puppy.tools.agent_tools.get_session_context",
                return_value="original-parent",
            ),
            patch(
                "code_puppy.tools.agent_tools.set_session_context",
                side_effect=lambda x: set_context_calls.append(x),
            ),
            patch("code_puppy.tools.agent_tools.emit_error"),
            patch(
                "code_puppy.agents.agent_manager.load_agent",
                return_value=mock_agent_config,
            ),
            patch(
                "code_puppy.model_factory.ModelFactory.load_config",
                side_effect=RuntimeError("Config load failed"),
            ),
            patch(
                "code_puppy.tools.agent_tools._load_session_history", return_value=[]
            ),
            patch(
                "code_puppy.tools.agent_tools._generate_session_hash_suffix",
                return_value="abc123",
            ),
        ):
            mock_bus.return_value.emit = MagicMock()
            result = await invoke_agent(
                MagicMock(),
                agent_name="test-agent",
                prompt="Hello",
                session_id=None,
            )
            assert result.error is not None
            assert "original-parent" in set_context_calls


# --------------------------------------------------------------------------- #
# Partial-progress save on crash
# --------------------------------------------------------------------------- #
class TestInvokeAgentPartialSessionSaveOnCrash:
    """invoke_agent should save partial progress when the run blows up.

    The history processor mutates ``agent_config._message_history`` in place,
    so on a mid-run crash agent_config holds the last committed turn.
    """

    def _make_agent_config(self, partial_history):
        cfg = MagicMock()
        cfg.get_model_name.return_value = "test-model"
        cfg.get_system_prompt.return_value = "Test"
        cfg.get_message_history.return_value = partial_history
        return cfg

    @pytest.mark.asyncio
    async def test_partial_history_saved_when_run_crashes(self):
        invoke_agent = _capture_registered(register_invoke_agent)
        partial = ["msg_from_loaded_session", "new_turn_1", "new_turn_2"]
        mock_agent_config = self._make_agent_config(partial)
        with (
            patch(
                "code_puppy.tools.agent_tools.generate_group_id",
                return_value="test-group",
            ),
            patch("code_puppy.tools.agent_tools.get_message_bus") as mock_bus,
            patch(
                "code_puppy.tools.agent_tools.get_session_context",
                return_value="parent",
            ),
            patch("code_puppy.tools.agent_tools.set_session_context"),
            patch("code_puppy.tools.agent_tools.emit_error"),
            patch("code_puppy.tools.agent_tools.emit_info"),
            patch(
                "code_puppy.agents.agent_manager.load_agent",
                return_value=mock_agent_config,
            ),
            patch(
                "code_puppy.model_factory.ModelFactory.load_config",
                side_effect=RuntimeError("boom"),
            ),
            patch(
                "code_puppy.tools.agent_tools._load_session_history",
                return_value=["msg_from_loaded_session"],
            ),
            patch(
                "code_puppy.tools.agent_tools._generate_session_hash_suffix",
                return_value="abc123",
            ),
            patch("code_puppy.tools.agent_tools._save_session_history") as mock_save,
        ):
            mock_bus.return_value.emit = MagicMock()
            result = await invoke_agent(
                MagicMock(),
                agent_name="test-agent",
                prompt="do the thing",
                session_id=None,
            )
        assert result.error is not None
        assert mock_save.call_count == 1
        save_kwargs = mock_save.call_args.kwargs
        assert save_kwargs["message_history"] == partial
        assert save_kwargs["agent_name"] == "test-agent"
        assert save_kwargs["initial_prompt"] == "do the thing"

    @pytest.mark.asyncio
    async def test_no_save_when_no_progress_beyond_loaded_history(self):
        invoke_agent = _capture_registered(register_invoke_agent)
        loaded = ["m1", "m2"]
        mock_agent_config = self._make_agent_config(list(loaded))
        with (
            patch(
                "code_puppy.tools.agent_tools.generate_group_id",
                return_value="test-group",
            ),
            patch("code_puppy.tools.agent_tools.get_message_bus") as mock_bus,
            patch(
                "code_puppy.tools.agent_tools.get_session_context",
                return_value="parent",
            ),
            patch("code_puppy.tools.agent_tools.set_session_context"),
            patch("code_puppy.tools.agent_tools.emit_error"),
            patch("code_puppy.tools.agent_tools.emit_info"),
            patch(
                "code_puppy.agents.agent_manager.load_agent",
                return_value=mock_agent_config,
            ),
            patch(
                "code_puppy.model_factory.ModelFactory.load_config",
                side_effect=RuntimeError("boom"),
            ),
            patch(
                "code_puppy.tools.agent_tools._load_session_history",
                return_value=loaded,
            ),
            patch(
                "code_puppy.tools.agent_tools._generate_session_hash_suffix",
                return_value="abc123",
            ),
            patch("code_puppy.tools.agent_tools._save_session_history") as mock_save,
        ):
            mock_bus.return_value.emit = MagicMock()
            result = await invoke_agent(
                MagicMock(),
                agent_name="test-agent",
                prompt="x",
                session_id="existing-session-abc123",
            )
        assert result.error is not None
        mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_failure_does_not_mask_original_error(self):
        invoke_agent = _capture_registered(register_invoke_agent)
        partial = ["a", "b", "c", "d"]
        mock_agent_config = self._make_agent_config(partial)
        with (
            patch(
                "code_puppy.tools.agent_tools.generate_group_id",
                return_value="test-group",
            ),
            patch("code_puppy.tools.agent_tools.get_message_bus") as mock_bus,
            patch(
                "code_puppy.tools.agent_tools.get_session_context",
                return_value="parent",
            ),
            patch("code_puppy.tools.agent_tools.set_session_context"),
            patch("code_puppy.tools.agent_tools.emit_error"),
            patch("code_puppy.tools.agent_tools.emit_info"),
            patch(
                "code_puppy.agents.agent_manager.load_agent",
                return_value=mock_agent_config,
            ),
            patch(
                "code_puppy.model_factory.ModelFactory.load_config",
                side_effect=RuntimeError("original boom"),
            ),
            patch(
                "code_puppy.tools.agent_tools._load_session_history",
                return_value=["a"],
            ),
            patch(
                "code_puppy.tools.agent_tools._generate_session_hash_suffix",
                return_value="abc123",
            ),
            patch(
                "code_puppy.tools.agent_tools._save_session_history",
                side_effect=OSError("disk full"),
            ),
        ):
            mock_bus.return_value.emit = MagicMock()
            result = await invoke_agent(
                MagicMock(),
                agent_name="test-agent",
                prompt="x",
                session_id=None,
            )
        assert result.error is not None
        assert "original boom" in result.error

    @pytest.mark.asyncio
    async def test_load_agent_itself_crashes_no_save_attempted(self):
        """agent_config is None if load_agent raises — don't read it."""
        invoke_agent = _capture_registered(register_invoke_agent)
        with (
            patch(
                "code_puppy.tools.agent_tools.generate_group_id",
                return_value="test-group",
            ),
            patch("code_puppy.tools.agent_tools.get_message_bus") as mock_bus,
            patch(
                "code_puppy.tools.agent_tools.get_session_context",
                return_value="parent",
            ),
            patch("code_puppy.tools.agent_tools.set_session_context"),
            patch("code_puppy.tools.agent_tools.emit_error"),
            patch(
                "code_puppy.agents.agent_manager.load_agent",
                side_effect=RuntimeError("agent gone"),
            ),
            patch(
                "code_puppy.tools.agent_tools._load_session_history", return_value=[]
            ),
            patch(
                "code_puppy.tools.agent_tools._generate_session_hash_suffix",
                return_value="abc123",
            ),
            patch("code_puppy.tools.agent_tools._save_session_history") as mock_save,
        ):
            mock_bus.return_value.emit = MagicMock()
            result = await invoke_agent(
                MagicMock(),
                agent_name="test-agent",
                prompt="x",
                session_id=None,
            )
        assert result.error is not None
        mock_save.assert_not_called()


# --------------------------------------------------------------------------- #
# Module-level state
# --------------------------------------------------------------------------- #
def test_active_subagent_tasks_is_a_set():
    from code_puppy.tools.agent_tools import _active_subagent_tasks

    assert isinstance(_active_subagent_tasks, set)
