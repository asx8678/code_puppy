from unittest.mock import patch

from code_puppy.tools.ask_user_question.helpers import select_with_smart_defaults

# Patch target for lazy imports in helpers.py
# (ask_user_question is imported via code_puppy.tools.ask_user_question)
PATCH_TARGET = "code_puppy.tools.ask_user_question.ask_user_question"


def test_empty_list_returns_none():
    assert select_with_smart_defaults([]) is None


def test_single_item_auto_selects():
    assert select_with_smart_defaults(["only"]) == "only"


def test_single_item_dict_auto_selects():
    item = {"id": 1, "name": "alpha"}
    assert select_with_smart_defaults([item]) is item  # identity preserved


def test_single_item_no_interactive_call():
    """Verify we don't invoke the interactive flow for single-item lists."""
    with patch(PATCH_TARGET) as mock_ask:
        result = select_with_smart_defaults(["x"])
        mock_ask.assert_not_called()
        assert result == "x"


def test_empty_no_interactive_call():
    """Verify we don't invoke the interactive flow for empty lists."""
    with patch(PATCH_TARGET) as mock_ask:
        result = select_with_smart_defaults([])
        mock_ask.assert_not_called()
        assert result is None


def test_custom_display_fn_for_single_item():
    """display_fn should NOT be invoked when auto-collapsing."""
    calls = []

    def render(item):
        calls.append(item)
        return str(item)

    result = select_with_smart_defaults([42], display_fn=render)
    assert result == 42
    assert calls == []  # display_fn not called in auto-collapse path


def test_custom_display_fn_used_for_multi_item():
    """display_fn should be invoked for multi-item lists."""
    calls = []

    def render(item):
        calls.append(item)
        return f"Item {item}"

    # Create a mock result for multi-item selection
    from code_puppy.tools.ask_user_question.models import (
        AskUserQuestionOutput,
        QuestionAnswer,
    )

    mock_result = AskUserQuestionOutput(
        answers=[QuestionAnswer(question_header="Select", selected_options=["Item 1"])]
    )

    with patch(PATCH_TARGET, return_value=mock_result):
        result = select_with_smart_defaults([1, 2, 3], display_fn=render)

    assert result == 1  # Returns the item matching the selected label
    assert calls == [1, 2, 3]  # display_fn called for all items


def test_multi_item_no_selection_returns_none():
    """When user cancels or doesn't select, return None."""
    from code_puppy.tools.ask_user_question.models import AskUserQuestionOutput

    mock_result = AskUserQuestionOutput(
        answers=[], cancelled=True, error=None, timed_out=False
    )

    with patch(PATCH_TARGET, return_value=mock_result):
        result = select_with_smart_defaults(["a", "b", "c"])

    assert result is None


def test_multi_item_empty_selection_returns_none():
    """When user doesn't select anything, return None."""
    from code_puppy.tools.ask_user_question.models import (
        AskUserQuestionOutput,
        QuestionAnswer,
    )

    mock_result = AskUserQuestionOutput(
        answers=[QuestionAnswer(question_header="Select", selected_options=[])]
    )

    with patch(PATCH_TARGET, return_value=mock_result):
        result = select_with_smart_defaults(["a", "b", "c"])

    assert result is None


def test_multi_item_error_returns_none():
    """When the tool returns an error, return None."""
    from code_puppy.tools.ask_user_question.models import AskUserQuestionOutput

    mock_result = AskUserQuestionOutput(
        answers=[], cancelled=False, error="Something went wrong", timed_out=False
    )

    with patch(PATCH_TARGET, return_value=mock_result):
        result = select_with_smart_defaults(["a", "b", "c"])

    assert result is None


def test_multi_item_timed_out_returns_none():
    """When the tool times out, return None."""
    from code_puppy.tools.ask_user_question.models import AskUserQuestionOutput

    mock_result = AskUserQuestionOutput(
        answers=[], cancelled=False, error=None, timed_out=True
    )

    with patch(PATCH_TARGET, return_value=mock_result):
        result = select_with_smart_defaults(["a", "b", "c"])

    assert result is None


def test_custom_question_header_and_prompt():
    """Custom header and prompt are passed through correctly."""
    from code_puppy.tools.ask_user_question.models import (
        AskUserQuestionOutput,
        QuestionAnswer,
    )

    # Items are rendered via str() by default, so "a" -> label "a", "b" -> label "b"
    mock_result = AskUserQuestionOutput(
        answers=[
            QuestionAnswer(
                question_header="my-header",
                selected_options=["a"],  # Select "a"
            )
        ]
    )

    with patch(PATCH_TARGET, return_value=mock_result) as mock_ask:
        result = select_with_smart_defaults(
            ["a", "b"],
            question_header="my-header",  # max 12 chars
            prompt_text="Choose wisely",
        )

        # Verify the question was created with correct values
        call_args = mock_ask.call_args
        questions = call_args[0][0]
        assert len(questions) == 1
        assert questions[0].header == "my-header"
        assert questions[0].question == "Choose wisely"

    assert result == "a"
