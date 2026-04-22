"""Isolation tests for remote skill installation."""

from pathlib import Path
from unittest.mock import patch

from code_puppy.plugins.agent_skills.downloader import download_and_install_skill


def test_download_and_install_skill_blocks_legacy_target_dir_in_pup_ex(
    monkeypatch, tmp_path
):
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    ex_home = tmp_path / "pup_ex_home"
    ex_home.mkdir()
    monkeypatch.setenv("PUP_EX_HOME", str(ex_home))
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    legacy_skills_dir = fake_home / ".code_puppy" / "skills"

    with patch(
        "code_puppy.plugins.agent_skills.downloader._download_to_file"
    ) as download:
        result = download_and_install_skill(
            "myskill", "https://example.invalid/myskill.zip", target_dir=legacy_skills_dir
        )

    assert result.success is False
    assert result.message == "Unexpected error installing skill"
    assert not legacy_skills_dir.exists()
    download.assert_not_called()
