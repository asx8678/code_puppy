"""Tests for get_platform_info() and updated get_full_system_prompt()."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

import code_puppy.agents.base_agent as base_agent_module


class ConcreteAgent(base_agent_module.BaseAgent):
    @property
    def name(self) -> str:
        return "test-agent"

    @property
    def display_name(self) -> str:
        return "Test Agent"

    @property
    def description(self) -> str:
        return "A test agent"

    def get_system_prompt(self) -> str:
        return "You are a test agent."

    def get_available_tools(self) -> list:
        return []


@pytest.fixture
def agent():
    return ConcreteAgent()


class TestGetPlatformInfo:
    def test_contains_platform(self, agent):
        info = agent.get_platform_info()
        assert "- Platform:" in info

    def test_contains_shell(self, agent):
        info = agent.get_platform_info()
        assert "- Shell:" in info

    def test_contains_date(self, agent):
        info = agent.get_platform_info()
        assert "- Current date:" in info
        # Date should be in YYYY-MM-DD format
        import re

        assert re.search(r"\d{4}-\d{2}-\d{2}", info)

    def test_contains_working_directory(self, agent):
        info = agent.get_platform_info()
        assert "- Working directory:" in info
        assert os.getcwd() in info

    def test_git_detection_when_present(self, agent, tmp_path):
        """When .git dir exists, should mention git repo."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        with patch("os.getcwd", return_value=str(tmp_path)):
            # Patch Path(".git").is_dir() to check our tmp dir
            original_is_dir = Path.is_dir

            def mock_is_dir(self_path):
                if str(self_path) == ".git":
                    return git_dir.is_dir()
                return original_is_dir(self_path)

            with patch.object(Path, "is_dir", mock_is_dir):
                info = agent.get_platform_info()
                assert "git repository" in info

    def test_no_git_when_absent(self, agent, tmp_path):
        """When .git dir doesn't exist, should not mention git."""
        with patch("os.getcwd", return_value=str(tmp_path)):
            original_is_dir = Path.is_dir

            def mock_is_dir(self_path):
                if str(self_path) == ".git":
                    return False
                return original_is_dir(self_path)

            with patch.object(Path, "is_dir", mock_is_dir):
                info = agent.get_platform_info()
                assert "git repository" not in info

    def test_shell_var_unix(self, agent):
        with patch("os.name", "posix"):
            with patch.dict(os.environ, {"SHELL": "/bin/bash"}):
                info = agent.get_platform_info()
                assert "SHELL=/bin/bash" in info

    def test_shell_var_windows(self, agent):
        with patch("os.name", "nt"):
            with patch.dict(os.environ, {"COMSPEC": "C:\\Windows\\cmd.exe"}):
                info = agent.get_platform_info()
                assert "COMSPEC=" in info

    def test_platform_error_handled(self, agent):
        """If platform.platform() raises, should fall back gracefully."""
        import platform as _platform

        with patch.object(_platform, "platform", side_effect=Exception("boom")):
            info = agent.get_platform_info()
            assert "- Platform: unknown" in info


class TestGetFullSystemPrompt:
    def test_includes_base_prompt(self, agent):
        prompt = agent.get_full_system_prompt()
        assert "You are a test agent." in prompt

    def test_includes_environment_section(self, agent):
        prompt = agent.get_full_system_prompt()
        assert "# Environment" in prompt
        assert "- Platform:" in prompt

    def test_includes_identity(self, agent):
        prompt = agent.get_full_system_prompt()
        assert "Your ID is" in prompt

    def test_ordering(self, agent):
        """Environment should come after base prompt, before identity."""
        prompt = agent.get_full_system_prompt()
        base_idx = prompt.index("You are a test agent.")
        env_idx = prompt.index("# Environment")
        id_idx = prompt.index("Your ID is")
        assert base_idx < env_idx < id_idx
