"""Full coverage tests for tools/ask_user_question/handler.py."""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from code_puppy.tools.ask_user_question.handler import (
    _cancelled_response,
    _format_validation_error,
    _run_interactive_picker,
    ask_user_question,
    is_interactive,
)

H = "code_puppy.tools.ask_user_question.handler"

VALID_QUESTION = [
    {"question": "q", "header": "h", "options": [{"label": "a"}, {"label": "b"}]}
]


def _patch_gates(subagent=False, wiggum=False, interactive=True, **extra):
    """Enter the standard handler gate patches; return an active ExitStack.

    `extra` maps handler attribute name -> patch kwargs dict.
    """
    stack = ExitStack()
    stack.enter_context(patch(f"{H}.is_subagent", return_value=subagent))
    stack.enter_context(patch(f"{H}.is_wiggum_active", return_value=wiggum))
    stack.enter_context(patch(f"{H}.is_interactive", return_value=interactive))
    for name, kwargs in extra.items():
        stack.enter_context(patch(f"{H}.{name}", **kwargs))
    return stack


def _patch_validated_picker(picker_kwargs):
    """Patch gates plus a passing _validate_input and a _run_interactive_picker."""
    stack = _patch_gates()
    mock_val = stack.enter_context(patch(f"{H}._validate_input"))
    mock_val.return_value = MagicMock(questions=[MagicMock()])
    stack.enter_context(patch(f"{H}._run_interactive_picker", **picker_kwargs))
    return stack


class TestIsInteractive:
    @pytest.mark.parametrize(
        "stdin_kwargs, env, expected",
        [
            ({"isatty.return_value": True}, {}, True),
            ({"isatty.return_value": False}, {}, False),
            ({"isatty.return_value": True}, {"CI": "true"}, False),
        ],
    )
    def test_isatty_and_env(self, stdin_kwargs, env, expected):
        with (
            patch.object(sys, "stdin", new=MagicMock(**stdin_kwargs)),
            patch.dict(os.environ, env, clear=True),
        ):
            assert is_interactive() is expected

    def test_attribute_error(self):
        with patch.object(sys, "stdin", new=None):
            assert is_interactive() is False


class TestCancelledResponse:
    def test_returns_cancelled(self):
        result = _cancelled_response()
        assert result.cancelled is True
        assert result.error is None


class TestAskUserQuestion:
    def test_subagent_blocked(self):
        with _patch_gates(subagent=True):
            result = ask_user_question(
                [{"question": "q", "header": "h", "options": [{"label": "a"}]}]
            )
        assert result.error is not None
        assert "sub-agent" in result.error

    def test_wiggum_blocked(self):
        # Validation happens first now, so use a fully valid question payload
        # (2-6 options) to actually reach the wiggum gate.
        with _patch_gates(wiggum=True):
            result = ask_user_question(VALID_QUESTION)
        assert "wiggum" in result.error.lower()

    def test_non_interactive(self):
        with _patch_gates(interactive=False):
            result = ask_user_question(VALID_QUESTION)
        assert "not running" in result.error

    def test_validation_error(self):
        with _patch_gates():
            result = ask_user_question([{"bad": "data"}])
        assert result.error is not None

    def test_type_error(self):
        with _patch_gates(
            _validate_input={"side_effect": TypeError("bad")},
        ):
            result = ask_user_question([])
        assert "Validation error" in result.error

    @pytest.mark.parametrize(
        "picker_kwargs, check",
        [
            ({"side_effect": KeyboardInterrupt}, lambda r: r.cancelled is True),
            (
                {"side_effect": OSError("fail")},
                lambda r: "error" in r.error.lower(),
            ),
            ({"return_value": ([], False, True)}, lambda r: r.timed_out is True),
            ({"return_value": ([], True, False)}, lambda r: r.cancelled is True),
        ],
    )
    def test_picker_outcomes(self, picker_kwargs, check):
        with _patch_validated_picker(picker_kwargs):
            result = ask_user_question(VALID_QUESTION)
        assert check(result)

    def test_success(self):
        from code_puppy.tools.ask_user_question.models import QuestionAnswer

        answer = QuestionAnswer(
            question_index=0, question_header="h", selected_options=["a"]
        )
        with _patch_validated_picker({"return_value": ([answer], False, False)}):
            result = ask_user_question(VALID_QUESTION)
        assert len(result.answers) == 1


class TestRunInteractivePicker:
    def test_async_context_raises(self):
        """When in async context, should raise RuntimeError."""

        async def in_async():
            with pytest.raises(RuntimeError):
                _run_interactive_picker([], 10)

        asyncio.run(in_async())


class TestFormatValidationError:
    def test_no_errors(self):
        mock_err = MagicMock()
        mock_err.errors.return_value = []
        assert _format_validation_error(mock_err) == "Validation error"

    def test_with_errors(self):
        mock_err = MagicMock()
        mock_err.errors.return_value = [{"loc": ("field",), "msg": "is required"}]
        assert "field" in _format_validation_error(mock_err)

    def test_truncated_errors(self):
        mock_err = MagicMock()
        mock_err.errors.return_value = [
            {"loc": (f"field{i}",), "msg": f"error{i}"} for i in range(20)
        ]
        assert "more" in _format_validation_error(mock_err)
