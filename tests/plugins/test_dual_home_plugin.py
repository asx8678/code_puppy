"""Tests for the dual-home isolation plugin."""

from pathlib import Path

from code_puppy.plugins.dual_home.register_callbacks import (
    _on_file_permission,
    _on_load_prompt,
)


def test_dual_home_file_permission_blocks_legacy_writes_in_pup_ex(
    monkeypatch, tmp_path
):
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    ex_home = tmp_path / "pup_ex_home"
    ex_home.mkdir()
    monkeypatch.setenv("PUP_EX_HOME", str(ex_home))
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    legacy_file = fake_home / ".code_puppy" / "prefs.json"
    active_file = ex_home / "prefs.json"

    assert _on_file_permission({}, str(legacy_file), "write") is False
    assert _on_file_permission({}, str(legacy_file), "replace text in") is False
    assert _on_file_permission({}, str(legacy_file), "delete snippet from") is False
    assert _on_file_permission({}, str(active_file), "write") is True
    assert _on_file_permission({}, str(legacy_file), "read") is True


def test_dual_home_load_prompt_includes_active_and_legacy_homes(monkeypatch, tmp_path):
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    ex_home = tmp_path / "pup_ex_home"
    ex_home.mkdir()
    monkeypatch.setenv("PUP_EX_HOME", str(ex_home))
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    prompt = _on_load_prompt()

    assert prompt is not None
    assert str(ex_home) in prompt
    assert str(fake_home / ".code_puppy") in prompt
    assert "READ-ONLY" in prompt
