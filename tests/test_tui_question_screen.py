"""Tests for the QuestionScreen Textual screen.

Covers:
- Import and class hierarchy
- Key bindings declared
- Instantiation with Question objects
- State initialisation
- Action methods (cancel, submit, confirm, toggle, navigate)
- Timeout / timer-tick behaviour
- Input event handlers
- Render helpers (smoke tests — no running app required)
"""

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_questions(n: int = 2):
    """Return *n* minimal Question objects."""
    from code_puppy.tools.ask_user_question.models import Question, QuestionOption

    questions = []
    for i in range(n):
        questions.append(
            Question(
                question=f"Which option do you prefer for topic {i}?",
                header=f"topic-{i}",
                multi_select=(i % 2 == 1),
                options=[
                    QuestionOption(label="Alpha", description="First choice"),
                    QuestionOption(label="Beta", description="Second choice"),
                    QuestionOption(label="Gamma", description="Third choice"),
                ],
            )
        )
    return questions


def _binding_keys(screen_cls) -> set[str]:
    """Return all key strings from a screen's BINDINGS list."""
    return {b.key for b in screen_cls.BINDINGS}


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------


class TestImports:
    def test_question_screen_importable(self) -> None:
        from code_puppy.tui.screens.question_screen import QuestionScreen

        assert QuestionScreen is not None

    def test_question_result_type_importable(self) -> None:
        from code_puppy.tui.screens.question_screen import QuestionResult  # noqa: F401

        assert QuestionResult is not None

    def test_module_docstring_present(self) -> None:
        import code_puppy.tui.screens.question_screen as mod

        assert mod.__doc__ is not None
        assert len(mod.__doc__) > 10


# ---------------------------------------------------------------------------
# Class hierarchy
# ---------------------------------------------------------------------------


class TestClassHierarchy:
    def test_question_screen_is_screen_subclass(self) -> None:
        from textual.screen import Screen

        from code_puppy.tui.screens.question_screen import QuestionScreen

        assert issubclass(QuestionScreen, Screen)

    def test_question_screen_is_generic_over_result(self) -> None:
        """QuestionScreen is Screen[QuestionResult] — check via __orig_bases__."""
        from code_puppy.tui.screens.question_screen import QuestionScreen

        # Screen subclasses store generic arg in __orig_bases__
        orig_bases = getattr(QuestionScreen, "__orig_bases__", [])
        args_strs = [str(b) for b in orig_bases]
        assert any("QuestionResult" in s or "tuple" in s for s in args_strs), (
            "QuestionScreen should be typed as Screen[QuestionResult]"
        )


# ---------------------------------------------------------------------------
# Bindings
# ---------------------------------------------------------------------------


class TestBindings:
    def test_has_escape(self) -> None:
        from code_puppy.tui.screens.question_screen import QuestionScreen

        assert "escape" in _binding_keys(QuestionScreen)

    def test_has_ctrl_s(self) -> None:
        from code_puppy.tui.screens.question_screen import QuestionScreen

        assert "ctrl+s" in _binding_keys(QuestionScreen)

    def test_has_enter(self) -> None:
        from code_puppy.tui.screens.question_screen import QuestionScreen

        assert "enter" in _binding_keys(QuestionScreen)

    def test_has_space(self) -> None:
        from code_puppy.tui.screens.question_screen import QuestionScreen

        assert "space" in _binding_keys(QuestionScreen)

    def test_has_vim_navigation(self) -> None:
        from code_puppy.tui.screens.question_screen import QuestionScreen

        keys = _binding_keys(QuestionScreen)
        for key in ("j", "k", "h", "l"):
            assert key in keys, f"Expected vim key '{key}' in BINDINGS"

    def test_has_arrow_navigation(self) -> None:
        from code_puppy.tui.screens.question_screen import QuestionScreen

        keys = _binding_keys(QuestionScreen)
        for key in ("up", "down", "left", "right"):
            assert key in keys, f"Expected arrow key '{key}' in BINDINGS"


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------


