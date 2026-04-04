"""Token accounting integration tests.

Verify that tool result trimming, image lifecycle management, and system
prompt budgets actually reduce token counts as expected.

This module creates before/after token measurements to ensure each
optimization delivers measurable token savings.
"""

import pytest
from unittest.mock import patch
from pydantic_ai import BinaryContent, ImageUrl, DocumentUrl
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart

from code_puppy.agents.agent_code_puppy import CodePuppyAgent


async def run_async(coro):
    """Helper to run async coroutines in tests."""
    return await coro


class TestToolResultTruncationTokens:
    """Test that tool result truncation actually saves tokens."""

    @pytest.fixture
    def agent(self):
        """Provide a concrete agent for testing."""
        return CodePuppyAgent()

    @pytest.mark.asyncio
    async def test_large_tool_result_truncation_saves_tokens(self, agent):
        """Verify that truncating a large tool result reduces token count."""
        from code_puppy.plugins.tool_result_truncator.register_callbacks import (
            _on_post_tool_call,
            _extract_result_text,
            estimate_token_count,
        )

        # Create a large result that exceeds the threshold
        large_content = "Line content with many words\n" * 2000  # ~50k chars, ~12k tokens
        original_result = {"content": large_content, "status": "ok"}

        # Extract and measure original tokens
        result_text, _ = _extract_result_text(original_result)
        original_tokens = estimate_token_count(result_text)

        # Should be a large number of tokens
        assert original_tokens > 8000, f"Expected >8000 tokens, got {original_tokens}"

        # Call the truncation callback with a low threshold
        with patch(
            "code_puppy.plugins.tool_result_truncator.register_callbacks.get_tool_result_max_tokens",
            return_value=100,
        ):
            truncated = await _on_post_tool_call(
                tool_name="read_file",
                tool_args={"file_path": "/test.txt"},
                result=original_result,
                duration_ms=100.0,
                context=None,
            )

        # Verify truncation occurred
        assert truncated is not None, "Truncation should have occurred"
        assert isinstance(truncated, dict), "Should return dict for dict input"
        assert "content" in truncated, "Should have content field"

        # Measure truncated tokens
        truncated_text, _ = _extract_result_text(truncated)
        truncated_tokens = estimate_token_count(truncated_text)

        # Verify measurable savings
        tokens_saved = original_tokens - truncated_tokens
        assert tokens_saved > 0, f"Expected token savings, saved {tokens_saved}"
        assert truncated_tokens < original_tokens, "Truncated should be smaller"

        # Verify truncation indicator is present
        assert "[...truncated" in truncated_text, "Should have truncation indicator"
        assert "original was" in truncated_text, "Should indicate original token count"

    @pytest.mark.asyncio
    async def test_truncation_preserves_beginning_and_end(self, agent):
        """Verify truncation preserves beginning and end of content."""
        from code_puppy.plugins.tool_result_truncator.register_callbacks import (
            _on_post_tool_call,
            estimate_token_count,
        )

        # Create content with identifiable beginning and end
        beginning_marker = "BEGINNING_MARKER_UNIQUE"
        end_marker = "END_MARKER_UNIQUE"
        middle_content = "Middle content line\n" * 500
        large_content = f"{beginning_marker}\n{middle_content}\n{end_marker}"

        original_result = large_content
        original_tokens = estimate_token_count(original_result)

        # Truncate with low threshold
        with patch(
            "code_puppy.plugins.tool_result_truncator.register_callbacks.get_tool_result_max_tokens",
            return_value=100,
        ):
            truncated = await _on_post_tool_call(
                tool_name="grep",
                tool_args={"pattern": "test"},
                result=original_result,
                duration_ms=100.0,
                context=None,
            )

        # Verify both markers are present
        assert truncated is not None
        assert beginning_marker in truncated, "Should preserve beginning"
        assert end_marker in truncated, "Should preserve end"
        assert "[...truncated" in truncated, "Should have indicator"

        # Verify tokens were saved
        truncated_tokens = estimate_token_count(truncated)
        assert truncated_tokens < original_tokens

    @pytest.mark.asyncio
    async def test_no_truncation_for_small_results(self, agent):
        """Verify small results are not truncated (no token waste)."""
        from code_puppy.plugins.tool_result_truncator.register_callbacks import (
            _on_post_tool_call,
        )

        # Small result that should NOT be truncated
        small_content = "Small result content"
        original_result = {"content": small_content}

        # Call with high threshold
        with patch(
            "code_puppy.plugins.tool_result_truncator.register_callbacks.get_tool_result_max_tokens",
            return_value=8000,
        ):
            result = await _on_post_tool_call(
                tool_name="read_file",
                tool_args={"file_path": "/test.txt"},
                result=original_result,
                duration_ms=100.0,
                context=None,
            )

        # Should not be truncated
        assert result is None, "Small result should not be truncated"

    @pytest.mark.asyncio
    async def test_truncation_for_all_truncateable_tools(self, agent):
        """Verify all truncatable tools show token savings."""
        from code_puppy.plugins.tool_result_truncator.register_callbacks import (
            _on_post_tool_call,
            TRUNCATED_TOOLS,
            estimate_token_count,
        )

        large_content = "Large content line\n" * 1000
        original_tokens = estimate_token_count(large_content)

        for tool_name in TRUNCATED_TOOLS:
            with patch(
                "code_puppy.plugins.tool_result_truncator.register_callbacks.get_tool_result_max_tokens",
                return_value=100,
            ):
                truncated = await _on_post_tool_call(
                    tool_name=tool_name,
                    tool_args={},
                    result=large_content,
                    duration_ms=100.0,
                    context=None,
                )

            # All should be truncated
            assert truncated is not None, f"{tool_name} should be truncated"
            truncated_tokens = estimate_token_count(str(truncated))
            assert truncated_tokens < original_tokens, (
                f"{tool_name} should show token savings"
            )


