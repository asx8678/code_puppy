"""Full coverage tests for tools/universal_constructor.py."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from code_puppy.tools.universal_constructor import (
    UniversalConstructorOutput,
    _build_summary,
    _emit_uc_message,
    _generate_preview,
    _run_ruff_format,
    _stub_not_implemented,
    universal_constructor_impl,
)


@contextmanager
def patched(registry=None):
    """Patch get_message_bus and (optionally) get_registry for the duration.

    Yields the registry mock (or None). When ``registry`` is None only the
    message bus is patched, mirroring the handlers that fail before ever
    touching the registry.
    """
    bus = patch("code_puppy.tools.universal_constructor.get_message_bus")
    if registry is None:
        with bus:
            yield None
    else:
        reg = patch(
            "code_puppy.plugins.universal_constructor.registry.get_registry",
            **(
                {"side_effect": registry}
                if isinstance(registry, Exception)
                else {"return_value": registry}
            ),
        )
        with bus, reg:
            yield registry


def make_tool(*, enabled=True, source_path=None, func=...):
    """Build a registry mock returning one configured tool."""
    registry = MagicMock()
    tool = MagicMock()
    tool.meta.enabled = enabled
    tool.source_path = source_path
    registry.get_tool.return_value = tool
    if func is not ...:
        registry.get_tool_function.return_value = func
    return registry


async def run_impl(registry, *args, **kwargs):
    with patched(registry):
        return await universal_constructor_impl(MagicMock(), *args, **kwargs)


class TestGeneratePreview:
    def test_short_code(self):
        assert _generate_preview("a\nb") == "a\nb"

    def test_long_code(self):
        code = "\n".join(f"line{i}" for i in range(20))
        preview = _generate_preview(code, max_lines=5)
        assert "truncated" in preview
        assert preview.count("\n") == 5


class TestRunRuffFormat:
    def test_success(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("x=1")
        result = _run_ruff_format(f)
        assert result is None or isinstance(result, str)

    @pytest.mark.parametrize(
        "side_effect, expected",
        [
            (FileNotFoundError, "not found"),
            (Exception("boom"), "error"),
        ],
    )
    def test_side_effect_errors(self, side_effect, expected):
        with patch("subprocess.run", side_effect=side_effect):
            assert expected in _run_ruff_format("/fake")

    def test_timeout(self):
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ruff", 10)):
            assert "timed out" in _run_ruff_format("/fake")

    def test_nonzero_exit(self):
        mock_result = MagicMock(returncode=1, stderr="error")
        with patch("subprocess.run", return_value=mock_result):
            assert "failed" in _run_ruff_format("/fake")


class TestStubNotImplemented:
    def test_returns_error(self):
        result = _stub_not_implemented("test")
        assert result.success is False
        assert "Not implemented" in result.error


class TestEmitUcMessage:
    def test_emits(self):
        with patch("code_puppy.tools.universal_constructor.get_message_bus") as mb:
            _emit_uc_message("list", True, "summary", "tool", "details")
            mb().emit.assert_called_once()


class TestBuildSummary:
    def test_error(self):
        r = UniversalConstructorOutput(action="x", success=False, error="fail")
        assert _build_summary(r) == "fail"

    def test_error_none(self):
        r = UniversalConstructorOutput(action="x", success=False)
        assert _build_summary(r) == "Operation failed"

    def test_no_specific_result(self):
        r = UniversalConstructorOutput(action="x", success=True)
        assert _build_summary(r) == "Operation completed"

    def test_list_result(self):
        from code_puppy.plugins.universal_constructor.models import UCListOutput

        r = UniversalConstructorOutput(
            action="list",
            success=True,
            list_result=UCListOutput(tools=[], total_count=5, enabled_count=3),
        )
        assert "3" in _build_summary(r)

    def test_call_result(self):
        from code_puppy.plugins.universal_constructor.models import UCCallOutput

        r = UniversalConstructorOutput(
            action="call",
            success=True,
            call_result=UCCallOutput(
                success=True, tool_name="t", result="ok", execution_time=1.5
            ),
        )
        assert "1.50" in _build_summary(r)

    @pytest.mark.parametrize(
        "action, expected", [("create", "Created"), ("update", "Updated")]
    )
    def test_create_update_result(self, action, expected):
        from code_puppy.plugins.universal_constructor.models import (
            UCCreateOutput,
            UCUpdateOutput,
        )

        model = {"create": UCCreateOutput, "update": UCUpdateOutput}[action]
        out = model(success=True, tool_name="t", source_path="/p")
        r = UniversalConstructorOutput(
            action=action, success=True, **{f"{action}_result": out}
        )
        assert expected in _build_summary(r)

    def test_info_result(self):
        from code_puppy.plugins.universal_constructor.models import (
            ToolMeta,
            UCInfoOutput,
            UCToolInfo,
        )

        meta = ToolMeta(name="test", namespace="ns", description="d", enabled=True)
        tool_info = UCToolInfo(
            meta=meta, signature="def f()", source_path="/p", function_name="f"
        )
        r = UniversalConstructorOutput(
            action="info",
            success=True,
            info_result=UCInfoOutput(success=True, tool=tool_info, source_code="x"),
        )
        assert "ns.test" in _build_summary(r)


class TestHandleListAction:
    @pytest.mark.anyio
    async def test_list_empty(self):
        registry = MagicMock()
        registry.list_tools.return_value = []
        result = await run_impl(registry, "list")
        assert result.success is True

    @pytest.mark.anyio
    async def test_list_error(self):
        result = await run_impl(Exception("boom"), "list")
        assert result.success is False


class TestHandleCallAction:
    @pytest.mark.anyio
    async def test_no_tool_name(self):
        result = await run_impl(None, "call")
        assert result.success is False
        assert "required" in result.error

    @pytest.mark.anyio
    async def test_tool_not_found(self):
        registry = MagicMock()
        registry.get_tool.return_value = None
        result = await run_impl(registry, "call", tool_name="x")
        assert "not found" in result.error

    @pytest.mark.anyio
    async def test_tool_disabled(self):
        registry = make_tool(enabled=False)
        result = await run_impl(registry, "call", tool_name="x")
        assert "disabled" in result.error

    @pytest.mark.anyio
    async def test_call_no_function(self):
        registry = make_tool(func=None)
        result = await run_impl(registry, "call", tool_name="x")
        assert "Could not load" in result.error

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "tool_args, expected",
        [
            ("{bad", "Invalid"),
            ([1, 2], "must be a dict"),
        ],
    )
    async def test_call_bad_args(self, tool_args, expected):
        registry = make_tool(func=lambda: None)
        result = await run_impl(registry, "call", tool_name="x", tool_args=tool_args)
        assert expected in result.error

    @pytest.mark.anyio
    async def test_call_success(self):
        registry = make_tool(func=lambda: "result")
        result = await run_impl(registry, "call", tool_name="x")
        assert result.success is True

    @pytest.mark.anyio
    async def test_call_json_string_args_parsed_and_forwarded(self):
        """tool_args may arrive as a JSON-encoded string from transports that
        stringify nested objects (e.g. some tool-calling layers). The string
        should be parsed transparently and forwarded as kwargs to the tool."""
        captured = {}

        def echo(**kwargs):
            captured.update(kwargs)
            return {"got": kwargs}

        registry = make_tool(func=echo)
        result = await run_impl(
            registry,
            "call",
            tool_name="x",
            tool_args='{"subject": "a knight", "pixel_grid": 64}',
        )
        assert result.success is True
        assert captured == {"subject": "a knight", "pixel_grid": 64}

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "exc, expected",
        [
            (TypeError("wrong args"), "Invalid arguments"),
            (RuntimeError("boom"), "execution failed"),
        ],
    )
    async def test_call_func_raises(self, exc, expected):
        def bad_func(**kw):
            raise exc

        registry = make_tool(func=bad_func)
        result = await run_impl(registry, "call", tool_name="x")
        assert expected in result.error


class TestHandleCreateAction:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "python_code, expected",
        [
            ("", "required"),
            ("def f(", "Syntax"),
            ("x = 1", "No functions"),
        ],
    )
    async def test_create_errors(self, python_code, expected):
        result = await run_impl(None, "create", python_code=python_code)
        assert expected in result.error

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "tool_name, python_code, description",
        [
            ("hello", 'def hello():\n    return "hi"', "test"),
            ("ns.hello", 'def hello():\n    return "hi"', None),
            (
                None,
                'TOOL_META = {"name": "mytool", "description": "test", "enabled": True}\n'
                "def f():\n    pass",
                None,
            ),
        ],
    )
    async def test_create_success(self, tmp_path, tool_name, python_code, description):
        kwargs = {"python_code": python_code}
        if tool_name is not None:
            kwargs["tool_name"] = tool_name
        if description is not None:
            kwargs["description"] = description
        with (
            patch("code_puppy.tools.universal_constructor.get_message_bus"),
            patch("code_puppy.plugins.universal_constructor.USER_UC_DIR", tmp_path),
            patch("code_puppy.plugins.universal_constructor.registry.get_registry"),
        ):
            result = await universal_constructor_impl(MagicMock(), "create", **kwargs)
            assert result.success is True


class TestHandleUpdateAction:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "kwargs",
        [
            {},
            {"tool_name": "x"},
        ],
    )
    async def test_missing_required(self, kwargs):
        result = await run_impl(None, "update", **kwargs)
        assert "required" in result.error

    @pytest.mark.anyio
    async def test_tool_not_found(self):
        registry = MagicMock()
        registry.get_tool.return_value = None
        result = await run_impl(registry, "update", tool_name="x", python_code="x=1")
        assert "not found" in result.error

    @pytest.mark.anyio
    async def test_no_source_path(self):
        registry = make_tool(source_path=None)
        result = await run_impl(registry, "update", tool_name="x", python_code="x=1")
        assert result.success is False

    @pytest.mark.anyio
    async def test_update_success(self, tmp_path):
        code = (
            'TOOL_META = {"name": "x", "description": "test", "enabled": True}\n'
            "def f():\n    pass"
        )
        src = tmp_path / "x.py"
        src.write_text("old")
        registry = make_tool(source_path=str(src))
        result = await run_impl(registry, "update", tool_name="x", python_code=code)
        assert result.success is True

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "python_code, expected",
        [
            ("def f():\n    pass", "TOOL_META"),
            ("def f(", "Syntax"),
        ],
    )
    async def test_update_invalid_code(self, tmp_path, python_code, expected):
        src = tmp_path / "x.py"
        src.write_text("old")
        registry = make_tool(source_path=str(src))
        result = await run_impl(
            registry, "update", tool_name="x", python_code=python_code
        )
        assert expected in result.error


class TestHandleInfoAction:
    @pytest.mark.anyio
    async def test_no_tool_name(self):
        result = await run_impl(None, "info")
        assert "required" in result.error

    @pytest.mark.anyio
    async def test_tool_not_found(self):
        registry = MagicMock()
        registry.get_tool.return_value = None
        result = await run_impl(registry, "info", tool_name="x")
        assert "not found" in result.error


class TestUnknownAction:
    @pytest.mark.anyio
    async def test_unknown(self):
        result = await run_impl(None, "unknown")
        assert result.success is False
        assert "Unknown" in result.error