class TestInstantiation:
    def test_instantiates_with_questions(self) -> None:
        from code_puppy.tui.screens.question_screen import QuestionScreen

        screen = QuestionScreen(questions=_make_questions(2))
        assert screen is not None

    def test_instantiates_with_timeout(self) -> None:
        from code_puppy.tui.screens.question_screen import QuestionScreen

        screen = QuestionScreen(questions=_make_questions(1), timeout_seconds=60)
        assert screen._state.timeout_seconds == 60

    def test_state_initialized(self) -> None:
        from code_puppy.tools.ask_user_question.terminal_ui import QuestionUIState
        from code_puppy.tui.screens.question_screen import QuestionScreen

        screen = QuestionScreen(questions=_make_questions(3))
        assert isinstance(screen._state, QuestionUIState)
        assert len(screen._state.questions) == 3

    def test_default_timeout_is_300(self) -> None:
        from code_puppy.tui.screens.question_screen import QuestionScreen

        screen = QuestionScreen(questions=_make_questions(1))
        assert screen._state.timeout_seconds == 300

    def test_state_starts_at_first_question(self) -> None:
        from code_puppy.tui.screens.question_screen import QuestionScreen

        screen = QuestionScreen(questions=_make_questions(2))
        assert screen._state.current_question_index == 0


# ---------------------------------------------------------------------------
# Action: cancel
# ---------------------------------------------------------------------------


class TestActionCancel:
    """action_cancel() without a running app — we mock dismiss()."""

    def _screen(self, n: int = 2):
        from code_puppy.tui.screens.question_screen import QuestionScreen

        s = QuestionScreen(questions=_make_questions(n))
        s._dismissed: list = []
        s.dismiss = lambda result: s._dismissed.append(result)  # type: ignore
        return s

    def test_cancel_sends_cancelled_true(self) -> None:
        screen = self._screen()
        screen.action_cancel()
        assert len(screen._dismissed) == 1
        _answers, cancelled, timed_out = screen._dismissed[0]
        assert cancelled is True
        assert timed_out is False
        assert _answers == []

    def test_cancel_in_other_mode_exits_other_mode_first(self) -> None:
        screen = self._screen()
        screen._state.entering_other_text = True
        screen._state.other_text_buffer = "partial"
        # Without a running app _refresh_all will fail — patch it out
        screen._refresh_all = lambda: None  # type: ignore
        screen.action_cancel()
        # Should NOT dismiss; should exit other-text mode instead
        assert len(screen._dismissed) == 0
        assert screen._state.entering_other_text is False
        assert screen._state.other_text_buffer == ""


# ---------------------------------------------------------------------------
# Action: submit_all
# ---------------------------------------------------------------------------


class TestActionSubmitAll:
    def _screen(self):
        from code_puppy.tui.screens.question_screen import QuestionScreen

        s = QuestionScreen(questions=_make_questions(2))
        s._dismissed: list = []
        s.dismiss = lambda result: s._dismissed.append(result)  # type: ignore
        return s

    def test_submit_all_sends_cancelled_false(self) -> None:
        screen = self._screen()
        screen.action_submit_all()
        assert len(screen._dismissed) == 1
        _answers, cancelled, timed_out = screen._dismissed[0]
        assert cancelled is False
        assert timed_out is False

    def test_submit_all_commits_other_text_first(self) -> None:
        screen = self._screen()
        screen._state.entering_other_text = True
        screen._state.other_text_buffer = "custom answer"
        screen.action_submit_all()
        assert len(screen._dismissed) == 1
        # Should have called commit_other_text, clearing entering_other_text
        assert screen._state.entering_other_text is False


# ---------------------------------------------------------------------------
# Action: confirm (advance / submit)
# ---------------------------------------------------------------------------


