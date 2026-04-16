"""Tests for code_puppy.utils.overflow_detect."""

from code_puppy.utils.overflow_detect import (
    is_context_overflow,
    is_rate_limit_error,
    get_overflow_patterns,
    get_non_overflow_patterns,
)


class TestIsContextOverflow:
    """Tests for the is_context_overflow function."""

    # --- Anthropic ---
    def test_anthropic_prompt_too_long(self):
        assert is_context_overflow("prompt is too long: 150000 tokens > 128000")

    def test_anthropic_request_too_large(self):
        assert is_context_overflow("request_too_large: maximum allowed size exceeded")

    # --- OpenAI ---
    def test_openai_maximum_context_length(self):
        assert is_context_overflow(
            "This model's maximum context length is 128000 tokens. "
            "However, your messages resulted in 150000 tokens."
        )

    def test_openai_reduce_length(self):
        assert is_context_overflow(
            "Please reduce the length of the messages or completion."
        )

    def test_openai_input_too_long(self):
        assert is_context_overflow("input is too long for requested model")

    # --- Google / Vertex ---
    def test_google_exceeds_context_window(self):
        assert is_context_overflow("Request exceeds the context window")

    def test_google_input_token_count(self):
        assert is_context_overflow(
            "The input token count of 200000 exceeds the maximum of 128000"
        )

    def test_google_maximum_prompt_length(self):
        assert is_context_overflow("maximum prompt length is 32768 tokens")

    # --- Generic / Multi-provider ---
    def test_exceeds_limit(self):
        assert is_context_overflow("Input exceeds the limit of 128000 tokens")

    def test_exceeded_model_token_limit(self):
        assert is_context_overflow("exceeded model token limit")

    def test_context_window_exceeds_limit(self):
        assert is_context_overflow("context window exceeds limit")

    def test_too_many_tokens(self):
        assert is_context_overflow("too many tokens in the request")

    def test_token_limit_exceeded(self):
        assert is_context_overflow("token limit exceeded")

    # --- Ollama / llama.cpp ---
    def test_ollama_prompt_too_long(self):
        assert is_context_overflow("prompt too long; exceeded max context length")

    def test_context_length_exceeded(self):
        assert is_context_overflow("context_length_exceeded")

    def test_context_length_exceeded_spaces(self):
        assert is_context_overflow("context length exceeded")

    # --- Bare HTTP status ---
    def test_400_no_body(self):
        assert is_context_overflow("400 (no body)")

    def test_413_no_body(self):
        assert is_context_overflow("413 status code (no body)")

    # --- Non-overflow errors (should NOT match) ---
    def test_rate_limit_not_overflow(self):
        assert not is_context_overflow("rate limit exceeded")

    def test_too_many_requests_not_overflow(self):
        assert not is_context_overflow("too many requests, please retry")

    def test_throttling_not_overflow(self):
        assert not is_context_overflow("Throttling error: too many requests")

    def test_service_unavailable_not_overflow(self):
        assert not is_context_overflow("Service unavailable: try again later")

    def test_generic_error_not_overflow(self):
        assert not is_context_overflow("connection reset by peer")

    def test_empty_string_not_overflow(self):
        assert not is_context_overflow("")

    # --- Silent overflow detection ---
    def test_silent_overflow_detected(self):
        assert is_context_overflow(
            "", input_tokens=200000, context_window=128000
        )

    def test_silent_overflow_not_triggered_within_window(self):
        assert not is_context_overflow(
            "", input_tokens=100000, context_window=128000
        )

    def test_silent_overflow_needs_both_params(self):
        assert not is_context_overflow("", input_tokens=200000)
        assert not is_context_overflow("", context_window=128000)

    # --- Case insensitivity ---
    def test_case_insensitive(self):
        assert is_context_overflow("PROMPT IS TOO LONG")
        assert is_context_overflow("Maximum Context Length Is 128000 Tokens")


class TestIsRateLimitError:
    def test_rate_limit(self):
        assert is_rate_limit_error("rate limit exceeded")

    def test_too_many_requests(self):
        assert is_rate_limit_error("too many requests")

    def test_throttling(self):
        assert is_rate_limit_error("Throttling error: slow down")

    def test_not_rate_limit(self):
        assert not is_rate_limit_error("prompt is too long")

    def test_empty(self):
        assert not is_rate_limit_error("")


class TestPatternAccessors:
    def test_overflow_patterns_returns_list(self):
        patterns = get_overflow_patterns()
        assert isinstance(patterns, list)
        assert len(patterns) >= 18  # At least 18 patterns per spec

    def test_non_overflow_patterns_returns_list(self):
        patterns = get_non_overflow_patterns()
        assert isinstance(patterns, list)
        assert len(patterns) >= 3

    def test_patterns_are_copies(self):
        """Modifying returned list doesn't affect originals."""
        patterns = get_overflow_patterns()
        original_len = len(patterns)
        patterns.clear()
        assert len(get_overflow_patterns()) == original_len
