from pathlib import Path

import pytest

from code_puppy import callbacks as callbacks_module
from code_puppy.model_utils import prepare_prompt_for_model
from code_puppy.plugins.repo_compass.formatter import format_structure_map
from code_puppy.plugins.repo_compass.indexer import build_structure_map
from code_puppy.plugins.repo_compass.register_callbacks import (
    _build_repo_context,
    _inject_repo_context,
)


@pytest.fixture(autouse=True)
def _isolate_callback_registry():
    snapshot = {
        phase: list(callbacks_module.get_callbacks(phase))
        for phase in callbacks_module._callbacks
    }
    try:
        yield
    finally:
        callbacks_module.clear_callbacks()
        for phase, funcs in snapshot.items():
            for func in funcs:
                callbacks_module.register_callback(phase, func)


def test_build_structure_map_extracts_python_symbols(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(
        "class Greeter:\n"
        "    def hello(self, name):\n"
        "        return name\n\n"
        "def wave(person, times):\n"
        "    return person\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")

    summaries = build_structure_map(tmp_path, max_files=10, max_symbols_per_file=5)
    by_path = {item.path: item for item in summaries}

    assert "pkg/mod.py" in by_path
    assert by_path["pkg/mod.py"].kind == "python"
    assert any(
        symbol.startswith("class Greeter") for symbol in by_path["pkg/mod.py"].symbols
    )
    assert "def wave(person, times)" in by_path["pkg/mod.py"].symbols
    assert "README.md" in by_path


def test_format_structure_map_truncates_long_output(tmp_path: Path):
    summaries = [
        type(
            "Summary",
            (),
            {"path": f"file_{i}.py", "kind": "python", "symbols": (f"def fn_{i}()",)},
        )
        for i in range(20)
    ]
    result = format_structure_map(tmp_path, summaries, max_chars=180)

    assert result is not None
    assert "Repo Compass" in result
    assert "truncated" in result


def test_build_repo_context_can_be_disabled(monkeypatch):
    monkeypatch.setattr(
        "code_puppy.plugins.repo_compass.register_callbacks.load_config",
        lambda: type(
            "Cfg",
            (),
            {
                "enabled": False,
                "max_files": 10,
                "max_symbols_per_file": 5,
                "max_prompt_chars": 500,
            },
        )(),
    )
    assert _build_repo_context() is None


def test_inject_repo_context_appends_to_system_prompt(monkeypatch):
    monkeypatch.setattr(
        "code_puppy.plugins.repo_compass.register_callbacks._build_repo_context",
        lambda root=None: "## Repo Compass\n- sample.py [python]: def run()",
    )

    result = _inject_repo_context("gpt-5", "BASE PROMPT", "hello")

    assert result is not None
    assert result["handled"] is False
    assert result["user_prompt"] == "hello"
    assert "BASE PROMPT" in result["instructions"]
    assert "Repo Compass" in result["instructions"]


def test_prepare_prompt_for_model_uses_repo_compass_callback(monkeypatch):
    monkeypatch.setattr(
        "code_puppy.callbacks.on_get_model_system_prompt",
        lambda model_name, default_system_prompt, user_prompt: [
            {
                "instructions": "BASE\n\n## Repo Compass\n- sample.py [python]: def run()",
                "user_prompt": user_prompt,
                "handled": True,
            }
        ],
    )

    result = prepare_prompt_for_model("gpt-5", "BASE", "hello")

    assert "Repo Compass" in result.instructions
    assert result.user_prompt == "hello"
    assert result.is_claude_code is False


def test_prepare_prompt_for_model_applies_repo_compass_augmentation(monkeypatch):
    monkeypatch.setattr(
        "code_puppy.callbacks.on_get_model_system_prompt",
        lambda model_name, default_system_prompt, user_prompt: [
            {
                "instructions": "BASE\n\n## Repo Compass\n- sample.py [python]: def run()",
                "user_prompt": user_prompt,
                "handled": False,
            }
        ],
    )

    result = prepare_prompt_for_model("gpt-5", "BASE", "hello")

    assert "Repo Compass" in result.instructions
    assert result.user_prompt == "hello"
    assert result.is_claude_code is False


def test_prepare_prompt_for_claude_code_preserves_repo_compass_augmentation(
    monkeypatch,
):
    monkeypatch.setattr(
        "code_puppy.callbacks.on_get_model_system_prompt",
        lambda model_name, default_system_prompt, user_prompt: [
            {
                "instructions": "BASE\n\n## Repo Compass\n- sample.py [python]: def run()",
                "user_prompt": user_prompt,
                "handled": False,
            }
        ],
    )

    result = prepare_prompt_for_model("claude-code-sonnet", "BASE", "hello")

    assert result.is_claude_code is True
    assert (
        result.instructions
        == "You are Claude Code, Anthropic's official CLI for Claude."
    )
    assert "Repo Compass" in result.user_prompt
    assert result.user_prompt.endswith("hello")


def test_build_repo_context_includes_tech_stack_build_commands_and_decisions(
    tmp_path: Path, monkeypatch
):
    """Test that _build_repo_context includes tech stack, build commands, and key decisions sections."""
    # Enable repo compass for this test
    monkeypatch.setattr(
        "code_puppy.plugins.repo_compass.register_callbacks.load_config",
        lambda: type(
            "Cfg",
            (),
            {
                "enabled": True,
                "max_files": 10,
                "max_symbols_per_file": 5,
                "max_prompt_chars": 500,
            },
        )(),
    )

    # Create a temp repo structure that triggers all sections
    # Python project with pyproject.toml for tech stack detection
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\nrequires-python = ">=3.11"\ndependencies = ["fastapi"]\n',
        encoding="utf-8",
    )

    # Makefile for build commands
    (tmp_path / "Makefile").write_text(
        "test:\n\tpytest\n\nlint:\n\truff check .\n",
        encoding="utf-8",
    )

    # Python file with decision markers
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        "# WHY: Using FastAPI for performance\ndef main(): pass\n",
        encoding="utf-8",
    )

    result = _build_repo_context(tmp_path)

    assert result is not None
    assert "Tech stack:" in result
    assert "Build commands:" in result
    assert "Key decisions:" in result


def test_build_repo_context_graceful_failure_when_detect_tech_stack_raises(
    tmp_path: Path, monkeypatch
):
    """Test that _build_repo_context still returns useful context when detect_tech_stack raises."""
    # Enable repo compass for this test
    monkeypatch.setattr(
        "code_puppy.plugins.repo_compass.register_callbacks.load_config",
        lambda: type(
            "Cfg",
            (),
            {
                "enabled": True,
                "max_files": 10,
                "max_symbols_per_file": 5,
                "max_prompt_chars": 500,
            },
        )(),
    )

    # Create a basic repo structure
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        "def main(): pass\n",
        encoding="utf-8",
    )

    # Mock detect_tech_stack to raise an exception
    def raise_exception(*args, **kwargs):
        raise RuntimeError("Tech stack detection failed!")

    monkeypatch.setattr(
        "code_puppy.plugins.repo_compass.register_callbacks.detect_tech_stack",
        raise_exception,
    )

    # Should still return context (structure map) even if tech stack fails
    result = _build_repo_context(tmp_path)

    assert result is not None
    assert "Repo Compass" in result  # The structure map should still be present
