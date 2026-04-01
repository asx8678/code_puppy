"""Tests for improved token estimation heuristic."""

from code_puppy.token_utils import estimate_token_count, _is_code_heavy


def test_empty_string_returns_one():
    assert estimate_token_count("") == 1


def test_short_text():
    # "hello world" = 11 chars, ~4 chars/token = 2 tokens
    result = estimate_token_count("hello world")
    assert result >= 1
    assert result <= 5


def test_code_detection():
    code = """
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)

class Calculator:
    def __init__(self):
        self.history = []

    def add(self, a, b):
        result = a + b
        self.history.append(result)
        return result
"""
    assert _is_code_heavy(code) is True


def test_prose_detection():
    prose = """
The quick brown fox jumps over the lazy dog. This is a simple paragraph
of English text that should not be detected as code. It contains normal
punctuation and sentence structure without any programming constructs.
"""
    assert _is_code_heavy(prose) is False


def test_code_estimated_lower_than_old_heuristic():
    """Code should be estimated at ~4.5 chars/token, not 2.5 chars/token."""
    code = "def foo():\n    return bar(x, y)\n" * 20
    new_estimate = estimate_token_count(code)
    old_estimate = max(1, len(code) * 2 // 5)  # old formula: len/2.5
    # New estimate should be meaningfully lower than old (less overestimation)
    assert new_estimate < old_estimate


def test_prose_estimated_lower_than_old_heuristic():
    """Prose at ~4 chars/token should also be lower than old 2.5 chars/token."""
    prose = "The rain in Spain falls mainly on the plain. " * 20
    new_estimate = estimate_token_count(prose)
    old_estimate = max(1, len(prose) * 2 // 5)
    assert new_estimate < old_estimate


def test_minimum_one_token():
    assert estimate_token_count("a") == 1
    assert estimate_token_count("ab") == 1
