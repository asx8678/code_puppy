"""Integration tests for prompt_store prompt assembly behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from code_puppy import callbacks
from code_puppy.model_utils import get_claude_code_instructions, prepare_prompt_for_model
from code_puppy.plugins.agent_skills.register_callbacks import _inject_skills_into_prompt
from code_puppy.plugins.prompt_store.commands import load_custom_prompt
from code_puppy.plugins.repo_compass.register_callbacks import _inject_repo_context


@pytest.fixture
def isolated_prompt_callbacks():
    """Temporarily isolate prompt-related callback phases for integration tests."""
    saved_load = callbacks.get_callbacks("load_prompt")
    saved_model = callbacks.get_callbacks("get_model_system_prompt")
    callbacks.clear_callbacks("load_prompt")
    callbacks.clear_callbacks("get_model_system_prompt")
    try:
        yield
    finally:
        callbacks.clear_callbacks("load_prompt")
        callbacks.clear_callbacks("get_model_system_prompt")
        for callback in saved_load:
            callbacks.register_callback("load_prompt", callback)
        for callback in saved_model:
            callbacks.register_callback("get_model_system_prompt", callback)


def _assemble_system_prompt(base_prompt: str) -> str:
    """Build the full system prompt the same way agents do before model prep."""
    prompt_additions = [addition for addition in callbacks.on_load_prompt() if addition]
    if not prompt_additions:
        return base_prompt
    return base_prompt + "\n" + "\n".join(prompt_additions)


def _patch_prompt_sources():
    """Patch prompt-producing helpers with predictable test content."""
    mock_template = MagicMock()
    mock_template.content = "PROMPT_STORE_SECTION"
    mock_store = MagicMock()
    mock_store.get_active_for_agent.return_value = mock_template
    return (
        patch(
            "code_puppy.plugins.prompt_store.commands.get_current_agent_name",
            return_value="code-puppy",
        ),
        patch(
            "code_puppy.plugins.prompt_store.commands._get_store",
            return_value=mock_store,
        ),
        patch(
            "code_puppy.plugins.agent_skills.register_callbacks._get_skills_prompt_section",
            return_value="SKILLS_SECTION",
        ),
        patch(
            "code_puppy.plugins.repo_compass.register_callbacks._build_repo_context",
            return_value="REPO_CONTEXT",
        ),
    )


class TestPromptStoreIntegration:
    def test_prompt_store_skills_and_repo_compass_all_reach_final_prompt(
        self, isolated_prompt_callbacks
    ):
        callbacks.register_callback("load_prompt", load_custom_prompt)
        callbacks.register_callback(
            "get_model_system_prompt", _inject_skills_into_prompt
        )
        callbacks.register_callback("get_model_system_prompt", _inject_repo_context)

        with (
            _patch_prompt_sources()[0],
            _patch_prompt_sources()[1],
            _patch_prompt_sources()[2],
            _patch_prompt_sources()[3],
        ):
            assembled = _assemble_system_prompt("BASE_PROMPT")
            prepared = prepare_prompt_for_model("gpt-4o-mini", assembled, "USER_PROMPT")

        assert "BASE_PROMPT" in prepared.instructions
        assert "PROMPT_STORE_SECTION" in prepared.instructions
        assert "SKILLS_SECTION" in prepared.instructions
        assert "REPO_CONTEXT" in prepared.instructions

    def test_model_system_prompt_callbacks_receive_chained_prompt_state(
        self, isolated_prompt_callbacks
    ):
        callbacks.register_callback(
            "get_model_system_prompt", _inject_skills_into_prompt
        )
        callbacks.register_callback("get_model_system_prompt", _inject_repo_context)

        with (
            patch(
                "code_puppy.plugins.agent_skills.register_callbacks._get_skills_prompt_section",
                return_value="SKILLS_SECTION",
            ),
            patch(
                "code_puppy.plugins.repo_compass.register_callbacks._build_repo_context",
                return_value="REPO_CONTEXT",
            ),
        ):
            results = callbacks.on_get_model_system_prompt(
                "gpt-4o-mini", "BASE_PROMPT", "USER_PROMPT"
            )

        assert len(results) == 2
        assert results[0]["instructions"].endswith("SKILLS_SECTION")
        assert "SKILLS_SECTION" in results[1]["instructions"]
        assert "REPO_CONTEXT" in results[1]["instructions"]

    def test_prompt_store_content_survives_claude_code_preparation(
        self, isolated_prompt_callbacks
    ):
        callbacks.register_callback("load_prompt", load_custom_prompt)
        callbacks.register_callback(
            "get_model_system_prompt", _inject_skills_into_prompt
        )
        callbacks.register_callback("get_model_system_prompt", _inject_repo_context)

        patches = _patch_prompt_sources()
        with (patches[0], patches[1], patches[2], patches[3]):
            assembled = _assemble_system_prompt("BASE_PROMPT")
            prepared = prepare_prompt_for_model(
                "claude-code-sonnet", assembled, "USER_PROMPT"
            )

        assert prepared.instructions == get_claude_code_instructions()
        assert "PROMPT_STORE_SECTION" in prepared.user_prompt
        assert "SKILLS_SECTION" in prepared.user_prompt
        assert "REPO_CONTEXT" in prepared.user_prompt
