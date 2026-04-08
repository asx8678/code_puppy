"""Tests for tool_id sanitization helper."""

import random
import string

from code_puppy.claude_cache_client import sanitize_tool_id, _ANTHROPIC_TOOL_ID_RE


class TestSanitizeToolId:
    """Tests for the sanitize_tool_id helper function."""

    def test_valid_ids_pass_through_unchanged(self):
        """Valid ids matching ^[a-zA-Z0-9_-]+$ should be returned unchanged."""
        valid_ids = [
            "call_abc123",
            "fc_deadbeef",
            "sanitized_abc",
            "a-b_c-1",
            "simple",
            "ABC123",
            "a1B2c3D4",
            "tool-123_call",
            "xyz_",
        ]
        for vid in valid_ids:
            result = sanitize_tool_id(vid)
            assert result == vid, f"Valid id {vid!r} should pass through unchanged, got {result!r}"
            assert _ANTHROPIC_TOOL_ID_RE.match(result), f"Result {result!r} should still match regex"

    def test_invalid_ids_are_rewritten(self):
        """Ids with invalid characters should be rewritten to sanitized_... format."""
        invalid_ids = [
            "fc_a.b.c",      # dots
            "fc_a/b/c",      # slashes
            "fc_a:b:c",      # colons
            "fc_a=b=c",      # equals
            "fc_a+b+c",      # plus
            "fc a b c",      # space
            "fc#a#b",        # hash
            "tool.call.id",  # multiple dots
            "https://example.com",  # URL-like
            "uuid:1234-5678",       # uuid format
        ]
        for iid in invalid_ids:
            result = sanitize_tool_id(iid)
            assert result != iid, f"Invalid id {iid!r} should be rewritten"
            assert result.startswith("sanitized_"), f"Result should start with 'sanitized_', got {result!r}"
            assert _ANTHROPIC_TOOL_ID_RE.match(result), f"Result {result!r} should match Anthropic pattern"

    def test_sanitize_is_idempotent(self):
        """Calling sanitize twice should give same result as once."""
        test_cases = [
            "valid_id_123",      # valid
            "fc_a.b.c",          # invalid with dots
            "fc_a:b:c",          # invalid with colons
            "",                  # empty
        ]
        for tc in test_cases:
            once = sanitize_tool_id(tc)
            twice = sanitize_tool_id(once)
            assert once == twice, f"Idempotent check failed for {tc!r}: once={once!r}, twice={twice!r}"

    def test_sanitize_is_deterministic(self):
        """Same input should always produce same output."""
        test_cases = [
            "fc_a.b.c",
            "call_123",
            "",
            "some.long.id:with+chars",
        ]
        for tc in test_cases:
            results = [sanitize_tool_id(tc) for _ in range(10)]
            assert all(r == results[0] for r in results), f"Non-deterministic for {tc!r}: {results}"

    def test_empty_and_non_string_inputs(self):
        """Empty string and non-string inputs should be handled gracefully."""
        # Empty string returns empty string
        assert sanitize_tool_id("") == ""

        # Non-string inputs return unchanged (no crash)
        assert sanitize_tool_id(None) is None
        assert sanitize_tool_id(123) == 123
        assert sanitize_tool_id([]) == []
        assert sanitize_tool_id({}) == {}

    def test_collision_fuzz_deterministic(self):
        """Generate random invalid ids and verify collision rate is minimal (seeded for reproducibility)."""
        rng = random.Random(0)  # SEEDED
        seen = set()
        for _ in range(1000):
            # Generate a random invalid id
            length = rng.randint(5, 30)
            chars = rng.choices("abc123./:=+", k=length)  # Mix of valid and invalid chars
            raw = "".join(chars)
            out = sanitize_tool_id(raw)
            seen.add(out)
        # With 1000 unique-ish inputs and 64-bit hash space, no collisions expected
        # Allow 1 collision as paranoia margin
        assert len(seen) >= 999

    def test_sanitized_output_format(self):
        """Verify sanitized output format is correct."""
        result = sanitize_tool_id("fc_a.b.c")

        # Format: sanitized_<16-hex-chars>
        assert result.startswith("sanitized_")
        hex_part = result[len("sanitized_"):]
        assert len(hex_part) == 16, f"Hex part should be 16 chars, got {len(hex_part)}: {hex_part!r}"
        assert all(c in string.hexdigits for c in hex_part), f"Hex part should be hex digits: {hex_part!r}"

    def test_tool_use_tool_result_pair_stays_consistent(self):
        """Same invalid id should sanitize to same value for paired use."""
        raw_id = "fc_a.b.c"
        sanitized_a = sanitize_tool_id(raw_id)
        sanitized_b = sanitize_tool_id(raw_id)
        assert sanitized_a == sanitized_b, "Same raw id should produce same sanitized id"
        assert _ANTHROPIC_TOOL_ID_RE.match(sanitized_a)

    def test_unicode_handling(self):
        """Unicode in ids should be handled gracefully."""
        # Unicode is invalid per the regex, should be sanitized
        unicode_ids = [
            "fc_日本語",
            "fc_emoji_🎉",
            "fc_café",
        ]
        for uid in unicode_ids:
            result = sanitize_tool_id(uid)
            assert result.startswith("sanitized_")
            assert _ANTHROPIC_TOOL_ID_RE.match(result)

    def test_sanitize_lone_surrogate_does_not_raise(self):
        """Lone surrogates should not crash sanitize_tool_id."""
        # \ud800 is a lone surrogate (invalid utf-8 on its own)
        result = sanitize_tool_id("\ud800")
        assert result.startswith("sanitized_")
        assert _ANTHROPIC_TOOL_ID_RE.match(result)

    def test_sanitize_null_byte(self):
        """Null bytes in ids should not crash sanitize_tool_id."""
        result = sanitize_tool_id("fc_a\x00b")
        assert result.startswith("sanitized_")
        assert _ANTHROPIC_TOOL_ID_RE.match(result)

    def test_sanitize_long_id_does_not_crash(self):
        """Very long ids should not crash sanitize_tool_id."""
        # Use an INVALID long id (contains '.') so it gets sanitized
        long_id = "fc_" + "a" * 100_000 + ".invalid"
        result = sanitize_tool_id(long_id)
        assert result.startswith("sanitized_")
        assert _ANTHROPIC_TOOL_ID_RE.match(result)
