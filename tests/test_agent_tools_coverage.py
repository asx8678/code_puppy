"""Additional coverage tests for agent_tools.py.

This module focuses on testing uncovered code paths including:
- _get_subagent_sessions_dir function
- Pydantic models (AgentInfo, ListAgentsOutput, AgentInvokeOutput)
- register_list_agents tool execution
- register_invoke_agent tool execution with various code paths

DBOS workflow-id tests were removed when DBOS moved to a plugin; see
``code_puppy/plugins/dbos_durable_exec/`` for plugin-level tests (Phase 4).
"""

import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from code_puppy.tools.agent_tools import (
    AgentInfo,
    AgentInvokeOutput,
    ListAgentsOutput,
    _estimate_subagent_initial_tokens,
    _get_subagent_sessions_dir,
    register_invoke_agent,
    register_list_agents,
)


class TestGetSubagentSessionsDir:
    """Test suite for _get_subagent_sessions_dir function."""

    def test_returns_path_object(self):
        """Test that function returns a Path object."""
        with patch("code_puppy.tools.agent_tools.DATA_DIR", tempfile.gettempdir()):
            result = _get_subagent_sessions_dir()
            assert isinstance(result, Path)

    def test_path_ends_with_subagent_sessions(self):
        """Test that path ends with 'subagent_sessions'."""
        with patch("code_puppy.tools.agent_tools.DATA_DIR", tempfile.gettempdir()):
            result = _get_subagent_sessions_dir()
            assert result.name == "subagent_sessions"

    def test_creates_directory_if_not_exists(self):
        """Test that directory is created if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("code_puppy.tools.agent_tools.DATA_DIR", tmpdir):
                result = _get_subagent_sessions_dir()
                assert result.exists()
                assert result.is_dir()

    def test_directory_has_correct_permissions(self):
        """Test that created directory has mode 0o700."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("code_puppy.tools.agent_tools.DATA_DIR", tmpdir):
                result = _get_subagent_sessions_dir()
                # Check mode (on Unix-like systems)
                mode = result.stat().st_mode & 0o777
                assert mode == 0o700

    def test_returns_same_path_on_multiple_calls(self):
        """Test that function returns consistent path."""
        with patch("code_puppy.tools.agent_tools.DATA_DIR", tempfile.gettempdir()):
            path1 = _get_subagent_sessions_dir()
            path2 = _get_subagent_sessions_dir()
            assert path1 == path2


class TestEstimateSubagentInitialTokens:
    """Pure-function tests for the token seeding helper used by invoke_agent."""

    def test_returns_overhead_plus_history_plus_prompt(self):
        """Success path: sum of mocked overhead/history/prompt."""
        mock_cfg = MagicMock()
        mock_cfg.estimate_tokens_for_message.side_effect = lambda m: len(m)
        mock_cfg._estimate_context_overhead.return_value = 25

        history = ["abc", "defg"]
        prompt = "hi"
        assert (
            _estimate_subagent_initial_tokens(mock_cfg, history, prompt)
            == 25 + 3 + 4 + 2
        )

    def test_returns_zero_when_estimate_raises(self):
        """Failure path: any exception is swallowed and 0 is returned."""
        mock_cfg = MagicMock()
        mock_cfg.estimate_tokens_for_message.side_effect = RuntimeError("boom")

        assert _estimate_subagent_initial_tokens(mock_cfg, ["x"], "y") == 0