class TestActionConfirm:
    def _screen(self, n: int = 2):
        from code_puppy.tui.screens.question_screen import QuestionScreen

        s = QuestionScreen(questions=_make_questions(n))
        s._dismissed: list = []
        s.dismiss = lambda result: s._dismissed.append(result)  # type: ignore
        s._refresh_all = lambda: None  # type: ignore
        return s

    def test_confirm_advances_to_next_question(self) -> None:
        screen = self._screen(2)
        # Select option 0 so it's valid
        screen._state.select_current_option()
        screen.action_confirm()
        # Not yet dismissed — moved to Q2
        assert len(screen._dismissed) == 0
        assert screen._state.current_question_index == 1

    def test_confirm_exits_other_text_mode(self) -> None:
        screen = self._screen(2)
        screen._state.entering_other_text = True
        screen._state.other_text_buffer = "something"
        screen.action_confirm()
        assert screen._state.entering_other_text is False

    def test_confirm_enters_other_text_mode_when_cursor_on_other(self) -> None:
        screen = self._screen(1)
        # Move cursor to last (Other) option
        other_idx = len(screen._state.current_question.options)
        screen._state.current_cursor = other_idx
        screen.action_confirm()
        assert screen._state.entering_other_text is True


# ---------------------------------------------------------------------------
# Action: toggle_option
# ---------------------------------------------------------------------------


class TestActionToggle:
    def _screen(self, multi: bool = False):
        from code_puppy.tools.ask_user_question.models import Question, QuestionOption
        from code_puppy.tui.screens.question_screen import QuestionScreen

        q = Question(
            question="Pick one",
            header="pick",
            multi_select=multi,
            options=[
                QuestionOption(label="A"),
                QuestionOption(label="B"),
            ],
        )
        s = QuestionScreen(questions=[q])
        s._refresh_all = lambda: None  # type: ignore
        return s

    def test_toggle_multi_select_adds_to_selected(self) -> None:
        screen = self._screen(multi=True)
        screen._state.current_cursor = 0
        screen.action_toggle_option()
        assert screen._state.is_option_selected(0)

    def test_toggle_multi_select_removes_if_already_selected(self) -> None:
        screen = self._screen(multi=True)
        screen._state.current_cursor = 0
        screen.action_toggle_option()  # select
        screen.action_toggle_option()  # deselect
        assert not screen._state.is_option_selected(0)

    def test_toggle_single_select_sets_selection(self) -> None:
        screen = self._screen(multi=False)
        screen._state.current_cursor = 1
        screen.action_toggle_option()
        assert screen._state.single_selections[0] == 1


# ---------------------------------------------------------------------------
# Navigation actions
# ---------------------------------------------------------------------------


class TestNavigationActions:
    def _screen(self, n: int = 3):
        from code_puppy.tui.screens.question_screen import QuestionScreen

        s = QuestionScreen(questions=_make_questions(n))
        s._refresh_all = lambda: None  # type: ignore
        s._render_right_panel = lambda: None  # type: ignore
        return s

    def test_next_question_advances_index(self) -> None:
        screen = self._screen(3)
        screen.action_next_question()
        assert screen._state.current_question_index == 1

    def test_prev_question_does_not_go_below_zero(self) -> None:
        screen = self._screen(3)
        screen.action_prev_question()
        assert screen._state.current_question_index == 0

    def test_next_option_advances_cursor(self) -> None:
        screen = self._screen(2)
        screen.action_next_option()
        assert screen._state.current_cursor == 1

    def test_prev_option_does_not_go_below_zero(self) -> None:
        screen = self._screen(2)
        screen.action_prev_option()
        assert screen._state.current_cursor == 0

    def test_navigation_blocked_in_other_text_mode(self) -> None:
        screen = self._screen(3)
        screen._state.entering_other_text = True
        screen.action_next_question()
        screen.action_next_option()
        # Should not have moved
        assert screen._state.current_question_index == 0
        assert screen._state.current_cursor == 0


# ---------------------------------------------------------------------------
# Timeout / timer tick
# ---------------------------------------------------------------------------