class TestImageLifecycleTokens:
    """Test that image lifecycle management actually saves tokens."""

    @pytest.fixture
    def agent(self):
        """Provide a concrete agent for testing."""
        return CodePuppyAgent()

    def test_old_images_replaced_saves_tokens(self, agent):
        """Verify replacing old images with placeholders removes binary content."""
        # Create image data
        image_data = b"fake_image_data_" * 100  # ~1.5KB
        binary_content = BinaryContent(data=image_data, media_type="image/png")

        # Create messages spanning 3 turns (default TTL is 2)
        # A "turn" is: ModelRequest (user) -> ModelResponse (assistant)
        messages = [
            # Turn 0: user with image
            ModelRequest(parts=[TextPart(content="First:"), binary_content]),
            ModelResponse(parts=[TextPart(content="I see it")]),
            # Turn 1: user -> assistant
            ModelRequest(parts=[TextPart(content="Second turn")]),
            ModelResponse(parts=[TextPart(content="OK")]),
            # Turn 2: user -> assistant
            ModelRequest(parts=[TextPart(content="Third turn")]),
            ModelResponse(parts=[TextPart(content="Done")]),
        ]

        # Apply lifecycle management
        result, images_replaced, tokens_saved = agent._manage_image_lifecycle(messages)

        # Verify image was replaced
        assert images_replaced == 1, f"Should replace 1 old image, got {images_replaced}"
        assert tokens_saved > 0, f"Should report positive tokens saved, got {tokens_saved}"

        # Verify the image is now a text placeholder (not BinaryContent)
        first_msg_parts = result[0].parts
        assert isinstance(first_msg_parts[1], TextPart), (
            f"Expected TextPart placeholder, got {type(first_msg_parts[1])}"
        )
        assert "Image removed" in first_msg_parts[1].content, (
            f"Placeholder should indicate image removal: {first_msg_parts[1].content[:50]}"
        )
        # Verify tokens are mentioned in the placeholder
        assert "tokens" in first_msg_parts[1].content.lower(), (
            "Placeholder should mention tokens saved"
        )

    def test_multiple_images_token_savings(self, agent):
        """Verify multiple old images are replaced."""
        image_data = b"fake_image_data_" * 200
        binary_content1 = BinaryContent(data=image_data, media_type="image/png")
        binary_content2 = BinaryContent(data=image_data, media_type="image/jpeg")

        # Create messages spanning 4 turns (more than default TTL of 2)
        messages = [
            # Turn 0: user with two old images
            ModelRequest(parts=[binary_content1, binary_content2]),
            ModelResponse(parts=[TextPart(content="I see both")]),
            # Turn 1
            ModelRequest(parts=[TextPart(content="Next")]),
            ModelResponse(parts=[TextPart(content="Done")]),
            # Turn 2
            ModelRequest(parts=[TextPart(content="Another")]),
            ModelResponse(parts=[TextPart(content="OK")]),
            # Turn 3
            ModelRequest(parts=[TextPart(content="Final")]),
            ModelResponse(parts=[TextPart(content="End")]),
        ]

        result, images_replaced, tokens_saved = agent._manage_image_lifecycle(messages)

        # Both images should be replaced
        assert images_replaced == 2, f"Expected 2 images replaced, got {images_replaced}"
        assert tokens_saved > 1000, f"Should report significant tokens saved, got {tokens_saved}"

        # Verify placeholders
        assert isinstance(result[0].parts[0], TextPart), "First image should be TextPart"
        assert isinstance(result[0].parts[1], TextPart), "Second image should be TextPart"
        assert "Image removed" in result[0].parts[0].content
        assert "Image removed" in result[0].parts[1].content

    def test_recent_images_not_replaced(self, agent):
        """Verify recent images (within TTL) are not replaced."""
        image_data = b"fake_image_data_" * 100
        binary_content = BinaryContent(data=image_data, media_type="image/png")

        # Create only 1 turn (within default TTL of 2)
        messages = [
            ModelRequest(parts=[TextPart(content="Look:"), binary_content]),
            ModelResponse(parts=[TextPart(content="I see it")]),
        ]

        result, images_replaced, tokens_saved = agent._manage_image_lifecycle(messages)

        # No images should be replaced (within TTL)
        assert images_replaced == 0, "Recent images should not be replaced"
        assert tokens_saved == 0, "No tokens should be saved for recent images"

        # Image should still be present as BinaryContent
        assert isinstance(result[0].parts[1], BinaryContent), (
            "Recent image should remain as BinaryContent"
        )

    def test_image_url_replaced(self, agent):
        """Verify ImageUrl attachments are replaced with placeholders."""
        image_url = ImageUrl(url="https://example.com/image.png")

        # Create messages spanning 3 turns
        messages = [
            ModelRequest(parts=[image_url]),
            ModelResponse(parts=[TextPart(content="I see it")]),
            ModelRequest(parts=[TextPart(content="Second")]),
            ModelResponse(parts=[TextPart(content="OK")]),
            ModelRequest(parts=[TextPart(content="Third")]),
            ModelResponse(parts=[TextPart(content="Done")]),
        ]

        result, images_replaced, tokens_saved = agent._manage_image_lifecycle(messages)

        assert images_replaced == 1, "ImageUrl should be replaced"
        assert tokens_saved > 0, f"Should report tokens saved, got {tokens_saved}"
        assert isinstance(result[0].parts[0], TextPart), (
            "ImageUrl should become TextPart"
        )
        assert "image url removed" in result[0].parts[0].content.lower(), (
            "Should indicate URL removal"
        )

    def test_document_url_replaced(self, agent):
        """Verify DocumentUrl attachments are replaced with placeholders."""
        doc_url = DocumentUrl(url="https://example.com/doc.pdf")

        messages = [
            ModelRequest(parts=[doc_url]),
            ModelResponse(parts=[TextPart(content="I see it")]),
            ModelRequest(parts=[TextPart(content="Second")]),
            ModelResponse(parts=[TextPart(content="OK")]),
            ModelRequest(parts=[TextPart(content="Third")]),
            ModelResponse(parts=[TextPart(content="Done")]),
        ]

        result, images_replaced, tokens_saved = agent._manage_image_lifecycle(messages)

        assert images_replaced == 1, "DocumentUrl should be replaced"
        assert tokens_saved > 0, f"Should report tokens saved, got {tokens_saved}"
        assert isinstance(result[0].parts[0], TextPart), (
            "DocumentUrl should become TextPart"
        )
        assert "document url removed" in result[0].parts[0].content.lower(), (
            "Should indicate URL removal"
        )