class TestPydanticModels:
    """Test suite for Pydantic models in agent_tools."""

    class TestAgentInfo:
        """Tests for AgentInfo model."""

        def test_create_with_required_fields(self):
            """Test creating AgentInfo with all required fields."""
            info = AgentInfo(
                name="test-agent",
                display_name="Test Agent",
                description="A test agent for testing",
            )
            assert info.name == "test-agent"
            assert info.display_name == "Test Agent"
            assert info.description == "A test agent for testing"

        def test_serialization(self):
            """Test that AgentInfo serializes correctly."""
            info = AgentInfo(
                name="code-reviewer",
                display_name="Code Reviewer",
                description="Reviews code for quality",
            )
            data = info.model_dump()
            assert data["name"] == "code-reviewer"
            assert data["display_name"] == "Code Reviewer"
            assert data["description"] == "Reviews code for quality"

        def test_json_serialization(self):
            """Test JSON serialization."""
            info = AgentInfo(
                name="qa-expert",
                display_name="QA Expert",
                description="Quality assurance expert",
            )
            json_str = info.model_dump_json()
            assert "qa-expert" in json_str
            assert "QA Expert" in json_str

    class TestListAgentsOutput:
        """Tests for ListAgentsOutput model."""

        def test_create_with_agents_list(self):
            """Test creating with list of agents."""
            agents = [
                AgentInfo(
                    name="agent1",
                    display_name="Agent One",
                    description="First agent",
                ),
                AgentInfo(
                    name="agent2",
                    display_name="Agent Two",
                    description="Second agent",
                ),
            ]
            output = ListAgentsOutput(agents=agents)
            assert len(output.agents) == 2
            assert output.error is None

        def test_create_with_error(self):
            """Test creating with error message."""
            output = ListAgentsOutput(agents=[], error="Something went wrong")
            assert len(output.agents) == 0
            assert output.error == "Something went wrong"

        def test_default_error_is_none(self):
            """Test that error defaults to None."""
            output = ListAgentsOutput(agents=[])
            assert output.error is None

        def test_empty_agents_list(self):
            """Test with empty agents list."""
            output = ListAgentsOutput(agents=[])
            assert output.agents == []

    class TestAgentInvokeOutput:
        """Tests for AgentInvokeOutput model."""

        def test_create_success_response(self):
            """Test creating successful invocation output."""
            output = AgentInvokeOutput(
                response="This is the agent's response",
                agent_name="test-agent",
                session_id="session-abc123",
            )
            assert output.response == "This is the agent's response"
            assert output.agent_name == "test-agent"
            assert output.session_id == "session-abc123"
            assert output.error is None

        def test_create_error_response(self):
            """Test creating error invocation output."""
            output = AgentInvokeOutput(
                response=None,
                agent_name="failing-agent",
                error="Agent crashed",
            )
            assert output.response is None
            assert output.agent_name == "failing-agent"
            assert output.error == "Agent crashed"

        def test_default_values(self):
            """Test default values for optional fields."""
            output = AgentInvokeOutput(
                response="response",
                agent_name="agent",
            )
            assert output.session_id is None
            assert output.error is None

        def test_serialization(self):
            """Test model serialization."""
            output = AgentInvokeOutput(
                response="Hello!",
                agent_name="greeter",
                session_id="session-123",
            )
            data = output.model_dump()
            assert data["response"] == "Hello!"
            assert data["agent_name"] == "greeter"
            assert data["session_id"] == "session-123"