class TestTimerTick:
    @pytest.mark.asyncio
    async def test_timer_tick_dismisses_on_timeout(self) -> None:
        from code_puppy.tui.screens.question_screen import QuestionScreen

        screen = QuestionScreen(questions=_make_questions(1), timeout_seconds=0)
        screen._dismissed: list = []
        screen.dismiss = lambda result: screen._dismissed.append(result)  # type: ignore
        # Force timeout
        screen._state.timeout_seconds = 0
        await screen._on_timer_tick()
        assert len(screen._dismissed) == 1
        _answers, cancelled, timed_out = screen._dismissed[0]
        assert timed_out is True
        assert cancelled is False

    @pytest.mark.asyncio
    async def test_timer_tick_no_dismiss_when_not_timed_out(self) -> None:
        from code_puppy.tui.screens.question_screen import QuestionScreen

        screen = QuestionScreen(questions=_make_questions(1), timeout_seconds=999)
        screen._dismissed: list = []
        screen.dismiss = lambda result: screen._dismissed.append(result)  # type: ignore
        screen._update_timeout_display = lambda: None  # type: ignore
        await screen._on_timer_tick()
        assert len(screen._dismissed) == 0


# ---------------------------------------------------------------------------
# Input event handlers
# ---------------------------------------------------------------------------


class TestInputEvents:
    def _screen(self):
        from code_puppy.tui.screens.question_screen import QuestionScreen

        s = QuestionScreen(questions=_make_questions(1))
        s._refresh_all = lambda: None  # type: ignore
        return s

    def test_on_input_submitted_commits_other_text(self) -> None:
        from unittest.mock import MagicMock

        screen = self._screen()
        screen._state.entering_other_text = True
        screen._state.other_text_buffer = "my custom answer"

        event = MagicMock()
        event.input.id = "q-other-input"
        event.value = "my custom answer"

        screen.on_input_submitted(event)
        assert screen._state.entering_other_text is False

    def test_on_input_submitted_ignores_other_input_ids(self) -> None:
        from unittest.mock import MagicMock

        screen = self._screen()
        screen._state.entering_other_text = True

        event = MagicMock()
        event.input.id = "some-other-widget"
        event.value = "irrelevant"

        screen.on_input_submitted(event)
        # entering_other_text should remain unchanged
        assert screen._state.entering_other_text is True

    def test_on_input_changed_syncs_buffer(self) -> None:
        from unittest.mock import MagicMock

        screen = self._screen()
        screen._state.entering_other_text = True

        event = MagicMock()
        event.input.id = "q-other-input"
        event.value = "partial text"

        screen.on_input_changed(event)
        assert screen._state.other_text_buffer == "partial text"

    def test_on_input_changed_ignored_when_not_in_other_mode(self) -> None:
        from unittest.mock import MagicMock

        screen = self._screen()
        screen._state.entering_other_text = False
        screen._state.other_text_buffer = "original"

        event = MagicMock()
        event.input.id = "q-other-input"
        event.value = "new text"

        screen.on_input_changed(event)
        assert screen._state.other_text_buffer == "original"


# ---------------------------------------------------------------------------
# State helpers (via QuestionUIState — integration smoke test)
# ---------------------------------------------------------------------------


class TestStateIntegration:
    def test_build_answers_returns_list(self) -> None:
        from code_puppy.tui.screens.question_screen import QuestionScreen

        screen = QuestionScreen(questions=_make_questions(2))
        # Select an option on each question
        screen._state.select_current_option()
        screen._state.next_question()
        screen._state.select_current_option()
        answers = screen._state.build_answers()
        assert isinstance(answers, list)
        assert len(answers) == 2

    def test_is_question_answered_reflects_selection(self) -> None:
        from code_puppy.tui.screens.question_screen import QuestionScreen

        screen = QuestionScreen(questions=_make_questions(2))
        assert not screen._state.is_question_answered(0)
        screen._state.select_current_option()
        assert screen._state.is_question_answered(0)

    def test_timeout_get_time_remaining_positive(self) -> None:
        from code_puppy.tui.screens.question_screen import QuestionScreen

        screen = QuestionScreen(questions=_make_questions(1), timeout_seconds=300)
        remaining = screen._state.get_time_remaining()
        assert remaining > 0

    def test_timeout_is_timed_out_false_initially(self) -> None:
        from code_puppy.tui.screens.question_screen import QuestionScreen

        screen = QuestionScreen(questions=_make_questions(1), timeout_seconds=300)
        assert not screen._state.is_timed_out()
