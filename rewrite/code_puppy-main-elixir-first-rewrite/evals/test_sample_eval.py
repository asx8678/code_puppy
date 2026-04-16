"""Sample eval demonstrating the eval framework.

This eval is marked ALWAYS_PASSES because it uses a mock result rather than
calling a real LLM. It serves as a living example of how to write evals and
as a smoke-test for the framework itself.

Run with:
    RUN_EVALS=1 pytest evals/test_sample_eval.py -v
"""

import pytest

from evals.eval_helpers import EvalPolicy, EvalResult, ToolCall, log_eval


@pytest.mark.eval
def test_sample_eval_framework():
    """Verify the eval framework captures tool calls correctly.

    Policy: ALWAYS_PASSES — uses a mock result, fully deterministic.
    """
    _policy = EvalPolicy.ALWAYS_PASSES  # document intent; not enforced yet

    # Simulate what a real eval would produce after running an agent
    result = EvalResult(
        response_text="I'll read the file for you.",
        tool_calls=[
            ToolCall(
                name="read_file",
                args={"path": "README.md"},
                result="# Code Puppy...",
            ),
        ],
        duration_seconds=1.5,
        model_name="mock-model",
    )

    # Assert on the captured tool calls
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "read_file"
    assert "README.md" in result.tool_calls[0].args["path"]

    # Persist for debugging / inspection
    log_eval("sample_eval_framework", result)