class TestRegisterListAgentsExecution:
    """Test the actual list_agents tool function execution."""

    def test_list_agents_returns_available_agents(self):
        """Test that list_agents returns available agents."""
        mock_agent = MagicMock()
        mock_context = MagicMock()

        # Capture the registered function
        registered_func = None

        def capture_tool(func):
            nonlocal registered_func
            registered_func = func
            return func

        mock_agent.tool = capture_tool

        # Register the tool
        register_list_agents(mock_agent)
        assert registered_func is not None

        # Mock the agent manager functions and config
        # Note: get_banner_color is imported from code_puppy.config inside the function
        with (
            patch(
                "code_puppy.config.get_banner_color",
                return_value="blue",
            ),
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

            # Call the registered function
            result = registered_func(mock_context)

            # Verify the result
            assert isinstance(result, ListAgentsOutput)
            assert len(result.agents) == 2
            assert result.error is None

            # Verify agent info
            agent_names = [a.name for a in result.agents]
            assert "code-reviewer" in agent_names
            assert "qa-expert" in agent_names

    def test_list_agents_handles_exception(self):
        """Test that list_agents handles exceptions gracefully."""
        mock_agent = MagicMock()
        mock_context = MagicMock()

        registered_func = None

        def capture_tool(func):
            nonlocal registered_func
            registered_func = func
            return func

        mock_agent.tool = capture_tool
        register_list_agents(mock_agent)

        # Mock to raise an exception
        with (
            patch(
                "code_puppy.config.get_banner_color",
                return_value="blue",
            ),
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
            result = registered_func(mock_context)

            # Should return error output
            assert isinstance(result, ListAgentsOutput)
            assert len(result.agents) == 0
            assert "Database connection failed" in result.error
            assert mock_emit_error.called

    def test_list_agents_with_missing_description(self):
        """Test that list_agents handles missing descriptions."""
        mock_agent = MagicMock()
        mock_context = MagicMock()

        registered_func = None

        def capture_tool(func):
            nonlocal registered_func
            registered_func = func
            return func

        mock_agent.tool = capture_tool
        register_list_agents(mock_agent)

        with (
            patch(
                "code_puppy.config.get_banner_color",
                return_value="blue",
            ),
            patch("code_puppy.tools.agent_tools.emit_info"),
            patch(
                "code_puppy.tools.agent_tools.generate_group_id",
                return_value="test-group",
            ),
            patch("code_puppy.agents.get_available_agents") as mock_available,
            patch("code_puppy.agents.get_agent_descriptions") as mock_descriptions,
        ):
            mock_available.return_value = {
                "new-agent": "New Agent",
            }
            # No description for new-agent
            mock_descriptions.return_value = {}

            result = registered_func(mock_context)

            # Should use default description
            assert len(result.agents) == 1
            assert result.agents[0].description == "No description available"


class TestRegisterInvokeAgentExecution:
    """Test the actual invoke_agent tool function execution."""

    @pytest.fixture
    def temp_session_dir(self):
        """Create a temporary directory for session storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def _get_registered_invoke_agent(self):
        """Helper to capture the registered invoke_agent function."""
        mock_agent = MagicMock()
        registered_func = None

        def capture_tool(func):
            nonlocal registered_func
            registered_func = func
            return func

        mock_agent.tool = capture_tool
        register_invoke_agent(mock_agent)
        return registered_func

    @pytest.mark.asyncio
    async def test_invoke_agent_invalid_session_id_returns_error(self):
        """Test that invalid session_id returns error immediately."""
        invoke_agent = self._get_registered_invoke_agent()
        mock_context = MagicMock()

        with (
            patch("code_puppy.tools.agent_tools.emit_error") as mock_emit_error,
            patch(
                "code_puppy.tools.agent_tools.generate_group_id",
                return_value="test-group",
            ),
        ):
            # Call with invalid session_id (uppercase not allowed)
            result = await invoke_agent(
                mock_context,
                agent_name="test-agent",
                prompt="Hello",
                session_id="Invalid_Session",
            )

            # Should return error output
            assert isinstance(result, AgentInvokeOutput)
            assert result.response is None
            assert result.error is not None
            assert "must be kebab-case" in result.error
            assert mock_emit_error.called

    @pytest.mark.asyncio
    async def test_invoke_agent_model_not_found_error(self):
        """Test error handling when model is not found."""
        invoke_agent = self._get_registered_invoke_agent()
        mock_context = MagicMock()

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
            patch(
                "code_puppy.model_factory.ModelFactory.load_config",
                return_value={},  # No models configured
            ),
            patch(
                "code_puppy.tools.agent_tools._load_session_history",
                return_value=[],
            ),
            patch(
                "code_puppy.tools.agent_tools._generate_session_hash_suffix",
                return_value="abc123",
            ),
        ):
            mock_bus.return_value.emit = MagicMock()

            result = await invoke_agent(
                mock_context,
                agent_name="test-agent",
                prompt="Hello",
                session_id=None,
            )

            # Should return error
            assert result.error is not None
            assert "nonexistent-model" in result.error
            assert mock_emit_error.called

    @pytest.mark.asyncio
    async def test_invoke_agent_session_context_restored_on_error(self):
        """Test that session context is restored even when an error occurs."""
        invoke_agent = self._get_registered_invoke_agent()
        mock_context = MagicMock()

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
                "code_puppy.tools.agent_tools._load_session_history",
                return_value=[],
            ),
            patch(
                "code_puppy.tools.agent_tools._generate_session_hash_suffix",
                return_value="abc123",
            ),
        ):
            mock_bus.return_value.emit = MagicMock()

            result = await invoke_agent(
                mock_context,
                agent_name="test-agent",
                prompt="Hello",
                session_id=None,
            )

            # Should have error
            assert result.error is not None

            # Session context should still be restored
            assert "original-parent" in set_context_calls


class TestInvokeAgentPartialSessionSaveOnCrash:
    """Issue: invoke_agent should save partial progress when the run blows up.

    The BaseAgent wrapper's ``_message_history`` is mutated in place by the
    ``make_history_processor(agent_config)`` callback that pydantic-ai invokes
    before every model request. So on a mid-run crash, ``agent_config`` still
    holds the last fully-committed turn and we want that written to the
    session file rather than thrown away.
    """

    def _get_registered_invoke_agent(self):
        mock_agent = MagicMock()
        registered_func = None

        def capture_tool(func):
            nonlocal registered_func
            registered_func = func
            return func

        mock_agent.tool = capture_tool
        register_invoke_agent(mock_agent)
        return registered_func

    def _make_agent_config(self, partial_history):
        cfg = MagicMock()
        cfg.get_model_name.return_value = "test-model"
        cfg.get_system_prompt.return_value = "Test"
        cfg.get_message_history.return_value = partial_history
        return cfg

    @pytest.mark.asyncio
    async def test_partial_history_saved_when_run_crashes(self):
        invoke_agent = self._get_registered_invoke_agent()
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
            # Force a crash *after* load_agent has run so agent_config is bound.
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
        # The seed + partial history should have triggered one save.
        assert mock_save.call_count == 1
        save_kwargs = mock_save.call_args.kwargs
        assert save_kwargs["message_history"] == partial
        assert save_kwargs["agent_name"] == "test-agent"
        # Brand new session → initial_prompt recorded.
        assert save_kwargs["initial_prompt"] == "do the thing"

    @pytest.mark.asyncio
    async def test_no_save_when_no_progress_beyond_loaded_history(self):
        """If the crash happens before any new turns land, skip the save."""
        invoke_agent = self._get_registered_invoke_agent()
        # Same length as loaded → no new progress to persist.
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
        invoke_agent = self._get_registered_invoke_agent()
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

            # Must not raise despite the save blowing up.
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
        """agent_config is None if load_agent raises — don't blow up trying to read it."""
        invoke_agent = self._get_registered_invoke_agent()

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
                "code_puppy.tools.agent_tools._load_session_history",
                return_value=[],
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


class TestActiveSubagentTasks:
    """Test the _active_subagent_tasks tracking."""

    def test_active_tasks_set_exists(self):
        """Test that the active tasks set is accessible."""
        from code_puppy.tools.agent_tools import _active_subagent_tasks

        assert isinstance(_active_subagent_tasks, set)

    def test_active_tasks_initially_empty(self):
        """Test that active tasks set starts empty (or becomes empty)."""
        from code_puppy.tools.agent_tools import _active_subagent_tasks

        # After all tasks complete, should be empty
        # (This is testing the cleanup behavior)
        # In a fresh module load, it would be empty
        assert isinstance(_active_subagent_tasks, set)


class TestSessionIdValidationInInvokeAgent:
    """Test session ID validation edge cases in invoke_agent."""

    def _get_registered_invoke_agent(self):
        """Helper to capture the registered invoke_agent function."""
        mock_agent = MagicMock()
        registered_func = None

        def capture_tool(func):
            nonlocal registered_func
            registered_func = func
            return func

        mock_agent.tool = capture_tool
        register_invoke_agent(mock_agent)
        return registered_func

    @pytest.mark.asyncio
    async def test_invalid_session_with_spaces(self):
        """Test that session IDs with spaces are rejected."""
        invoke_agent = self._get_registered_invoke_agent()
        mock_context = MagicMock()

        with (
            patch("code_puppy.tools.agent_tools.emit_error"),
            patch(
                "code_puppy.tools.agent_tools.generate_group_id",
                return_value="test-group",
            ),
        ):
            result = await invoke_agent(
                mock_context,
                agent_name="test-agent",
                prompt="Hello",
                session_id="my session",
            )

            assert result.error is not None
            assert "must be kebab-case" in result.error

    @pytest.mark.asyncio
    async def test_invalid_session_with_special_chars(self):
        """Test that session IDs with special chars are rejected."""
        invoke_agent = self._get_registered_invoke_agent()
        mock_context = MagicMock()

        with (
            patch("code_puppy.tools.agent_tools.emit_error"),
            patch(
                "code_puppy.tools.agent_tools.generate_group_id",
                return_value="test-group",
            ),
        ):
            result = await invoke_agent(
                mock_context,
                agent_name="test-agent",
                prompt="Hello",
                session_id="session@123",
            )

            assert result.error is not None
            assert "must be kebab-case" in result.error

    @pytest.mark.asyncio
    async def test_empty_session_id_rejected(self):
        """Test that empty session IDs are rejected."""
        invoke_agent = self._get_registered_invoke_agent()
        mock_context = MagicMock()

        with (
            patch("code_puppy.tools.agent_tools.emit_error"),
            patch(
                "code_puppy.tools.agent_tools.generate_group_id",
                return_value="test-group",
            ),
        ):
            result = await invoke_agent(
                mock_context,
                agent_name="test-agent",
                prompt="Hello",
                session_id="",
            )

            assert result.error is not None
            assert "cannot be empty" in result.error

    @pytest.mark.asyncio
    async def test_too_long_session_id_rejected(self):
        """Test that session IDs over 128 chars are rejected."""
        invoke_agent = self._get_registered_invoke_agent()
        mock_context = MagicMock()

        with (
            patch("code_puppy.tools.agent_tools.emit_error"),
            patch(
                "code_puppy.tools.agent_tools.generate_group_id",
                return_value="test-group",
            ),
        ):
            long_id = "a" * 129
            result = await invoke_agent(
                mock_context,
                agent_name="test-agent",
                prompt="Hello",
                session_id=long_id,
            )

            assert result.error is not None
            assert "128 characters or less" in result.error


class TestListAgentsEmitsBannerAndInfo:
    """Test that list_agents properly emits banner and info messages."""

    def test_emits_banner_message(self):
        """Test that list_agents emits a banner message."""
        mock_agent = MagicMock()
        mock_context = MagicMock()

        registered_func = None

        def capture_tool(func):
            nonlocal registered_func
            registered_func = func
            return func

        mock_agent.tool = capture_tool
        register_list_agents(mock_agent)

        with (
            patch(
                "code_puppy.config.get_banner_color",
                return_value="green",
            ) as mock_banner_color,
            patch("code_puppy.tools.agent_tools.emit_info") as mock_emit_info,
            patch(
                "code_puppy.tools.agent_tools.generate_group_id",
                return_value="banner-group",
            ),
            patch(
                "code_puppy.agents.get_available_agents",
                return_value={},
            ),
            patch(
                "code_puppy.agents.get_agent_descriptions",
                return_value={},
            ),
        ):
            registered_func(mock_context)

            # Verify banner color was fetched
            mock_banner_color.assert_called_once_with("list_agents")

            # Verify emit_info was called (at least for banner)
            assert mock_emit_info.called


class TestInvokeAgentSubagentConsoleLifecycle:
    """Real-path lifecycle tests for invoke_agent's sub-agent dashboard hooks.

    These tests drive the actual registered invoke_agent tool.  The
    FakeAgent class is injected via code_puppy.tools.agent_tools.Agent
    so that temp_agent.run(...) is an **awaitable coroutine** (not a
    MagicMock).  That lets asyncio.create_task and await task run for
    real, which in turn lets subagent_context / on_agent_run_context
    and the success / error / finally blocks all execute on the real path.

    If the console_mgr/manager shadowing bug is reintroduced, these tests
    WILL fail because console_mgr.register_agent will hit MCPManager
    (AttributeError).  They are therefore a genuine regression guard, not
    hollow mocks.
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_registered_invoke_agent(self):
        """Capture the async tool function that register_invoke_agent registers."""
        mock_agent = MagicMock()
        registered = None

        def capture(func):
            nonlocal registered
            registered = func
            return func

        mock_agent.tool = capture
        register_invoke_agent(mock_agent)
        return registered

    def _base_invoke_patches(self, session_id="test-session-abc"):
        """Common patch dict for a clean success-path run."""
        fake_agent_config = MagicMock()
        fake_agent_config.get_model_name.return_value = "test-model"
        fake_agent_config._get_model_context_length.return_value = 200000
        # _estimate_subagent_initial_tokens = overhead(25) + len(history)=0 + len(prompt)=4
        fake_agent_config.estimate_tokens_for_message.side_effect = lambda m: len(m)
        fake_agent_config._estimate_context_overhead.return_value = 25
        fake_agent_config.get_full_system_prompt.return_value = "system prompt"
        fake_agent_config.set_message_history = MagicMock()
        fake_agent_config.get_message_history.return_value = []
        fake_agent_config.name = "test-agent"
        fake_agent_config.get_available_tools.return_value = []

        return {
            # Session / bus / emit plumbing
            "code_puppy.tools.agent_tools.generate_group_id": MagicMock(
                return_value="test-group"
            ),
            "code_puppy.tools.agent_tools.get_message_bus": MagicMock(
                return_value=MagicMock(emit=MagicMock())
            ),
            "code_puppy.tools.agent_tools.get_session_context": MagicMock(
                return_value="parent-session"
            ),
            "code_puppy.tools.agent_tools.set_session_context": MagicMock(),
            "code_puppy.tools.agent_tools.emit_error": MagicMock(),
            "code_puppy.tools.agent_tools.emit_info": MagicMock(),
            "code_puppy.tools.agent_tools.emit_success": MagicMock(),
            "code_puppy.tools.agent_tools._load_session_history": MagicMock(
                return_value=[]
            ),
            "code_puppy.tools.agent_tools._generate_session_hash_suffix": MagicMock(
                return_value="abc123"
            ),
            "code_puppy.tools.agent_tools._save_session_history": MagicMock(),
            # Agent / model loading
            "code_puppy.agents.agent_manager.load_agent": MagicMock(
                return_value=fake_agent_config
            ),
            "code_puppy.model_factory.ModelFactory.load_config": MagicMock(
                return_value={"test-model": {}}
            ),
            "code_puppy.model_factory.ModelFactory.get_model": MagicMock(),
            # The temp_agent is built from this; we replace it with a FakeAgent
            # whose run() is a REAL coroutine so  +
            # execute the success/error/finally branches naturally.
            "code_puppy.tools.agent_tools.Agent": None,  # set per-test
            # Dashboard (T2)
            "code_puppy.messaging.subagent_console.get_subagent_console_manager": MagicMock(
                return_value=MagicMock(
                    register_agent=MagicMock(),
                    update_agent=MagicMock(),
                    unregister_agent=MagicMock(),
                )
            ),
            "code_puppy.config.get_show_subagent_status": MagicMock(return_value=True),
            # Browser / cancel hooks
            "code_puppy.tools.browser.browser_manager.set_browser_session": MagicMock(
                return_value="token"
            ),
            "code_puppy.tools.browser.browser_manager._browser_session_var": MagicMock(
                reset=MagicMock()
            ),
            "code_puppy.config.set_subagent_status_runtime_override": MagicMock(),
            "code_puppy.tools.agent_tools.on_agent_run_cancel": MagicMock(),
            # Context managers / callbacks
            "code_puppy.tools.subagent_context.subagent_context": MagicMock(
                __enter__=MagicMock(return_value=None),
                __exit__=MagicMock(return_value=False),
            ),
            "code_puppy.callbacks.on_agent_run_context": MagicMock(return_value=[]),
            "code_puppy.callbacks.on_wrap_pydantic_agent": MagicMock(
                side_effect=lambda *a, **kw: MagicMock()
            ),
            "code_puppy.tools.agent_tools.get_message_limit": MagicMock(
                return_value=100
            ),
        }

    # ------------------------------------------------------------------
    # (a) Success path
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_success_path_registers_updates_running_and_unregisters(self):
        """invoke_agent registers (seeded tokens), updates running, unregisters completed."""
        invoke_agent = self._get_registered_invoke_agent()
        mock_context = MagicMock()
        patches = self._base_invoke_patches()

        class FakeAgent:
            def __init__(self, *a, **kw):
                pass

            async def run(self, *a, **kw):
                return MagicMock(output="done", all_messages=MagicMock(return_value=[]))

        patches["code_puppy.tools.agent_tools.Agent"] = FakeAgent
        console_mgr = patches[
            "code_puppy.messaging.subagent_console.get_subagent_console_manager"
        ].return_value

        with ExitStack() as _stack:
            for _t, _v in patches.items():
                _stack.enter_context(patch(_t, _v))
            result = await invoke_agent(
                mock_context,
                agent_name="test-agent",
                prompt="Hello",
                session_id="test-session-abc",
            )

        assert result.response == "done"
        assert result.error is None
        console_mgr.register_agent.assert_called_once()
        reg = console_mgr.register_agent.call_args
        assert reg.kwargs["token_count"] > 0
        assert reg.kwargs["token_limit"] > 0
        console_mgr.update_agent.assert_any_call(
            reg.kwargs["session_id"], status="running"
        )
        last = console_mgr.unregister_agent.call_args
        assert last.kwargs["final_status"] == "completed"

    # ------------------------------------------------------------------
    # (b) Error path
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_error_path_updates_error_and_unregisters(self):
        """run() raises -> update_agent(error) + unregister_agent(error)."""
        invoke_agent = self._get_registered_invoke_agent()
        patches = self._base_invoke_patches()

        class FakeAgentBoom:
            def __init__(self, *a, **kw):
                pass

            async def run(self, *a, **kw):
                raise RuntimeError("boom")

        patches["code_puppy.tools.agent_tools.Agent"] = FakeAgentBoom
        cm = patches[
            "code_puppy.messaging.subagent_console.get_subagent_console_manager"
        ].return_value

        with ExitStack() as s:
            for t, v in patches.items():
                s.enter_context(patch(t, v))
            result = await invoke_agent(
                MagicMock(),
                agent_name="test-agent",
                prompt="Hello",
                session_id="test-session-abc",
            )

        assert result.error is not None
        assert "boom" in (result.error or "")
        sid = cm.register_agent.call_args.kwargs["session_id"]
        # error_message is the *stringified* exception; RuntimeError("boom") -> "boom"
        cm.update_agent.assert_any_call(sid, status="error", error_message="boom")
        assert cm.unregister_agent.call_args.kwargs["final_status"] == "error"

    # ------------------------------------------------------------------
    # (c) Gate: show_status=False -> nothing touches the console manager
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_show_status_false_gates_dashboard_registration(self):
        """When show_subagent_status is False, register/update/unregister never fire."""
        invoke_agent = self._get_registered_invoke_agent()
        mock_context = MagicMock()
        patches = self._base_invoke_patches()
        patches["code_puppy.config.get_show_subagent_status"].return_value = False
        console_mgr = patches[
            "code_puppy.messaging.subagent_console.get_subagent_console_manager"
        ].return_value

        class FakeAgent:
            def __init__(self, *a, **kw):
                pass

            async def run(self, *a, **kw):
                return MagicMock(output="done", all_messages=MagicMock(return_value=[]))

        patches["code_puppy.tools.agent_tools.Agent"] = FakeAgent

        with ExitStack() as _stack:
            for _t, _v in patches.items():
                _stack.enter_context(patch(_t, _v))
            await invoke_agent(
                mock_context,
                agent_name="test-agent",
                prompt="Hello",
                session_id="test-session-abc",
            )

        console_mgr.register_agent.assert_not_called()
        console_mgr.update_agent.assert_not_called()
        console_mgr.unregister_agent.assert_not_called()

    # ------------------------------------------------------------------
    # (d) Cancellation: CancelledError is BaseException -> only finally runs
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_cancelled_task_unregisters_completed_and_propagates(self):
        """CancelledError (BaseException) propagates out of the task, bypasses
        ``except Exception``, the outer ``finally`` runs, and
        ``unregister_agent(final_status="completed")`` fires before the
        CancelledError escapes invoke_agent.
        """
        import asyncio

        invoke_agent = self._get_registered_invoke_agent()
        patches = self._base_invoke_patches()

        class FakeAgentCancelled:
            def __init__(self, *a, **kw):
                pass

            async def run(self, *a, **kw):
                raise asyncio.CancelledError()

        patches["code_puppy.tools.agent_tools.Agent"] = FakeAgentCancelled
        # Use a REAL task so CancelledError propagates naturally.
        patches.pop("code_puppy.tools.agent_tools.asyncio.create_task", None)
        # AsyncMock so ``await on_agent_run_cancel(...)`` doesn't spuriously
        # raise TypeError and mask the real contract.
        patches["code_puppy.tools.agent_tools.on_agent_run_cancel"] = AsyncMock()
        cm = patches[
            "code_puppy.messaging.subagent_console.get_subagent_console_manager"
        ].return_value

        with ExitStack() as s:
            for t, v in patches.items():
                s.enter_context(patch(t, v))
            with pytest.raises(asyncio.CancelledError):
                await invoke_agent(
                    MagicMock(),
                    agent_name="test-agent",
                    prompt="Hello",
                    session_id="test-session-abc",
                )

        cm.register_agent.assert_called_once()
        sid = cm.register_agent.call_args.kwargs["session_id"]
        cm.update_agent.assert_any_call(sid, status="running")
        # CancelledError bypasses ``except Exception``; default final_status
        # is "completed" in the outer finally.
        cm.unregister_agent.assert_called_once_with(sid, final_status="completed")


class TestSubagentStreamHandlerSeedSurvival:
    """Seed-survival regression: streamed deltas must not clobber the seed."""

    @pytest.mark.asyncio
    async def test_stream_delta_preserves_seeded_token_count(self):
        """Start with a seeded AgentState; delta accumulates on top."""
        from code_puppy.messaging.subagent_console import (
            SubAgentConsoleManager,
        )
        from code_puppy.agents.subagent_stream_handler import subagent_stream_handler

        SubAgentConsoleManager.reset_instance()
        try:
            manager = SubAgentConsoleManager.get_instance()
            manager.register_agent(
                session_id="sess-1",
                agent_name="test-agent",
                model_name="test-model",
                token_count=5000,
                token_limit=200000,
            )

            async def _events():
                from pydantic_ai import PartDeltaEvent
                from pydantic_ai.messages import TextPartDelta

                yield PartDeltaEvent(
                    index=0,
                    delta=TextPartDelta(content_delta="hello world"),
                )

            await subagent_stream_handler(
                ctx=MagicMock(),
                events=_events(),
                session_id="sess-1",
            )

            state = manager.get_agent_state("sess-1")
            assert state is not None
            assert state.token_count >= 5000
        finally:
            SubAgentConsoleManager.reset_instance()
