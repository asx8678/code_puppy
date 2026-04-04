"""Tests for image/attachment lifecycle management."""

import pytest
from pydantic_ai import BinaryContent, ImageUrl, DocumentUrl
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart

from code_puppy.agents.base_agent import BaseAgent


class ConcreteTestAgent(BaseAgent):
    """A concrete test agent class for testing image lifecycle."""

    @property
    def name(self) -> str:
        return "test-agent"

    @property
    def display_name(self) -> str:
        return "Test Agent"

    @property
    def description(self) -> str:
        return "A test agent"

    def get_system_prompt(self) -> str:
        return "You are a test agent."

    def get_available_tools(self) -> list:
        return []

    async def run(self, prompt: str, **kwargs):
        pass


@pytest.fixture
def agent():
    return ConcreteTestAgent()


class TestImageLifecycleManagement:
    """Tests for the _manage_image_lifecycle method."""

    def test_no_images_returns_unchanged(self, agent):
        """Test that messages without images are returned unchanged."""
        messages = [
            ModelRequest(parts=[TextPart(content="Hello")]),
            ModelResponse(parts=[TextPart(content="Hi there")]),
            ModelRequest(parts=[TextPart(content="How are you?")]),
        ]

        result, images_replaced, tokens_saved = agent._manage_image_lifecycle(messages)

        assert len(result) == 3
        assert images_replaced == 0
        assert tokens_saved == 0
        # Messages should be unchanged
        for i, msg in enumerate(result):
            assert isinstance(msg, type(messages[i]))

    def test_images_within_ttl_not_replaced(self, agent):
        """Test that images within TTL are not replaced."""
        # Create a simple image binary
        image_data = b"fake_image_data_" * 100  # ~1.5KB
        binary_content = BinaryContent(data=image_data, media_type="image/png")

        # Create messages: 1 turn (user with image -> assistant response)
        messages = [
            ModelRequest(parts=[TextPart(content="Look at this:"), binary_content]),
            ModelResponse(parts=[TextPart(content="I see the image")]),
        ]

        result, images_replaced, tokens_saved = agent._manage_image_lifecycle(messages)

        # Both messages are within TTL (turn 0), images should NOT be replaced
        assert images_replaced == 0
        assert tokens_saved == 0
        assert len(result) == 2

        # Verify the image is still there
        assert isinstance(result[0].parts[1], BinaryContent)

    def test_images_after_ttl_replaced_with_placeholder(self, agent):
        """Test that images older than TTL are replaced with placeholders."""
        # Create image data
        image_data = b"fake_image_data_" * 100  # ~1.5KB
        binary_content = BinaryContent(data=image_data, media_type="image/png")

        # Create messages spanning 3 turns (more than default TTL of 2)
        messages = [
            # Turn 0: user with image
            ModelRequest(parts=[TextPart(content="First image:"), binary_content]),
            ModelResponse(parts=[TextPart(content="I see it")]),
            # Turn 1: user message
            ModelRequest(parts=[TextPart(content="What about this?")]),
            ModelResponse(parts=[TextPart(content="Got it")]),
            # Turn 2: user message
            ModelRequest(parts=[TextPart(content="And this?")]),
            ModelResponse(parts=[TextPart(content="Yes")]),
        ]

        result, images_replaced, tokens_saved = agent._manage_image_lifecycle(messages)

        # The first image should be replaced (it's from turn 0, which is >= TTL of 2)
        assert images_replaced == 1
        assert tokens_saved > 0
        assert len(result) == 6

        # Verify the first image is now a TextPart placeholder
        first_msg_parts = result[0].parts
        assert isinstance(first_msg_parts[1], TextPart)
        assert "Image removed" in first_msg_parts[1].content
        assert "turns ago" in first_msg_parts[1].content

    def test_multiple_images_replaced(self, agent):
        """Test that multiple old images are all replaced."""
        image_data = b"fake_image_data_" * 200
        binary_content1 = BinaryContent(data=image_data, media_type="image/png")
        binary_content2 = BinaryContent(data=image_data, media_type="image/jpeg")

        # Create messages spanning 4 turns
        messages = [
            # Turn 0: user with two images
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

        # Both images should be replaced (from turn 0, TTL is 2)
        assert images_replaced == 2
        assert len(result[0].parts) == 2
        assert isinstance(result[0].parts[0], TextPart)
        assert isinstance(result[0].parts[1], TextPart)
        assert "Image removed" in result[0].parts[0].content
        assert "Image removed" in result[0].parts[1].content

    def test_image_url_replaced(self, agent):
        """Test that ImageUrl attachments are also replaced."""
        image_url = ImageUrl(url="https://example.com/image.png")

        # Create messages spanning 3 turns
        messages = [
            ModelRequest(parts=[image_url]),
            ModelResponse(parts=[TextPart(content="I see it")]),
            ModelRequest(parts=[TextPart(content="Second turn")]),
            ModelResponse(parts=[TextPart(content="OK")]),
            ModelRequest(parts=[TextPart(content="Third turn")]),
            ModelResponse(parts=[TextPart(content="Done")]),
        ]

        result, images_replaced, tokens_saved = agent._manage_image_lifecycle(messages)

        assert images_replaced == 1
        assert isinstance(result[0].parts[0], TextPart)
        assert "image url removed" in result[0].parts[0].content.lower()

    def test_document_url_replaced(self, agent):
        """Test that DocumentUrl attachments are also replaced."""
        doc_url = DocumentUrl(url="https://example.com/doc.pdf")

        # Create messages spanning 3 turns
        messages = [
            ModelRequest(parts=[doc_url]),
            ModelResponse(parts=[TextPart(content="I see it")]),
            ModelRequest(parts=[TextPart(content="Second turn")]),
            ModelResponse(parts=[TextPart(content="OK")]),
            ModelRequest(parts=[TextPart(content="Third turn")]),
            ModelResponse(parts=[TextPart(content="Done")]),
        ]

        result, images_replaced, tokens_saved = agent._manage_image_lifecycle(messages)

        assert images_replaced == 1
        assert isinstance(result[0].parts[0], TextPart)
        assert "document url removed" in result[0].parts[0].content.lower()

    def test_mixed_content_partial_replacement(self, agent):
        """Test that only old images are replaced, new ones are kept."""
        old_image = BinaryContent(data=b"old_image_data_" * 100, media_type="image/png")
        new_image = BinaryContent(data=b"new_image_data_" * 100, media_type="image/png")

        # Create messages spanning 3 turns with images in turn 0 and turn 2
        messages = [
            # Turn 0: old image
            ModelRequest(parts=[old_image]),
            ModelResponse(parts=[TextPart(content="I see old image")]),
            # Turn 1
            ModelRequest(parts=[TextPart(content="Middle")]),
            ModelResponse(parts=[TextPart(content="Middle response")]),
            # Turn 2: new image (within TTL since it's the current turn)
            ModelRequest(parts=[new_image]),
            ModelResponse(parts=[TextPart(content="I see new image")]),
        ]

        result, images_replaced, tokens_saved = agent._manage_image_lifecycle(messages)

        # Only the old image should be replaced
        assert images_replaced == 1
        # Turn 0 image replaced
        assert isinstance(result[0].parts[0], TextPart)
        assert "Image removed" in result[0].parts[0].content
        # Turn 2 image kept
        assert isinstance(result[4].parts[0], BinaryContent)

    def test_empty_messages(self, agent):
        """Test that empty messages are handled gracefully."""
        result, images_replaced, tokens_saved = agent._manage_image_lifecycle([])

        assert result == []
        assert images_replaced == 0
        assert tokens_saved == 0

    def test_token_estimate_bounds(self, agent):
        """Test that token estimates are within reasonable bounds."""
        # Small image (should get minimum 1000 tokens)
        small_image = BinaryContent(data=b"x" * 500, media_type="image/png")
        # Large image (should get maximum 5000 tokens)
        large_image = BinaryContent(data=b"x" * 1000000, media_type="image/png")

        messages = [
            ModelRequest(parts=[small_image]),
            ModelResponse(parts=[TextPart(content="Small")]),
            ModelRequest(parts=[TextPart(content="Next")]),
            ModelResponse(parts=[TextPart(content="Next response")]),
            ModelRequest(parts=[TextPart(content="Third")]),
            ModelResponse(parts=[TextPart(content="Third response")]),
        ]

        result, images_replaced, tokens_saved = agent._manage_image_lifecycle(messages)

        # Small image should be estimated at 1000 tokens minimum
        assert tokens_saved >= 1000
        # Large image estimate should not exceed 5000 per image
        assert tokens_saved <= 5000


class TestConfigIntegration:
    """Tests for config integration with image lifecycle."""

    def test_get_image_ttl_turns_default(self, monkeypatch):
        """Test that default image_ttl_turns is 2."""
        from code_puppy.config import get_image_ttl_turns, get_value

        # Ensure no config value is set
        monkeypatch.setattr(
            "code_puppy.config.get_value", lambda key: None if key == "image_ttl_turns" else get_value(key)
        )

        result = get_image_ttl_turns()
        assert result == 2

    def test_get_image_ttl_turns_custom(self, monkeypatch):
        """Test that custom image_ttl_turns value is respected."""
        from code_puppy.config import get_image_ttl_turns

        monkeypatch.setattr(
            "code_puppy.config.get_value", lambda key: "5" if key == "image_ttl_turns" else None
        )

        result = get_image_ttl_turns()
        assert result == 5

    def test_get_image_ttl_turns_clamped(self, monkeypatch):
        """Test that image_ttl_turns is clamped between 1 and 10."""
        from code_puppy.config import get_image_ttl_turns

        # Test upper bound
        monkeypatch.setattr(
            "code_puppy.config.get_value", lambda key: "20" if key == "image_ttl_turns" else None
        )
        assert get_image_ttl_turns() == 10

        # Test lower bound
        monkeypatch.setattr(
            "code_puppy.config.get_value", lambda key: "0" if key == "image_ttl_turns" else None
        )
        assert get_image_ttl_turns() == 1

        # Test negative
        monkeypatch.setattr(
            "code_puppy.config.get_value", lambda key: "-5" if key == "image_ttl_turns" else None
        )
        assert get_image_ttl_turns() == 1

    def test_get_image_ttl_turns_invalid(self, monkeypatch):
        """Test that invalid image_ttl_turns falls back to default."""
        from code_puppy.config import get_image_ttl_turns

        monkeypatch.setattr(
            "code_puppy.config.get_value", lambda key: "invalid" if key == "image_ttl_turns" else None
        )

        result = get_image_ttl_turns()
        assert result == 2

    def test_config_key_in_list(self):
        """Test that image_ttl_turns is in the config keys list."""
        from code_puppy.config import get_config_keys

        keys = get_config_keys()
        assert "image_ttl_turns" in keys
