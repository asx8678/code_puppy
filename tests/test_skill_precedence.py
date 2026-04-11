"""Tests for layered skill discovery with precedence."""

import logging
from pathlib import Path


from code_puppy.plugins.agent_skills.discovery import (
    discover_skills,
    _scan_directory,
)


def _make_skill(base: Path, name: str, with_skill_md: bool = True) -> Path:
    """Create a skill directory, optionally with SKILL.md."""
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    if with_skill_md:
        (skill_dir / "SKILL.md").write_text(f"# {name}\nA test skill.")
    return skill_dir


def test_higher_precedence_overrides_lower(tmp_path):
    """Project-level skills should override user-level skills with same name."""
    user_dir = tmp_path / "user_skills"
    project_dir = tmp_path / "project_skills"
    _make_skill(user_dir, "reviewer")
    _make_skill(project_dir, "reviewer")

    skills = discover_skills([user_dir, project_dir])

    assert len(skills) == 1
    assert skills[0].name == "reviewer"
    assert skills[0].path == project_dir / "reviewer"


def test_no_conflict_different_names(tmp_path):
    """Different skills from different directories should all appear."""
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    _make_skill(dir_a, "linter")
    _make_skill(dir_b, "formatter")

    skills = discover_skills([dir_a, dir_b])
    names = {s.name for s in skills}
    assert names == {"linter", "formatter"}


def test_conflict_logs_warning(tmp_path, caplog):
    """Same-named skills from different dirs should log a warning."""
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    _make_skill(dir_a, "reviewer")
    _make_skill(dir_b, "reviewer")

    with caplog.at_level(logging.WARNING):
        skills = discover_skills([dir_a, dir_b])

    assert len(skills) == 1
    assert any("overrides" in msg for msg in caplog.messages)


def test_source_level_assigned_correctly(tmp_path):
    """_scan_directory should assign the given source_level."""
    skill_dir = tmp_path / "skills"
    _make_skill(skill_dir, "my_skill")

    results = _scan_directory(skill_dir, "user")
    assert len(results) == 1
    assert results[0].source_level == "user"


def test_backward_compat_explicit_directories(tmp_path):
    """When directories= is passed explicitly, behavior should be preserved."""
    dir1 = tmp_path / "d1"
    _make_skill(dir1, "tool_a")
    _make_skill(dir1, "tool_b")

    skills = discover_skills([dir1])
    names = {s.name for s in skills}
    assert "tool_a" in names
    assert "tool_b" in names


def test_empty_directory(tmp_path):
    """An empty directory should yield no skills."""
    empty = tmp_path / "empty"
    empty.mkdir()
    skills = discover_skills([empty])
    assert skills == []


def test_hidden_dirs_skipped(tmp_path):
    """Directories starting with . should be skipped."""
    base = tmp_path / "skills"
    _make_skill(base, ".hidden_skill")
    _make_skill(base, "visible_skill")
    skills = discover_skills([base])
    assert len(skills) == 1
    assert skills[0].name == "visible_skill"
