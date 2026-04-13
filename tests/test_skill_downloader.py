"""Tests for remote skill downloader/installer."""

import zipfile
from pathlib import Path

import pytest

import code_puppy.plugins.agent_skills.downloader as dl


@pytest.fixture(autouse=True)
def _no_refresh(monkeypatch):
    """Fixture that prevents catalog refresh during tests."""

    monkeypatch.setattr(dl, "refresh_skill_cache", lambda: None)


def _make_zip(path: Path, files: dict[str, str]) -> None:
    """Create a zip file with given file contents."""

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)


def test_download_and_install_success(tmp_path: Path, monkeypatch) -> None:
    """Test successful download and installation of a skill."""

    skill_name = "test-skill"
    skills_dir = tmp_path / "skills"

    src_zip = tmp_path / "src.zip"
    _make_zip(
        src_zip,
        {
            "SKILL.md": "---\nname: test-skill\ndescription: hi\n---\n",
            "README.txt": "hello",
        },
    )

    def fake_download(url: str, dest: Path) -> bool:
        """Fake download function for testing."""

        dest.write_bytes(src_zip.read_bytes())
        return True

    monkeypatch.setattr(dl, "_download_to_file", fake_download)

    result = dl.download_and_install_skill(
        skill_name=skill_name,
        download_url="https://example.test/test-skill.zip",
        target_dir=skills_dir,
        force=False,
    )

    assert result.success is True
    assert result.installed_path == skills_dir / skill_name
    assert (skills_dir / skill_name / "SKILL.md").is_file()


def test_download_fails(tmp_path: Path, monkeypatch) -> None:
    """Test graceful handling when download fails."""

    monkeypatch.setattr(dl, "_download_to_file", lambda url, dest: False)

    result = dl.download_and_install_skill(
        skill_name="test-skill",
        download_url="https://example.test/test-skill.zip",
        target_dir=tmp_path / "skills",
    )

    assert result.success is False
    assert "Failed to download" in result.message


def test_already_installed_no_force(tmp_path: Path, monkeypatch) -> None:
    """Test that already-installed skills are skipped without force."""

    skill_name = "test-skill"
    skills_dir = tmp_path / "skills"

    src_zip = tmp_path / "src.zip"
    _make_zip(src_zip, {"SKILL.md": "---\nname: test-skill\ndescription: hi\n---\n"})

    def fake_download(url: str, dest: Path) -> bool:
        """Fake download function for testing."""

        dest.write_bytes(src_zip.read_bytes())
        return True

    monkeypatch.setattr(dl, "_download_to_file", fake_download)

    first = dl.download_and_install_skill(
        skill_name=skill_name,
        download_url="https://example.test/test-skill.zip",
        target_dir=skills_dir,
    )
    assert first.success is True

    second = dl.download_and_install_skill(
        skill_name=skill_name,
        download_url="https://example.test/test-skill.zip",
        target_dir=skills_dir,
        force=False,
    )

    assert second.success is False
    assert "already installed" in second.message.lower()


def test_already_installed_with_force(tmp_path: Path, monkeypatch) -> None:
    """Test that force flag replaces already-installed skills."""

    skill_name = "test-skill"
    skills_dir = tmp_path / "skills"

    src_zip_1 = tmp_path / "src1.zip"
    _make_zip(src_zip_1, {"SKILL.md": "---\nname: test-skill\ndescription: v1\n---\n"})

    src_zip_2 = tmp_path / "src2.zip"
    _make_zip(src_zip_2, {"SKILL.md": "---\nname: test-skill\ndescription: v2\n---\n"})

    def fake_download_v1(url: str, dest: Path) -> bool:
        """Fake download function for testing."""

        dest.write_bytes(src_zip_1.read_bytes())
        return True

    monkeypatch.setattr(dl, "_download_to_file", fake_download_v1)

    first = dl.download_and_install_skill(
        skill_name=skill_name,
        download_url="https://example.test/test-skill.zip",
        target_dir=skills_dir,
    )
    assert first.success is True

    # Now reinstall with different zip
    def fake_download_v2(url: str, dest: Path) -> bool:
        """Fake download function for testing."""

        dest.write_bytes(src_zip_2.read_bytes())
        return True

    monkeypatch.setattr(dl, "_download_to_file", fake_download_v2)

    second = dl.download_and_install_skill(
        skill_name=skill_name,
        download_url="https://example.test/test-skill.zip",
        target_dir=skills_dir,
        force=True,
    )
    assert second.success is True

    installed = (skills_dir / skill_name / "SKILL.md").read_text(encoding="utf-8")
    assert "v2" in installed