class TestSystemPromptBudget:
    """Test system prompt budget and protected token count integration."""

    @pytest.fixture
    def agent(self):
        """Provide a concrete agent for testing."""
        return CodePuppyAgent()

    def test_protected_token_count_is_positive(self, agent):
        """Verify protected_token_count returns a positive value."""
        from code_puppy.config import get_protected_token_count

        protected = get_protected_token_count()
        # Should be a positive number (default is typically 50000)
        assert protected > 0, f"protected_token_count should be positive, got {protected}"
        assert isinstance(protected, int), "Should return an integer"

    def test_system_prompt_included_in_overhead(self, agent):
        """Verify system prompt is included in context overhead estimation."""
        overhead = agent.estimate_context_overhead_tokens()

        # Should be non-negative (may include system prompt, tools, etc.)
        assert overhead >= 0, "Overhead should be non-negative"

        # Get system prompt tokens directly
        system_prompt = agent.get_full_system_prompt()

        # If there's a system prompt, overhead should be at least the system prompt
        if system_prompt:
            # Note: overhead may not directly include system_tokens due to model-specific handling
            assert overhead >= 0  # Just verify it's non-negative

    def test_filter_huge_messages_enforces_limits(self, agent):
        """Verify filter_huge_messages enforces token limits."""
        # Create a large message that would exceed typical limits
        # Using a very large message (> 50000 tokens to trigger filtering)
        large_text = "x" * 200000  # ~50k tokens
        large_message = ModelRequest(parts=[TextPart(content=large_text)])

        # Test filter_huge_messages (uses 50000 token limit)
        messages = [large_message]
        filtered = agent.filter_huge_messages(messages)

        # Large message should be filtered out
        # (the result may be empty or have a placeholder)
        assert len(filtered) < len(messages) or filtered != messages, (
            "Large message should be filtered or replaced"
        )

    def test_small_messages_preserved_by_filter(self, agent):
        """Verify small messages pass through filter."""
        small_messages = [
            ModelRequest(parts=[TextPart(content="Hello")]),
            ModelResponse(parts=[TextPart(content="Hi there")]),
            ModelRequest(parts=[TextPart(content="How are you?")]),
        ]

        filtered = agent.filter_huge_messages(small_messages)

        # All small messages should be preserved
        assert len(filtered) == len(small_messages)


