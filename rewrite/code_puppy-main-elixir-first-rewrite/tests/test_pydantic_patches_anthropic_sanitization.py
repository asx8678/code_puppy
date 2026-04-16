"""Tests for Anthropic tool id sanitization patch in pydantic_patches.py."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

from code_puppy.claude_cache_client import _ANTHROPIC_TOOL_ID_RE


class TestPydanticAnthropicSanitization:
    """Tests for the Anthropic tool id sanitization patch."""

    def test_patch_sanitizes_messages_for_request(self):
        """Verify that the patch sanitizes tool_call_ids in request()."""
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.messages import ToolCallPart, ModelResponse

        # Build a list to capture messages from the fake
        captured = []

        async def fake_original_request(self, messages, model_settings, model_request_parameters):
            captured.append(messages)
            return MagicMock()

        # Store the real method (which may already be patched)
        current_request = AnthropicModel.request

        # Temporarily restore to our fake
        AnthropicModel.request = fake_original_request

        # Re-apply the patch (it will wrap our fake)
        from code_puppy.pydantic_patches import patch_anthropic_tool_id_sanitization
        patch_anthropic_tool_id_sanitization()

        try:
            model = MagicMock(spec=AnthropicModel)
            original_id = "fc_a.b.c"
            part = ToolCallPart(tool_name="test_tool", args={"arg": "value"}, tool_call_id=original_id)
            original_messages = [ModelResponse(parts=[part])]

            async def run_test():
                # Call through the model mock which routes to the patched method
                await AnthropicModel.request(model, original_messages, None, MagicMock())

            asyncio.run(run_test())

            # Verify the original message was NOT mutated
            assert original_messages[0].parts[0].tool_call_id == original_id

            # But the messages passed to the fake HAD sanitized ids
            assert len(captured) == 1
            assert captured[0][0].parts[0].tool_call_id != original_id
            assert captured[0][0].parts[0].tool_call_id.startswith("sanitized_")
            assert _ANTHROPIC_TOOL_ID_RE.match(captured[0][0].parts[0].tool_call_id)
        finally:
            AnthropicModel.request = current_request

    def test_patch_sanitizes_messages_for_request_stream(self):
        """Verify that the patch sanitizes tool_call_ids in request_stream()."""
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.messages import ToolCallPart, ModelResponse

        captured = []

        @asynccontextmanager
        async def fake_original_request_stream(self, messages, model_settings, model_request_parameters, run_context=None):
            captured.append(messages)
            yield MagicMock()

        current_request_stream = AnthropicModel.request_stream

        # Replace with our fake original and re-apply patch
        AnthropicModel.request_stream = fake_original_request_stream

        from code_puppy.pydantic_patches import patch_anthropic_tool_id_sanitization
        patch_anthropic_tool_id_sanitization()

        try:
            model = MagicMock(spec=AnthropicModel)
            part = ToolCallPart(tool_name="test_tool", args={"arg": "value"}, tool_call_id="fc_a.b.c")
            messages = [ModelResponse(parts=[part])]

            async def run_test():
                # This should work without TypeError (async context manager)
                async with AnthropicModel.request_stream(model, messages, None, MagicMock(), None):
                    pass

            asyncio.run(run_test())

            # Verify the messages passed to the fake had sanitized ids
            assert len(captured) == 1
            assert captured[0][0].parts[0].tool_call_id != "fc_a.b.c"
            assert captured[0][0].parts[0].tool_call_id.startswith("sanitized_")
            assert _ANTHROPIC_TOOL_ID_RE.match(captured[0][0].parts[0].tool_call_id)
        finally:
            AnthropicModel.request_stream = current_request_stream

    def test_patch_uses_isinstance_not_hasattr(self):
        """Verify that TextPart (no tool_call_id) is skipped and ToolCallPart is sanitized."""
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.messages import ToolCallPart, TextPart, ModelResponse

        captured = []

        async def fake_original_request(self, messages, model_settings, model_request_parameters):
            captured.append(messages)
            return MagicMock()

        current_request = AnthropicModel.request

        AnthropicModel.request = fake_original_request

        from code_puppy.pydantic_patches import patch_anthropic_tool_id_sanitization
        patch_anthropic_tool_id_sanitization()

        try:
            model = MagicMock(spec=AnthropicModel)

            # Mix of TextPart (should be untouched) and ToolCallPart (should be sanitized)
            text_part = TextPart(content="Hello world")
            tool_part = ToolCallPart(tool_name="test_tool", args={"arg": "value"}, tool_call_id="fc_a.b.c")
            original_messages = [ModelResponse(parts=[text_part, tool_part])]

            async def run_test():
                await AnthropicModel.request(model, original_messages, None, MagicMock())

            asyncio.run(run_test())

            # Verify no AttributeError was raised on TextPart
            assert len(captured) == 1
            # TextPart should be unchanged
            assert captured[0][0].parts[0].content == "Hello world"
            # ToolCallPart should have sanitized id
            assert captured[0][0].parts[1].tool_call_id.startswith("sanitized_")
            assert _ANTHROPIC_TOOL_ID_RE.match(captured[0][0].parts[1].tool_call_id)
        finally:
            AnthropicModel.request = current_request

    def test_retry_prompt_part_sanitized(self):
        """Verify RetryPromptPart is also sanitized (it has tool_call_id too)."""
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.messages import RetryPromptPart, ModelRequest

        captured = []

        async def fake_original_request(self, messages, model_settings, model_request_parameters):
            captured.append(messages)
            return MagicMock()

        current_request = AnthropicModel.request

        AnthropicModel.request = fake_original_request

        from code_puppy.pydantic_patches import patch_anthropic_tool_id_sanitization
        patch_anthropic_tool_id_sanitization()

        try:
            model = MagicMock(spec=AnthropicModel)

            retry_part = RetryPromptPart(
                tool_name="test_tool",
                tool_call_id="retry.id.here",  # Invalid for Anthropic
                content="Please retry",  # field is 'content' not 'message'
            )
            original_messages = [ModelRequest(parts=[retry_part])]

            async def run_test():
                await AnthropicModel.request(model, original_messages, None, MagicMock())

            asyncio.run(run_test())

            # Verify the retry part was sanitized
            assert len(captured) == 1
            assert captured[0][0].parts[0].tool_call_id.startswith("sanitized_")
            assert _ANTHROPIC_TOOL_ID_RE.match(captured[0][0].parts[0].tool_call_id)
        finally:
            AnthropicModel.request = current_request