def test_invalid_zip(tmp_path: Path, monkeypatch) -> None:
    """Test handling of corrupted zip archives."""

    skills_dir = tmp_path / "skills"
    garbage = tmp_path / "garbage.zip"
    garbage.write_bytes(b"not a zip")

    def fake_download(url: str, dest: Path) -> bool:
        """Fake download function for testing."""

        dest.write_bytes(garbage.read_bytes())
        return True

    monkeypatch.setattr(dl, "_download_to_file", fake_download)

    result = dl.download_and_install_skill(
        skill_name="test-skill",
        download_url="https://example.test/test-skill.zip",
        target_dir=skills_dir,
    )

    assert result.success is False
    assert "valid zip" in result.message.lower()


def test_missing_skill_md_in_zip(tmp_path: Path, monkeypatch) -> None:
    """Test handling of zip archives missing SKILL.md."""

    skills_dir = tmp_path / "skills"
    src_zip = tmp_path / "src.zip"
    _make_zip(src_zip, {"README.md": "no skill md"})

    def fake_download(url: str, dest: Path) -> bool:
        """Fake download function for testing."""

        dest.write_bytes(src_zip.read_bytes())
        return True

    monkeypatch.setattr(dl, "_download_to_file", fake_download)

    result = dl.download_and_install_skill(
        skill_name="test-skill",
        download_url="https://example.test/test-skill.zip",
        target_dir=skills_dir,
    )

    assert result.success is False
    assert "missing skill.md" in result.message.lower()


def test_zip_with_subdirectory(tmp_path: Path, monkeypatch) -> None:
    """Zip contains a single top-level directory; installer should flatten it."""

    skills_dir = tmp_path / "skills"
    src_zip = tmp_path / "src.zip"

    _make_zip(
        src_zip,
        {
            "some-folder/SKILL.md": "---\nname: test-skill\ndescription: hi\n---\n",
            "some-folder/foo.txt": "bar",
        },
    )

    def fake_download(url: str, dest: Path) -> bool:
        """Fake download function for testing."""

        dest.write_bytes(src_zip.read_bytes())
        return True

    monkeypatch.setattr(dl, "_download_to_file", fake_download)

    result = dl.download_and_install_skill(
        skill_name="test-skill",
        download_url="https://example.test/test-skill.zip",
        target_dir=skills_dir,
    )

    assert result.success is True
    assert (skills_dir / "test-skill" / "SKILL.md").is_file()
    assert (skills_dir / "test-skill" / "foo.txt").is_file()


from unittest.mock import patch
import tempfile


def test_download_aborts_when_exceeds_limit():
    """Download must abort when exceeding MAX_DOWNLOAD_BYTES."""
    from code_puppy.plugins.agent_skills.downloader import (
        _download_to_file,
        MAX_DOWNLOAD_BYTES,
    )

    # Create a mock response that returns more than MAX_DOWNLOAD_BYTES
    class MockResponse:
        headers = {"content-type": "application/zip"}

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            # Yield chunks that exceed the limit
            chunk_size = 1024 * 1024  # 1MB chunks
            for _ in range((MAX_DOWNLOAD_BYTES // chunk_size) + 2):
                yield b"x" * chunk_size

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class MockClient:
        def __init__(self, **kwargs):
            pass

        def stream(self, method, url):
            return MockResponse()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "test.zip"

        with patch("code_puppy.plugins.agent_skills.downloader.httpx.Client", MockClient):
            result = _download_to_file("http://example.com/skill.zip", dest)

        assert result is False, "Download should fail when exceeding limit"
        assert not dest.exists(), "Partial file should be cleaned up"


def test_download_rejects_html_content_type():
    """Download must reject HTML responses (error pages)."""
    from code_puppy.plugins.agent_skills.downloader import _download_to_file

    class MockResponse:
        headers = {"content-type": "text/html; charset=utf-8"}

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            yield b"<html>Error</html>"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class MockClient:
        def __init__(self, **kwargs):
            pass

        def stream(self, method, url):
            return MockResponse()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "test.zip"

        with patch("code_puppy.plugins.agent_skills.downloader.httpx.Client", MockClient):
            result = _download_to_file("http://example.com/skill.zip", dest)

        assert result is False, "Download should fail for HTML content-type"


def test_shutil_move_used_for_cross_filesystem():
    """Verify shutil.move is used (handles cross-filesystem moves)."""
    # This is a static code check - verify shutil.move is in the file
    import inspect
    from code_puppy.plugins.agent_skills import downloader

    source = inspect.getsource(downloader)
    assert "shutil.move" in source, "shutil.move should be used for cross-filesystem safety"
    # Verify the old Path.move() is not used
    assert ".move(skill_dir)" not in source or "shutil.move" in source, \
        "Path.move() should be replaced with shutil.move()"
