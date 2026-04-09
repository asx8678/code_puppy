import tempfile
from pathlib import Path

import pytest

from code_puppy.utils.gitignore import (
    GitignoreMatcher,
    clear_cache,
    is_gitignored,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_cache()
    yield
    clear_cache()


def _make_repo_with_gitignore(tmpdir: Path, ignore_content: str) -> Path:
    """Create a fake repo with a .gitignore and some files."""
    (tmpdir / ".gitignore").write_text(ignore_content)
    (tmpdir / "main.py").write_text("print('hi')")
    build_dir = tmpdir / "build"
    build_dir.mkdir()
    (build_dir / "artifact.o").write_text("binary")
    (build_dir / "nested").mkdir()
    (build_dir / "nested" / "other.o").write_text("binary")
    (tmpdir / "src").mkdir()
    (tmpdir / "src" / "code.py").write_text("x = 1")
    return tmpdir


def test_no_gitignore_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        matcher = GitignoreMatcher.for_directory(tmp)
        assert matcher is None


def test_simple_build_pattern():
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        _make_repo_with_gitignore(tmpdir, "build/\n")
        matcher = GitignoreMatcher.for_directory(tmpdir)
    assert matcher is not None
    assert matcher.is_ignored("build/artifact.o") is True
    assert matcher.is_ignored("build/nested/other.o") is True
    assert matcher.is_ignored("src/code.py") is False
    assert matcher.is_ignored("main.py") is False


def test_glob_pattern():
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        _make_repo_with_gitignore(tmpdir, "*.o\n")
        matcher = GitignoreMatcher.for_directory(tmpdir)
    assert matcher is not None
    assert matcher.is_ignored("build/artifact.o") is True
    assert matcher.is_ignored("main.py") is False


def test_absolute_path():
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        _make_repo_with_gitignore(tmpdir, "build/\n")
        matcher = GitignoreMatcher.for_directory(tmpdir)
        assert matcher is not None
        abs_path = tmpdir / "build" / "artifact.o"
        assert matcher.is_ignored(abs_path) is True


def test_absolute_path_outside_root():
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        _make_repo_with_gitignore(tmpdir, "build/\n")
        matcher = GitignoreMatcher.for_directory(tmpdir)
        assert matcher is not None
        # A path outside the root should not be ignored
        assert matcher.is_ignored("/some/other/path/build/artifact.o") is False


def test_is_gitignored_helper():
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        _make_repo_with_gitignore(tmpdir, "build/\n*.log\n")
        assert is_gitignored("build/x.o", base_dir=tmpdir) is True
        assert is_gitignored("error.log", base_dir=tmpdir) is True
        assert is_gitignored("main.py", base_dir=tmpdir) is False


def test_cache_hits():
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        _make_repo_with_gitignore(tmpdir, "build/\n")
        # Two calls should use the cache
        a = is_gitignored("build/x.o", base_dir=tmpdir)
        b = is_gitignored("build/y.o", base_dir=tmpdir)
        assert a is True
        assert b is True


def test_clear_cache_works():
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        _make_repo_with_gitignore(tmpdir, "build/\n")
        assert is_gitignored("build/x.o", base_dir=tmpdir) is True
    # After tmp dir is gone, clearing cache should let a new lookup try fresh
    clear_cache()
    # And a fresh lookup on a non-existent dir should return False gracefully
    assert is_gitignored("anywhere", base_dir="/nonexistent/path/xyzzy") is False


def test_empty_gitignore():
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        (tmpdir / ".gitignore").write_text("")
        matcher = GitignoreMatcher.for_directory(tmpdir)
        # Empty gitignore -> no lines -> returns None
        assert matcher is None


def test_comments_ignored():
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        (tmpdir / ".gitignore").write_text("# this is a comment\n*.log\n")
        matcher = GitignoreMatcher.for_directory(tmpdir)
    assert matcher is not None
    assert matcher.is_ignored("x.log") is True
    assert matcher.is_ignored("this is a comment") is False
