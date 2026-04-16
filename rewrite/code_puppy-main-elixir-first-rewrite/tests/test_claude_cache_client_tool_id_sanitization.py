"""Tests for tool_id sanitization at the Claude cache client payload level."""

import copy

from code_puppy.claude_cache_client import (
    _sanitize_tool_ids_in_payload,
    _ANTHROPIC_TOOL_ID_RE,
)


class TestSanitizeToolIdsInPayload:
    """Tests for _sanitize_tool_ids_in_payload function."""

    def test_payload_with_invalid_tool_use_id_is_sanitized(self):
        """Build a minimal Anthropic-shaped payload with invalid tool_use id."""
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "Hello"}],
                },
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I'll help"},
                        {
                            "type": "tool_use",
                            "id": "fc_a.b.c",  # Invalid: contains dots
                            "name": "some_tool",
                            "input": {"arg": "value"},
                        },
                    ],
                },
            ],
        }

        changed = _sanitize_tool_ids_in_payload(payload)

        # Should report that it changed something
        assert changed is True

        # The tool_use id should now match the regex
        tool_use_block = payload["messages"][1]["content"][1]
        assert tool_use_block["type"] == "tool_use"
        assert _ANTHROPIC_TOOL_ID_RE.match(tool_use_block["id"])
        assert tool_use_block["id"].startswith("sanitized_")

    def test_tool_use_and_tool_result_pair_stay_consistent(self):
        """Payload with paired tool_use and tool_result should have matching ids after sanitization."""
        # This simulates a conversation history from OpenAI that goes to Claude
        raw_invalid_id = "fc_a.b"  # Contains dot, invalid for Anthropic

        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "Call tool"}],
                },
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": raw_invalid_id,
                            "name": "my_tool",
                            "input": {},
                        },
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": raw_invalid_id,  # Same invalid id
                            "content": "Result here",
                        },
                    ],
                },
            ],
        }

        changed = _sanitize_tool_ids_in_payload(payload)

        assert changed is True

        # Both tool_use and tool_result should now have the SAME sanitized id
        tool_use_id = payload["messages"][1]["content"][0]["id"]
        tool_result_id = payload["messages"][2]["content"][0]["tool_use_id"]

        assert tool_use_id == tool_result_id, (
            f"tool_use id ({tool_use_id!r}) should match tool_result id ({tool_result_id!r})"
        )
        assert _ANTHROPIC_TOOL_ID_RE.match(tool_use_id)
        assert _ANTHROPIC_TOOL_ID_RE.match(tool_result_id)

    def test_orphan_tool_result_is_still_sanitized(self):
        """A tool_result without a matching tool_use should still be sanitized."""
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "orphan.id.here",  # Invalid id
                            "content": "Orphan result",
                        },
                    ],
                },
            ],
        }

        changed = _sanitize_tool_ids_in_payload(payload)

        assert changed is True
        tool_result_id = payload["messages"][0]["content"][0]["tool_use_id"]
        assert _ANTHROPIC_TOOL_ID_RE.match(tool_result_id)
        assert tool_result_id.startswith("sanitized_")

    def test_valid_payload_is_untouched(self):
        """Payload with all-valid ids should return False and not mutate."""
        payload = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "valid_tool_id_123",  # Valid
                            "name": "my_tool",
                            "input": {},
                        },
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "valid_tool_id_123",  # Valid and matches
                            "content": "Result",
                        },
                    ],
                },
            ],
        }

        # Make a deep copy to compare later
        original = copy.deepcopy(payload)

        changed = _sanitize_tool_ids_in_payload(payload)

        assert changed is False
        assert payload == original, "Payload should be unchanged"

    def test_sanitization_is_idempotent_at_payload_level(self):
        """Running sanitizer twice should produce the same result as once."""
        payload = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "fc_a.b.c",  # Invalid
                            "name": "my_tool",
                            "input": {},
                        },
                    ],
                },
            ],
        }

        # First pass
        _sanitize_tool_ids_in_payload(payload)
        first_result = copy.deepcopy(payload)

        # Second pass
        changed = _sanitize_tool_ids_in_payload(payload)

        # Second pass should report no changes (already sanitized)
        assert changed is False
        assert payload == first_result, "Second pass should not change anything"

    def test_malformed_payload_does_not_crash(self):
        """Various malformed payloads should not raise exceptions."""
        malformed_cases = [
            {},  # Empty dict
            {"messages": "not a list"},  # messages is string
            {"messages": None},  # messages is None
            {"messages": [None, {}, {"content": "string"}]},  # Mixed bad entries
            {"messages": [{"content": None}]},  # content is None
            {"messages": [{"content": []}]},  # Empty content
            {"messages": [{"content": [{"type": "unknown"}]}]},  # Unknown block type
        ]

        for case in malformed_cases:
            # Should not raise
            result = _sanitize_tool_ids_in_payload(case)
            assert isinstance(result, bool), f"Should return bool for {case}"

    def test_mixed_valid_and_invalid_ids(self):
        """Payload with mix of valid and invalid ids."""
        payload = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "valid_id",  # Valid
                            "name": "tool_a",
                            "input": {},
                        },
                        {
                            "type": "tool_use",
                            "id": "fc_a.b",  # Invalid
                            "name": "tool_b",
                            "input": {},
                        },
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "valid_id",  # Valid
                            "content": "Good result",
                        },
                        {
                            "type": "tool_result",
                            "tool_use_id": "fc_a.b",  # Invalid
                            "content": "Bad result",
                        },
                    ],
                },
            ],
        }

        changed = _sanitize_tool_ids_in_payload(payload)

        assert changed is True

        # Valid ones should be unchanged
        assert payload["messages"][0]["content"][0]["id"] == "valid_id"
        assert payload["messages"][1]["content"][0]["tool_use_id"] == "valid_id"

        # Invalid ones should be sanitized
        assert _ANTHROPIC_TOOL_ID_RE.match(payload["messages"][0]["content"][1]["id"])
        assert _ANTHROPIC_TOOL_ID_RE.match(payload["messages"][1]["content"][1]["tool_use_id"])

        # But they should still match each other
        assert (payload["messages"][0]["content"][1]["id"] ==
                payload["messages"][1]["content"][1]["tool_use_id"])

    def test_nested_content_blocks(self):
        """Multiple content blocks per message."""
        payload = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I will use multiple tools"},
                        {
                            "type": "tool_use",
                            "id": "call.1",  # Invalid
                            "name": "tool1",
                            "input": {},
                        },
                        {
                            "type": "tool_use",
                            "id": "call.2",  # Invalid
                            "name": "tool2",
                            "input": {},
                        },
                        {"type": "text", "text": "Done calling"},
                    ],
                },
            ],
        }

        changed = _sanitize_tool_ids_in_payload(payload)

        assert changed is True
        content = payload["messages"][0]["content"]
        assert _ANTHROPIC_TOOL_ID_RE.match(content[1]["id"])
        assert _ANTHROPIC_TOOL_ID_RE.match(content[2]["id"])
        # The two tool ids should be different (different inputs)
        assert content[1]["id"] != content[2]["id"]

    def test_non_dict_messages_skipped(self):
        """Non-dict entries in messages list should be skipped."""
        payload = {
            "messages": [
                None,  # Not a dict
                "string message",  # Not a dict
                ["list"],  # Not a dict
                {  # Valid dict with invalid tool id
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "fc_a.b",
                            "name": "tool",
                            "input": {},
                        },
                    ],
                },
            ],
        }

        changed = _sanitize_tool_ids_in_payload(payload)

        assert changed is True
        tool_id = payload["messages"][3]["content"][0]["id"]
        assert _ANTHROPIC_TOOL_ID_RE.match(tool_id)

    def test_non_dict_content_blocks_skipped(self):
        """Non-dict entries in content list should be skipped."""
        payload = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        None,  # Not a dict
                        "string",  # Not a dict
                        ["list"],  # Not a dict
                        {  # Valid block with invalid tool id
                            "type": "tool_use",
                            "id": "fc_a.b",
                            "name": "tool",
                            "input": {},
                        },
                    ],
                },
            ],
        }

        changed = _sanitize_tool_ids_in_payload(payload)

        assert changed is True
        tool_id = payload["messages"][0]["content"][3]["id"]
        assert _ANTHROPIC_TOOL_ID_RE.match(tool_id)
