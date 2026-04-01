"""Tests for token estimation sampling in token_utils.py."""

from code_puppy.token_utils import (
    _SAMPLING_THRESHOLD,
    _chars_per_token,
    _is_code_heavy,
    estimate_token_count,
)


class TestIsCodeHeavy:
    def test_python_code(self):
        code = "def foo():\n    return bar()\n\nclass Baz:\n    pass\n"
        assert _is_code_heavy(code) is True

    def test_prose(self):
        prose = "The quick brown fox jumped over the lazy dog. " * 5
        assert _is_code_heavy(prose) is False

    def test_short_text_always_false(self):
        assert _is_code_heavy("x") is False
        assert _is_code_heavy("") is False

    def test_javascript_code(self):
        js = "function hello() {\n  const x = 1;\n  return x;\n}\n" * 3
        assert _is_code_heavy(js) is True


class TestCharsPerToken:
    def test_code_ratio(self):
        code = "def foo():\n    return 42\n" * 10
        assert _chars_per_token(code) == 4.5

    def test_prose_ratio(self):
        prose = "This is a paragraph of normal text. " * 20
        assert _chars_per_token(prose) == 4.0


class TestEstimateTokenCount:
    def test_empty_returns_one(self):
        assert estimate_token_count("") == 1
        assert estimate_token_count(None) == 1

    def test_short_text_direct(self):
        text = "hello world"
        result = estimate_token_count(text)
        assert result == max(1, int(len(text) / 4.0))

    def test_short_code_direct(self):
        code = "def foo():\n    return 42\n"
        result = estimate_token_count(code)
        # Short text, code detection may or may not trigger
        assert result >= 1

    def test_large_text_uses_sampling(self):
        # Generate text larger than threshold
        prose = "The quick brown fox jumped over the lazy dog.\n" * 100
        assert len(prose) > _SAMPLING_THRESHOLD
        result = estimate_token_count(prose)
        # Should be in the right ballpark (within 50% of naive estimate)
        naive = int(len(prose) / 4.0)
        assert naive * 0.5 < result < naive * 1.5

    def test_large_code_uses_sampling(self):
        code = "def func_{i}():\n    return {i}\n".format(i=0) * 200
        # Make it clearly code-heavy
        code = "import os\nimport sys\n" + "def foo():\n    x = [1, 2, 3];\n    return x\n" * 100
        assert len(code) > _SAMPLING_THRESHOLD
        result = estimate_token_count(code)
        assert result >= 1

    def test_consistency_small_vs_large_boundary(self):
        """Token count shouldn't jump wildly at the sampling threshold."""
        # Text just below threshold
        text_small = "a" * (_SAMPLING_THRESHOLD - 1)
        # Text just above threshold (same density)
        text_large = "a" * (_SAMPLING_THRESHOLD + 100)
        result_small = estimate_token_count(text_small)
        result_large = estimate_token_count(text_large)
        # Larger text should have proportionally more tokens
        ratio = result_large / result_small
        expected_ratio = len(text_large) / len(text_small)
        assert abs(ratio - expected_ratio) < 0.3  # Within 30%

    def test_single_char(self):
        assert estimate_token_count("x") == 1

    def test_minimum_is_one(self):
        assert estimate_token_count("a") >= 1

    def test_uniform_lines_give_stable_estimate(self):
        """Sampling uniform content should give ~same result as full scan."""
        line = "hello world this is a test line\n"
        text = line * 500  # ~15K chars
        result = estimate_token_count(text)
        full_estimate = int(len(text) / 4.0)
        # Should be very close for uniform content
        assert abs(result - full_estimate) / full_estimate < 0.1  # Within 10%