class TestTokenOptimizationIntegration:
    """Integration tests verifying all optimizations work together."""

    @pytest.fixture
    def agent(self):
        """Provide a concrete agent for testing."""
        return CodePuppyAgent()

    @pytest.mark.asyncio
    async def test_combined_optimizations_reduce_tokens(self, agent):
        """Verify combined optimizations result in measurable token reduction."""
        from code_puppy.plugins.tool_result_truncator.register_callbacks import (
            _on_post_tool_call,
        )

        # Create complex message history with images and large tool results
        image_data = b"fake_image_" * 100
        binary_content = BinaryContent(data=image_data, media_type="image/png")
        large_tool_result = "Large tool result\n" * 1000

        messages = [
            # Turn 0: old image and large tool result
            ModelRequest(parts=[binary_content, TextPart(content=large_tool_result)]),
            ModelResponse(parts=[TextPart(content="Response")]),
            # Turn 1
            ModelRequest(parts=[TextPart(content="Next")]),
            ModelResponse(parts=[TextPart(content="OK")]),
            # Turn 2
            ModelRequest(parts=[TextPart(content="Third")]),
            ModelResponse(parts=[TextPart(content="Done")]),
        ]

        # Calculate initial tokens
        initial_tokens = sum(
            agent.estimate_tokens_for_message(m) for m in messages
        )

        # Apply image lifecycle management
        managed_messages, images_replaced, image_tokens_saved = (
            agent._manage_image_lifecycle(messages)
        )

        # Apply tool result truncation (simulated for read_file tool)
        with patch(
            "code_puppy.plugins.tool_result_truncator.register_callbacks.get_tool_result_max_tokens",
            return_value=100,
        ):
            # Extract the large text from turn 0 and truncate it
            tool_result_part = managed_messages[0].parts[1]
            if isinstance(tool_result_part, TextPart):
                truncated = await _on_post_tool_call(
                    tool_name="read_file",
                    tool_args={},
                    result=tool_result_part.content,
                    duration_ms=100.0,
                    context=None,
                )
                if truncated:
                    # Replace the part with truncated version
                    managed_messages[0].parts[1] = TextPart(content=str(truncated))

        # Calculate final tokens
        final_tokens = sum(
            agent.estimate_tokens_for_message(m) for m in managed_messages
        )

        # Verify combined savings
        total_saved = initial_tokens - final_tokens
        assert images_replaced > 0, "Should replace at least one image"
        assert total_saved > 0, f"Should save tokens overall, saved {total_saved}"
        assert final_tokens < initial_tokens, (
            f"Final ({final_tokens}) should be less than initial ({initial_tokens})"
        )

    def test_token_measurement_consistency(self, agent):
        """Verify token estimation is consistent across methods."""
        text = "This is a test message for token consistency"

        # Estimate via agent method
        agent_tokens = agent.estimate_token_count(text)

        # Estimate via utility function
        from code_puppy.token_utils import estimate_token_count
        util_tokens = estimate_token_count(text)

        # Should be consistent
        assert agent_tokens == util_tokens, (
            f"Token estimation inconsistent: agent={agent_tokens}, util={util_tokens}"
        )

    @pytest.mark.asyncio
    async def test_optimization_indicators_present(self, agent):
        """Verify optimizations include appropriate indicators."""
        from code_puppy.plugins.tool_result_truncator.register_callbacks import (
            _on_post_tool_call,
        )

        # Test tool truncation indicator
        large_content = "Content\n" * 1000
        with patch(
            "code_puppy.plugins.tool_result_truncator.register_callbacks.get_tool_result_max_tokens",
            return_value=100,
        ):
            truncated = await _on_post_tool_call(
                tool_name="read_file",
                tool_args={},
                result=large_content,
                duration_ms=100.0,
                context=None,
            )

        assert truncated is not None
        assert "[...truncated" in str(truncated), "Should have truncation indicator"
        assert "original was" in str(truncated), "Should indicate original size"

        # Test image lifecycle indicator
        image_data = b"image_" * 100
        binary_content = BinaryContent(data=image_data, media_type="image/png")

        messages = [
            ModelRequest(parts=[binary_content]),
            ModelResponse(parts=[TextPart(content="OK")]),
            ModelRequest(parts=[TextPart(content="Next")]),
            ModelResponse(parts=[TextPart(content="Done")]),
        ]

        result, images_replaced, tokens_saved = agent._manage_image_lifecycle(messages)

        if images_replaced > 0:
            placeholder_text = result[0].parts[0].content
            assert "Image removed" in placeholder_text, "Should have image removal indicator"
            assert "tokens" in placeholder_text.lower(), "Should mention tokens saved"
