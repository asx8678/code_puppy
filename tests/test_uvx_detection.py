"""Test coverage for uvx_detection.py.

Tests UVX environment detection including process parent detection (psutil and
Windows ctypes), chain traversal, launch-scenario detection, signal handling
adaptation, caching, and fallback mechanisms.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from code_puppy.uvx_detection import (
    _get_parent_process_chain,
    _get_parent_process_chain_psutil,
    _get_parent_process_chain_windows_ctypes,
    _get_parent_process_name_psutil,
    _is_uvx_in_chain,
    get_uvx_detection_info,
    is_launched_via_uvx,
    is_windows,
    should_use_alternate_cancel_key,
)


def _clear_uvx_cache():
    if hasattr(is_launched_via_uvx, "cache_clear"):
        is_launched_via_uvx.cache_clear()


def _mock_psutil(process_return=None, process_side_effect=None):
    """Build a mock psutil module whose Process() is configured."""
    mock_psutil = MagicMock()
    if process_side_effect is not None:
        mock_psutil.Process.side_effect = process_side_effect
    else:
        mock_psutil.Process.return_value = process_return
    return mock_psutil


class TestIsUVXInChain:
    @pytest.mark.parametrize(
        "chain,expected",
        [
            (["python.exe", "uvx.exe", "cmd.exe"], True),  # uvx.exe detected
            (["python", "uvx", "cmd"], True),  # uvx without extension
            (["python.exe", "uv.exe", "cmd.exe"], False),  # uv.exe is not uvx
            ([], False),  # empty chain
            (["python", "bash", "cmd"], False),  # no uvx present
        ],
    )
    def test_is_uvx_in_chain(self, chain, expected):
        assert _is_uvx_in_chain(chain) is expected

    def test_is_uvx_in_chain_with_none_values(self):
        """Robust to None entries (shouldn't happen, but must not raise)."""
        result = _is_uvx_in_chain(["python.exe", None, "cmd.exe"])
        assert isinstance(result, bool)


class TestIsWindows:
    @pytest.mark.parametrize(
        "system,expected",
        [("Windows", True), ("Linux", False), ("Darwin", False)],
    )
    @patch("platform.system")
    def test_is_windows(self, mock_platform, system, expected):
        mock_platform.return_value = system
        assert is_windows() is expected

    def test_is_windows_returns_bool(self):
        assert isinstance(is_windows(), bool)


class TestIsLaunchedViaUVX:
    @pytest.mark.parametrize(
        "chain,expected",
        [
            (["python.exe", "uvx.exe"], True),  # uvx.exe in chain
            (["python", "uvx"], True),  # uvx without extension
            (["python.exe", "cmd.exe"], False),  # no uvx
            ([], False),  # empty chain
            (["python.exe", "uv.exe", "cmd.exe"], False),  # uv.exe not confused
        ],
    )
    @patch("code_puppy.uvx_detection._get_parent_process_chain")
    def test_is_launched_via_uvx(self, mock_get_chain, chain, expected):
        mock_get_chain.return_value = chain
        _clear_uvx_cache()
        assert is_launched_via_uvx() is expected

    @patch("code_puppy.uvx_detection._get_parent_process_chain")
    def test_returns_bool(self, mock_get_chain):
        mock_get_chain.return_value = []
        _clear_uvx_cache()
        assert isinstance(is_launched_via_uvx(), bool)


class TestShouldUseAlternateCancelKey:
    @pytest.mark.parametrize(
        "windows,uvx,expected",
        [
            (True, True, True),  # only Windows + uvx triggers alternate key
            (True, False, False),
            (False, True, False),
            (False, False, False),
        ],
    )
    @patch("code_puppy.uvx_detection.is_windows")
    @patch("code_puppy.uvx_detection.is_launched_via_uvx")
    def test_should_use_alternate_key(
        self, mock_is_uvx, mock_is_windows, windows, uvx, expected
    ):
        mock_is_windows.return_value = windows
        mock_is_uvx.return_value = uvx
        assert should_use_alternate_cancel_key() is expected

    def test_returns_bool(self):
        assert isinstance(should_use_alternate_cancel_key(), bool)


class TestGetUVXDetectionInfo:
    REQUIRED_KEYS = {
        "is_windows",
        "is_launched_via_uvx",
        "should_use_alternate_cancel_key",
        "parent_process_chain",
        "current_pid",
        "python_executable",
    }

    @patch("code_puppy.uvx_detection._get_parent_process_chain")
    @patch("code_puppy.uvx_detection.is_launched_via_uvx")
    @patch("code_puppy.uvx_detection.is_windows")
    @patch("code_puppy.uvx_detection.should_use_alternate_cancel_key")
    def test_returns_dict_with_expected_values(
        self, mock_cancel_key, mock_is_windows, mock_is_uvx, mock_get_chain
    ):
        mock_get_chain.return_value = ["python"]
        mock_is_windows.return_value = False
        mock_is_uvx.return_value = False
        mock_cancel_key.return_value = False

        result = get_uvx_detection_info()
        assert isinstance(result, dict)
        assert self.REQUIRED_KEYS.issubset(result.keys())
        assert result["parent_process_chain"] == ["python"]
        assert result["is_windows"] is False
        assert result["is_launched_via_uvx"] is False
        assert result["should_use_alternate_cancel_key"] is False
        assert result["current_pid"] > 0

    def test_real_call_has_correct_types(self):
        result = get_uvx_detection_info()
        assert self.REQUIRED_KEYS.issubset(result.keys())
        assert isinstance(result["is_windows"], bool)
        assert isinstance(result["is_launched_via_uvx"], bool)
        assert isinstance(result["should_use_alternate_cancel_key"], bool)
        assert isinstance(result["parent_process_chain"], list)
        assert isinstance(result["current_pid"], int)
        assert isinstance(result["python_executable"], str)


class TestCacheBehavior:
    @patch("code_puppy.uvx_detection._get_parent_process_chain")
    def test_caches_result(self, mock_get_chain):
        mock_get_chain.return_value = ["python.exe", "uvx.exe"]
        _clear_uvx_cache()

        result1 = is_launched_via_uvx()
        result2 = is_launched_via_uvx()

        assert result1 is True
        assert result1 == result2
        # Cached: underlying chain lookup only happens once.
        assert mock_get_chain.call_count == 1

    @patch("code_puppy.uvx_detection._get_parent_process_chain")
    def test_lru_cache_info(self, mock_get_chain):
        mock_get_chain.return_value = ["python"]
        assert hasattr(is_launched_via_uvx, "cache_clear")
        assert hasattr(is_launched_via_uvx, "cache_info")

        _clear_uvx_cache()
        is_launched_via_uvx()
        is_launched_via_uvx()

        info = is_launched_via_uvx.cache_info()
        assert info.hits >= 1
        assert info.misses >= 1


class TestGetParentProcessNamePsutil:
    @pytest.mark.parametrize("raw_name", ["uvx.exe", "UVX.EXE"])
    def test_returns_lowercase_parent_name(self, raw_name):
        mock_parent = MagicMock()
        mock_parent.name.return_value = raw_name
        mock_proc = MagicMock()
        mock_proc.parent.return_value = mock_parent
        mock_psutil = _mock_psutil(process_return=mock_proc)

        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            result = _get_parent_process_name_psutil(1234)

        assert result == "uvx.exe"
        mock_psutil.Process.assert_called_once_with(1234)

    def test_returns_none_when_parent_is_none(self):
        mock_proc = MagicMock()
        mock_proc.parent.return_value = None
        mock_psutil = _mock_psutil(process_return=mock_proc)

        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            assert _get_parent_process_name_psutil(1234) is None

    def test_returns_none_on_exception(self):
        mock_psutil = _mock_psutil(process_side_effect=Exception("No such process"))
        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            assert _get_parent_process_name_psutil(1234) is None

    def test_returns_none_without_psutil(self):
        """Import failure inside the helper yields None."""
        original = sys.modules.get("psutil")

        class FakeModule:
            def __getattr__(self, name):
                raise ImportError("No module named 'psutil'")

        sys.modules["psutil"] = FakeModule()
        try:
            assert _get_parent_process_name_psutil(1234) is None
        finally:
            if original is not None:
                sys.modules["psutil"] = original

    def test_returns_str_or_none_for_real_process(self):
        result = _get_parent_process_name_psutil(os.getpid())
        assert result is None or isinstance(result, str)


class TestGetParentProcessChainPsutil:
    def test_builds_chain_from_hierarchy(self):
        """current -> uvx -> bash -> None builds a full chain."""
        mock_parent2 = MagicMock(pid=100)
        mock_parent2.name.return_value = "bash"
        mock_parent2.parent.return_value = None

        mock_parent1 = MagicMock(pid=200)
        mock_parent1.name.return_value = "uvx"
        mock_parent1.parent.return_value = mock_parent2

        mock_current = MagicMock(pid=300)
        mock_current.name.return_value = "python"
        mock_current.parent.return_value = mock_parent1

        mock_psutil = _mock_psutil(process_return=mock_current)
        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            with patch("code_puppy.uvx_detection.os.getpid", return_value=300):
                result = _get_parent_process_chain_psutil()

        assert result == ["python", "uvx", "bash"]

    @pytest.mark.parametrize("parent_pid", [0, 100])
    def test_chain_stops_at_terminal_parent(self, parent_pid):
        """Stops when parent pid is 0 or equals current pid (circular)."""
        mock_parent = MagicMock(pid=parent_pid)
        mock_parent.name.return_value = "term"
        mock_current = MagicMock(pid=100)
        mock_current.name.return_value = "python"
        mock_current.parent.return_value = mock_parent

        mock_psutil = _mock_psutil(process_return=mock_current)
        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            with patch("code_puppy.uvx_detection.os.getpid", return_value=100):
                result = _get_parent_process_chain_psutil()

        # Loop breaks before recursing into the terminal parent.
        assert result == ["python"]

    def test_handles_none_parent(self):
        mock_current = MagicMock(pid=100)
        mock_current.name.return_value = "python"
        mock_current.parent.return_value = None
        mock_psutil = _mock_psutil(process_return=mock_current)

        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            with patch("code_puppy.uvx_detection.os.getpid", return_value=100):
                result = _get_parent_process_chain_psutil()

        assert result == ["python"]

    def test_name_exception_returns_empty(self):
        mock_current = MagicMock(pid=100)
        mock_current.name.side_effect = Exception("Cannot get name")
        mock_current.parent.return_value = None
        mock_psutil = _mock_psutil(process_return=mock_current)

        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            with patch("code_puppy.uvx_detection.os.getpid", return_value=100):
                result = _get_parent_process_chain_psutil()

        assert result == []

    def test_parent_exception_returns_partial_chain(self):
        """name is appended before parent() raises, so partial chain survives."""
        mock_current = MagicMock(pid=100)
        mock_current.name.return_value = "python"
        mock_current.parent.side_effect = Exception("Access denied")
        mock_psutil = _mock_psutil(process_return=mock_current)

        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            with patch("code_puppy.uvx_detection.os.getpid", return_value=100):
                result = _get_parent_process_chain_psutil()

        assert result == ["python"]

    def test_process_exception_returns_empty(self):
        mock_psutil = _mock_psutil(process_side_effect=Exception("Process not found"))
        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            with patch("code_puppy.uvx_detection.os.getpid", return_value=100):
                result = _get_parent_process_chain_psutil()

        assert result == []

    def test_returns_empty_without_psutil(self):
        original = sys.modules.get("psutil")

        class FakeModule:
            def __getattr__(self, name):
                raise ImportError("No module named 'psutil'")

        sys.modules["psutil"] = FakeModule()
        try:
            assert _get_parent_process_chain_psutil() == []
        finally:
            if original is not None:
                sys.modules["psutil"] = original

    def test_real_chain_is_lowercase_strings_with_python(self):
        """Real call returns lowercase strings, including python (or empty)."""
        result = _get_parent_process_chain_psutil()
        assert isinstance(result, list)
        for name in result:
            assert isinstance(name, str)
            assert name == name.lower()
        assert result == [] or any("python" in name for name in result)


class TestGetParentProcessChainWindowsCtypes:
    @pytest.mark.parametrize("system", ["Linux", "Darwin"])
    @patch("platform.system")
    def test_non_windows_returns_empty(self, mock_platform, system):
        mock_platform.return_value = system
        assert _get_parent_process_chain_windows_ctypes() == []

    @patch("platform.system", return_value="Windows")
    def test_invalid_handle_returns_list(self, mock_platform):
        mock_kernel32 = MagicMock()
        mock_kernel32.CreateToolhelp32Snapshot.return_value = -1  # INVALID_HANDLE_VALUE

        mock_ctypes = MagicMock()
        mock_ctypes.windll.kernel32 = mock_kernel32
        mock_ctypes.sizeof.return_value = 300
        mock_ctypes.c_char = bytes
        mock_ctypes.Structure = object

        mock_wintypes = MagicMock()
        mock_wintypes.DWORD = int
        mock_wintypes.LONG = int
        mock_wintypes.ULONG = int

        with patch.dict(
            sys.modules, {"ctypes": mock_ctypes, "ctypes.wintypes": mock_wintypes}
        ):
            result = _get_parent_process_chain_windows_ctypes()

        assert isinstance(result, list)

    @patch("platform.system", return_value="Windows")
    def test_ctypes_exception_returns_empty(self, mock_platform):
        mock_ctypes = MagicMock()
        mock_ctypes.windll.kernel32.CreateToolhelp32Snapshot.side_effect = Exception(
            "Ctypes error"
        )
        with patch.dict(sys.modules, {"ctypes": mock_ctypes}):
            assert _get_parent_process_chain_windows_ctypes() == []

    @patch("platform.system", return_value="Windows")
    def test_windows_no_crash(self, mock_platform):
        """On Windows the real ctypes path must not raise."""
        result = _get_parent_process_chain_windows_ctypes()
        assert isinstance(result, list)


class TestGetParentProcessChain:
    def test_uses_psutil_when_available(self):
        with patch(
            "code_puppy.uvx_detection._get_parent_process_chain_psutil"
        ) as mock_psutil:
            mock_psutil.return_value = ["python", "uvx", "cmd"]
            result = _get_parent_process_chain()
        assert isinstance(result, list)

    @patch("code_puppy.uvx_detection._get_parent_process_chain_psutil")
    def test_empty_psutil_result(self, mock_psutil_chain):
        mock_psutil_chain.return_value = []
        assert isinstance(_get_parent_process_chain(), list)

    @patch("code_puppy.uvx_detection._get_parent_process_chain_psutil")
    def test_resilient_to_psutil_errors(self, mock_psutil_chain):
        mock_psutil_chain.side_effect = Exception("psutil error")
        assert isinstance(_get_parent_process_chain(), list)

    def test_real_call_no_crash(self):
        assert isinstance(_get_parent_process_chain(), list)

    @patch("platform.system", return_value="Windows")
    @patch("code_puppy.uvx_detection._get_parent_process_chain_windows_ctypes")
    def test_fallback_to_ctypes_on_windows(self, mock_ctypes_chain, mock_platform):
        """Without psutil on Windows, falls back to the ctypes implementation."""
        mock_ctypes_chain.return_value = ["python.exe", "uvx.exe", "cmd.exe"]
        original_modules = sys.modules.copy()

        class BlockingImport:
            def __getattr__(self, name):
                raise ImportError("No psutil")

        sys.modules.pop("psutil", None)
        sys.modules["psutil"] = BlockingImport()
        try:
            result = _get_parent_process_chain()
            assert result == ["python.exe", "uvx.exe", "cmd.exe"]
        finally:
            sys.modules.clear()
            sys.modules.update(original_modules)

    @patch("platform.system", return_value="Linux")
    def test_no_ctypes_fallback_on_linux(self, mock_platform):
        """Without psutil on Linux, returns empty (no ctypes fallback)."""
        original_modules = sys.modules.copy()

        class BlockingImport:
            def __getattr__(self, name):
                raise ImportError("No psutil")

        sys.modules.pop("psutil", None)
        sys.modules["psutil"] = BlockingImport()
        try:
            assert _get_parent_process_chain() == []
        finally:
            sys.modules.clear()
            sys.modules.update(original_modules)


class TestUVXIntegration:
    @pytest.mark.parametrize(
        "system,chain,exp_windows,exp_uvx,exp_alt",
        [
            ("Windows", ["python.exe", "uvx.exe", "cmd.exe"], True, True, True),
            ("Windows", ["python.exe", "uv.exe", "cmd.exe"], True, False, False),
            ("Linux", ["python", "bash"], False, False, False),
        ],
    )
    @patch("code_puppy.uvx_detection._get_parent_process_chain")
    @patch("platform.system")
    def test_full_detection(
        self,
        mock_platform,
        mock_get_chain,
        system,
        chain,
        exp_windows,
        exp_uvx,
        exp_alt,
    ):
        mock_platform.return_value = system
        mock_get_chain.return_value = chain
        _clear_uvx_cache()

        assert is_windows() is exp_windows
        assert is_launched_via_uvx() is exp_uvx
        assert should_use_alternate_cancel_key() is exp_alt
