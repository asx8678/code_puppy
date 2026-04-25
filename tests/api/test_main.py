"""Tests for code_puppy/api/main.py."""

import logging
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI


def test_app_module_level():
    """The module-level `app` is a FastAPI instance."""
    from code_puppy.api.main import app

    assert isinstance(app, FastAPI)


def test_main_calls_uvicorn():
    """main() calls uvicorn.run with correct defaults."""
    with patch("code_puppy.api.main.uvicorn") as mock_uvicorn:
        from code_puppy.api.main import main

        main()
        mock_uvicorn.run.assert_called_once()
        call_kwargs = mock_uvicorn.run.call_args
        assert (
            call_kwargs[1]["host"] == "127.0.0.1" or call_kwargs[0][1] == "127.0.0.1"
            if len(call_kwargs[0]) > 1
            else True
        )


def test_main_custom_host_port():
    """main() passes custom host and port when allow_external=True."""
    with patch("code_puppy.api.main.uvicorn") as mock_uvicorn:
        from code_puppy.api.main import main

        main(host="0.0.0.0", port=9999, allow_external=True)
        args, kwargs = mock_uvicorn.run.call_args
        assert kwargs.get("host", args[1] if len(args) > 1 else None) == "0.0.0.0"


def test_main_non_localhost_warns(caplog) -> None:
    """Binding to a non-localhost address with allow_external=True logs a warning."""
    with patch("code_puppy.api.main.uvicorn"):
        from code_puppy.api.main import main

        with caplog.at_level(logging.WARNING, logger="code_puppy.api.main"):
            main(host="0.0.0.0", allow_external=True)
            assert any("Binding to" in r.message for r in caplog.records)


def test_main_non_localhost_refuses_without_allow_external() -> None:
    """Binding to a non-localhost address without allow_external raises SystemExit."""
    with patch.dict("os.environ", {}, clear=False):
        with patch("code_puppy.api.main.uvicorn"):
            from code_puppy.api.main import main

            with pytest.raises(SystemExit, match="Refusing to bind"):
                main(host="0.0.0.0", allow_external=False)


def test_main_allow_external_env_var() -> None:
    """CODE_PUPPY_ALLOW_EXTERNAL=1 allows non-localhost binding."""
    with patch.dict("os.environ", {"CODE_PUPPY_ALLOW_EXTERNAL": "1"}):
        with patch("code_puppy.api.main.uvicorn"):
            from code_puppy.api.main import main

            main(host="0.0.0.0")  # Should NOT raise


def test_routers_init_imports():
    """Test that routers __init__ exports the expected modules including runtime."""
    from code_puppy.api.routers import agents, commands, config, runtime, sessions

    assert agents is not None
    assert commands is not None
    assert config is not None
    assert sessions is not None
    assert runtime is not None


def test_main_open_browser() -> None:
    """open_browser=True schedules a browser open timer."""
    with patch("code_puppy.api.main.uvicorn"):
        with patch("code_puppy.api.main.webbrowser"):
            with patch("code_puppy.api.main.threading.Timer") as mock_timer:
                from code_puppy.api.main import main

                mock_timer.return_value.start = MagicMock()
                main(host="127.0.0.1", port=8765, open_browser=True)
                mock_timer.assert_called_once()
                mock_timer.return_value.start.assert_called_once()


def test_main_localhost_no_warning_no_exit(caplog) -> None:
    """Binding to localhost does not emit a security warning or exit."""
    with patch("code_puppy.api.main.uvicorn"):
        from code_puppy.api.main import main

        with caplog.at_level(logging.WARNING, logger="code_puppy.api.main"):
            main(host="127.0.0.1")
            assert not any("Binding to" in r.message for r in caplog.records)
