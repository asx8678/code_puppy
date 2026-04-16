"""Tests for code_puppy.utils.fs_errors module."""

import errno
import os
import tempfile


from code_puppy.utils.fs_errors import (
    get_fs_code,
    has_fs_code,
    is_eacces,
    is_eisdir,
    is_eexist,
    is_enoent,
    is_enospc,
    is_enotempty,
    is_enotdir,
    is_eperm,
    is_erofs,
    is_fs_error,
)


class TestIsFsError:
    def test_oserror_with_errno(self):
        exc = OSError(errno.ENOENT, "No such file")
        assert is_fs_error(exc) is True

    def test_file_not_found(self):
        exc = FileNotFoundError("gone")
        assert is_fs_error(exc) is True

    def test_permission_error(self):
        exc = PermissionError("denied")
        assert is_fs_error(exc) is True

    def test_value_error_not_fs(self):
        assert is_fs_error(ValueError("nope")) is False

    def test_runtime_error_not_fs(self):
        assert is_fs_error(RuntimeError("nope")) is False

    def test_keyboard_interrupt_not_fs(self):
        assert is_fs_error(KeyboardInterrupt()) is False


class TestIsEnoent:
    def test_matches_file_not_found(self):
        try:
            open("/nonexistent/path/that/does/not/exist/file.txt")
        except FileNotFoundError as exc:
            assert is_enoent(exc) is True

    def test_matches_oserror_enoent(self):
        exc = OSError(errno.ENOENT, "No such file")
        assert is_enoent(exc) is True

    def test_rejects_permission_error(self):
        exc = PermissionError("denied")
        assert is_enoent(exc) is False

    def test_rejects_non_os_error(self):
        assert is_enoent(ValueError("nope")) is False


class TestIsEacces:
    def test_matches_permission_error(self):
        exc = OSError(errno.EACCES, "Permission denied")
        assert is_eacces(exc) is True

    def test_rejects_enoent(self):
        exc = OSError(errno.ENOENT, "No such file")
        assert is_eacces(exc) is False


class TestIsEisdir:
    def test_matches_is_a_directory(self):
        exc = OSError(errno.EISDIR, "Is a directory")
        assert is_eisdir(exc) is True

    def test_rejects_enoent(self):
        assert is_eisdir(FileNotFoundError("gone")) is False


class TestIsEnotdir:
    def test_matches_not_a_directory(self):
        exc = OSError(errno.ENOTDIR, "Not a directory")
        assert is_enotdir(exc) is True


class TestIsEexist:
    def test_matches_file_exists(self):
        exc = OSError(errno.EEXIST, "File exists")
        assert is_eexist(exc) is True

    def test_matches_file_exists_error(self):
        exc = FileExistsError("exists")
        assert is_eexist(exc) is True


class TestIsEnotempty:
    def test_matches(self):
        exc = OSError(errno.ENOTEMPTY, "Directory not empty")
        assert is_enotempty(exc) is True


class TestIsEperm:
    def test_matches(self):
        exc = OSError(errno.EPERM, "Operation not permitted")
        assert is_eperm(exc) is True


class TestIsEnospc:
    def test_matches(self):
        exc = OSError(errno.ENOSPC, "No space left")
        assert is_enospc(exc) is True


class TestIsErofs:
    def test_matches(self):
        exc = OSError(errno.EROFS, "Read-only filesystem")
        assert is_erofs(exc) is True


class TestHasFsCode:
    def test_matches_arbitrary_code(self):
        exc = OSError(errno.EMLINK, "Too many links")
        assert has_fs_code(exc, errno.EMLINK) is True

    def test_rejects_wrong_code(self):
        exc = OSError(errno.ENOENT, "No such file")
        assert has_fs_code(exc, errno.EACCES) is False

    def test_rejects_non_os_error(self):
        assert has_fs_code(ValueError("nope"), errno.ENOENT) is False


class TestGetFsCode:
    def test_returns_errno(self):
        exc = OSError(errno.ENOENT, "No such file")
        assert get_fs_code(exc) == errno.ENOENT

    def test_returns_none_for_non_os(self):
        assert get_fs_code(ValueError("nope")) is None

    def test_returns_none_for_base_exception(self):
        assert get_fs_code(KeyboardInterrupt()) is None


class TestRealFilesystemErrors:
    """Integration tests with actual filesystem operations."""

    def test_enoent_from_open(self):
        try:
            with open("/nonexistent/unlikely/path/xyz123.txt"):
                pass
        except OSError as exc:
            assert is_enoent(exc) is True
            assert get_fs_code(exc) == errno.ENOENT

    def test_eisdir_from_open_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                with open(tmpdir, "w") as f:
                    f.write("test")
            except OSError as exc:
                assert is_eisdir(exc) is True

    def test_eexist_from_mkdir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                os.makedirs(tmpdir, exist_ok=False)
            except OSError as exc:
                assert is_eexist(exc) is True

    def test_enotempty_from_rmdir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file inside so rmdir fails
            with open(os.path.join(tmpdir, "file.txt"), "w") as f:
                f.write("x")
            try:
                os.rmdir(tmpdir)
            except OSError as exc:
                assert is_enotempty(exc) is True
