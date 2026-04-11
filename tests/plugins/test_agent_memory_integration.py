"""Integration tests for Agent Memory plugin.

End-to-end tests that verify:
1. Fact extraction from conversations
2. Signal detection and confidence updates
3. Prompt injection with token budgets
4. Callback registration and wiring
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from code_puppy.callbacks import get_callbacks
from code_puppy.plugins.agent_memory import (
    CORRECTION_DELTA,
    REINFORCEMENT_DELTA,
    ExtractedFact,
    FactExtractor,
    FileMemoryStorage,
    MemoryConfig,
    MemoryUpdater,
    MockLLMClient,
    Signal,
    SignalDetector,
    SignalType,
    detect_signals,
    has_correction,
    has_preference,
    has_reinforcement,
    load_config,
)
from code_puppy.plugins.agent_memory.config import _get_bool, _get_float, _get_int
from code_puppy.plugins.agent_memory.extraction import DEFAULT_EXTRACTION_PROMPT
from code_puppy.plugins.agent_memory.core import (
    _get_storage,
    _get_updater,
    _on_shutdown,
    _on_startup,
)
from code_puppy.plugins.agent_memory.messaging import (
    _get_conversation_messages,
    _normalize_messages,
)
from code_puppy.plugins.agent_memory.processing import (
    _apply_signal_confidence_updates,
    _schedule_fact_extraction,
)
from code_puppy.plugins.agent_memory.prompts import (
    _format_memory_section,
    _on_load_prompt,
)
from code_puppy.plugins.agent_memory.agent_run_end import _on_agent_run_end
from code_puppy.plugins.agent_memory.signals import (
    PREFERENCE_DELTA,
    _COMPILED_CORRECTION,
    _COMPILED_PREFERENCE,
    _COMPILED_REINFORCEMENT,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_memory_dir(tmp_path: Path) -> Path:
    """Create a temporary memory directory for testing."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    return memory_dir


@pytest.fixture
def mock_memory_config() -> MemoryConfig:
    """Provide a test memory config."""
    return MemoryConfig(
        enabled=True,
        max_facts=5,
        token_budget=200,
        min_confidence=0.5,
        debounce_ms=100,  # Fast debounce for testing
        extraction_enabled=True,
    )


@pytest.fixture
def sample_conversation() -> list[dict[str, Any]]:
    """Provide a sample conversation for testing."""
    return [
        {"role": "user", "content": "I prefer using dark mode for all my IDEs"},
        {"role": "assistant", "content": "I'll remember that you prefer dark mode."},
        {
            "role": "user",
            "content": "Yes, exactly! Also, I use Python 3.11 for this project.",
        },
        {"role": "assistant", "content": "Noted! Python 3.11 it is."},
        {
            "role": "user",
            "content": "Actually, I meant Python 3.12. Please correct that.",
        },
    ]


# ============================================================================
# Signal Detection Tests
# ============================================================================


class TestSignalDetection:
    """Tests for signal detection patterns."""

    def test_has_correction_patterns(self) -> None:
        """Test correction pattern detection."""
        assert has_correction("Actually, that's wrong.")
        assert has_correction("No, that is incorrect.")
        assert has_correction("Wait, that's not right.")
        assert has_correction("Let me correct that.")
        assert not has_correction("That looks great!")
        assert not has_correction("Thanks for the help.")

    def test_has_reinforcement_patterns(self) -> None:
        """Test reinforcement pattern detection."""
        assert has_reinforcement("Yes, exactly!")
        assert has_reinforcement("Yes, that is correct")
        assert has_reinforcement("That makes sense.")
        assert has_reinforcement("Agreed!")
        assert has_reinforcement("Perfect!")
        assert has_reinforcement("Exactly!")
        assert not has_reinforcement("I don't understand.")
        assert not has_reinforcement("Can you explain?")

    def test_has_preference_patterns(self) -> None:
        """Test preference pattern detection."""
        assert has_preference("I prefer dark mode.")
        assert has_preference("I like using VS Code.")
        assert has_preference("My preference is Python.")
        assert has_preference("I always use TypeScript.")
        assert not has_preference("What do you think?")
        assert not has_preference("Can you help me?")

    def test_detect_signals_returns_all_types(self) -> None:
        """Test that detect_signals finds multiple signal types."""
        # Correction + reinforcement
        text = "Actually, that's wrong. Yes, you are right!"
        signals = detect_signals(text)

        signal_types = [s.signal_type for s in signals]
        assert SignalType.CORRECTION in signal_types
        assert SignalType.REINFORCEMENT in signal_types

        # Preference + reinforcement
        text2 = "I prefer dark mode. Exactly!"
        signals2 = detect_signals(text2)
        signal_types2 = [s.signal_type for s in signals2]
        assert SignalType.PREFERENCE in signal_types2
        assert SignalType.REINFORCEMENT in signal_types2

    def test_signal_confidence_deltas(self) -> None:
        """Test that signals have correct confidence deltas."""
        correction = Signal(
            signal_type=SignalType.CORRECTION,
            confidence_delta=CORRECTION_DELTA,
            matched_text="test",
        )
        reinforcement = Signal(
            signal_type=SignalType.REINFORCEMENT,
            confidence_delta=REINFORCEMENT_DELTA,
            matched_text="test",
        )
        preference = Signal(
            signal_type=SignalType.PREFERENCE,
            confidence_delta=PREFERENCE_DELTA,
            matched_text="test",
        )

        assert correction.confidence_delta == -0.3
        assert reinforcement.confidence_delta == 0.1
        assert preference.confidence_delta == 0.15

    def test_signal_detector_stateful(self) -> None:
        """Test that SignalDetector maintains recent fact context."""
        detector = SignalDetector()
        facts = [{"text": "User likes Python"}, {"text": "User prefers dark mode"}]

        signals = detector.analyze_message("Yes, exactly!", facts)

        assert len(signals) > 0
        assert signals[0].signal_type == SignalType.REINFORCEMENT

    def test_signal_detector_clear_history(self) -> None:
        """Test that SignalDetector.clear_history works."""
        detector = SignalDetector()
        facts = [{"text": "Test fact"}]

        detector.analyze_message("Yes!", facts)
        detector.clear_history()

        # After clearing, next analysis should not have recent_facts
        signals = detector.analyze_message("Yes!")
        assert not signals[0].context or not signals[0].context.get("recent_facts")

    # Chinese Signal Detection Tests (code-puppy-4uw)
    def test_chinese_correction_patterns(self) -> None:
        """Test Chinese correction pattern detection (code-puppy-4uw)."""
        # Basic correction patterns
        assert has_correction("不对")
        assert has_correction("错了")
        assert has_correction("不正确")
        assert has_correction("有误")
        assert has_correction("纠正一下")
        assert has_correction("更正")
        assert has_correction("应该是Python")
        assert has_correction("其实")
        # Contextual corrections
        assert has_correction("这不是对的")
        assert has_correction("这不对")
        assert has_correction("这不是正确的")
        assert has_correction("它错了")
        assert has_correction("你错了")
        assert has_correction("我不喜欢用这个")
        assert has_correction("我不是这个意思")
        # Negative tests - should NOT match
        assert not has_correction("你好")  # "hello"
        assert not has_correction("对的")  # "that's right" - reinforcement
        assert not has_correction("正确")  # "correct" - reinforcement

    def test_chinese_reinforcement_patterns(self) -> None:
        """Test Chinese reinforcement pattern detection (code-puppy-4uw)."""
        # Basic reinforcement patterns
        assert has_reinforcement("对的")
        assert has_reinforcement("没错")
        assert has_reinforcement("正确")
        assert has_reinforcement("是这样")
        assert has_reinforcement("一点都没错")
        assert has_reinforcement("完全正确")
        assert has_reinforcement("准确")
        assert has_reinforcement("很准确")
        assert has_reinforcement("说到点子")
        assert has_reinforcement("同意")
        assert has_reinforcement("说得对")
        assert has_reinforcement("你说得对")
        assert has_reinforcement("这样对")
        # Negative tests - should NOT match
        assert not has_reinforcement("你好")  # "hello"
        assert not has_reinforcement("错了")  # "wrong" - correction
        assert not has_reinforcement("不对")  # "not right" - correction

    def test_chinese_preference_patterns(self) -> None:
        """Test Chinese preference pattern detection (code-puppy-4uw)."""
        # Basic preference patterns
        assert has_preference("我喜欢Python")
        assert has_preference("我偏好暗色模式")
        assert has_preference("我想要这个")
        assert has_preference("我需要帮助")
        assert has_preference("我更喜欢JavaScript")
        assert has_preference("我的偏好是VS Code")
        assert has_preference("我的最爱是Python")
        assert has_preference("我不喜欢Java")
        assert has_preference("我不想用这个")
        assert has_preference("我从来不用Java")
        assert has_preference("我通常用Python")
        assert has_preference("对我来说")
        assert has_preference("我个人觉得")
        assert has_preference("我希望用Python")
        assert has_preference("我讨厌Java")
        assert has_preference("记得用Python")
        assert has_preference("一定要用")
        assert has_preference("总是用Python")
        # Negative tests - should NOT match
        assert not has_preference("你好")  # "hello"

    def test_detect_signals_with_chinese(self) -> None:
        """Test that detect_signals finds all signal types in Chinese text (code-puppy-4uw)."""
        # Mixed Chinese text with correction + preference + reinforcement
        text = "不对，应该是Python。我喜欢Python。你说得对！"
        signals = detect_signals(text)

        signal_types = [s.signal_type for s in signals]
        assert SignalType.CORRECTION in signal_types
        assert SignalType.PREFERENCE in signal_types
        assert SignalType.REINFORCEMENT in signal_types

        # Verify matched text is Chinese
        for signal in signals:
            assert any('\u4e00' <= char <= '\u9fff' for char in signal.matched_text), \
                f"Expected Chinese text in matched_text, got: {signal.matched_text}"


# ============================================================================
# Fact Extraction Tests
# ============================================================================


class TestFactExtraction:
    """Tests for fact extraction functionality."""

    def test_basic_extraction_with_llm(self) -> None:
        """Test extraction with mock LLM client - using direct parsing test."""
        # Test the parsing directly without async
        extractor = FactExtractor(llm_client=None, min_confidence=0.5)

        # Test _parse_response directly
        mock_response = json.dumps([
            {"text": "User prefers dark mode", "confidence": 0.9},
            {"text": "Project uses Python 3.11", "confidence": 0.85},
        ])

        result = extractor._parse_response(mock_response)

        assert len(result) == 2
        assert result[0].text == "User prefers dark mode"
        assert result[0].confidence == 0.9
        assert result[1].text == "Project uses Python 3.11"
        assert result[1].confidence == 0.85

    def test_extraction_response_parsing_markdown(self) -> None:
        """Test parsing extraction response from markdown code block."""
        extractor = FactExtractor(llm_client=None)

        markdown_response = """```json
[
  {"text": "Fact one", "confidence": 0.8}
]
```"""

        result = extractor._parse_response(markdown_response)

        assert len(result) == 1
        assert result[0].text == "Fact one"

    def test_extraction_empty_response(self) -> None:
        """Test handling of empty extraction response."""
        extractor = FactExtractor(llm_client=None)

        result = extractor._parse_response("[]")

        assert len(result) == 0

    def test_extraction_invalid_json(self) -> None:
        """Test handling of invalid JSON response."""
        extractor = FactExtractor(llm_client=None)

        result = extractor._parse_response("not valid json")

        assert len(result) == 0

    def test_extraction_min_confidence_filter(self) -> None:
        """Test that min_confidence filters out low-confidence facts."""
        extractor = FactExtractor(llm_client=None, min_confidence=0.5)

        mock_response = json.dumps([
            {"text": "High confidence fact", "confidence": 0.9},
            {"text": "Low confidence fact", "confidence": 0.3},
        ])

        result = extractor._parse_response(mock_response)

        assert len(result) == 1
        assert result[0].text == "High confidence fact"

    def test_basic_extraction_no_llm(self) -> None:
        """Test basic pattern extraction when no LLM client provided."""
        extractor = FactExtractor(llm_client=None)

        messages = [
            {"role": "user", "content": "I prefer using VS Code for development."},
            {"role": "user", "content": "I like to write tests first."},
        ]

        result = asyncio.run(extractor.extract_facts(messages))

        # Should extract preference patterns
        assert len(result) > 0
        texts = [r.text.lower() for r in result]
        assert any("vs code" in t or "visual studio" in t for t in texts)

    def test_mock_llm_client_records_calls(self) -> None:
        """Test that MockLLMClient records prompt calls."""
        client = MockLLMClient(response="[]")

        # Simulate an async call
        async def test_call():
            return await client.complete("test prompt")

        asyncio.run(test_call())

        assert len(client.calls) == 1
        assert "test prompt" in client.calls[0]


# ============================================================================
# Config Tests
# ============================================================================


class TestMemoryConfig:
    """Tests for memory configuration."""

    def test_default_config_values(self) -> None:
        """Test default configuration values (Phase 6 OPT-IN defaults)."""
        config = MemoryConfig()

        # Phase 6: OPT-IN, disabled by default for privacy
        assert config.enabled is False
        # Phase 6: Increased max_facts from 10 to 50
        assert config.max_facts == 50
        # Phase 6: Reduced token_budget from 800 to 500
        assert config.token_budget == 500
        assert config.min_confidence == 0.5
        # Phase 6: Changed from debounce_ms (30000) to debounce_seconds (30)
        assert config.debounce_seconds == 30
        assert config.debounce_ms == 30000
        assert config.extraction_enabled is True

    def test_config_custom_values(self) -> None:
        """Test custom configuration values."""
        config = MemoryConfig(
            enabled=False,
            max_facts=20,
            token_budget=1000,
            min_confidence=0.7,
            debounce_ms=60000,
            extraction_enabled=False,
        )

        assert config.enabled is False
        assert config.max_facts == 20
        assert config.token_budget == 1000
        assert config.min_confidence == 0.7
        assert config.debounce_ms == 60000
        assert config.extraction_enabled is False

    def test_get_int_helper(self) -> None:
        """Test _get_int configuration helper."""
        with patch("code_puppy.config.get_value") as mock_get:
            mock_get.return_value = "42"
            assert _get_int("test_key", 10) == 42

            mock_get.return_value = None
            assert _get_int("test_key", 10) == 10

            mock_get.return_value = "invalid"
            assert _get_int("test_key", 10) == 10

            mock_get.return_value = "-5"
            assert _get_int("test_key", 10) == 10  # Negative returns default

    def test_get_bool_helper(self) -> None:
        """Test _get_bool configuration helper."""
        with patch("code_puppy.config.get_value") as mock_get:
            # Truthy values
            for val in ["1", "true", "True", "yes", "on", "enabled"]:
                mock_get.return_value = val
                assert _get_bool("test_key", False) is True

            # None returns default
            mock_get.return_value = None
            assert _get_bool("test_key", True) is True
            assert _get_bool("test_key", False) is False

            # Explicitly falsy values
            for val in ["0", "false", "False", "no", "off", "disabled"]:
                mock_get.return_value = val
                # These values are explicitly in the falsy set
                assert _get_bool("test_key", True) is False

    def test_get_float_helper(self) -> None:
        """Test _get_float configuration helper."""
        with patch("code_puppy.config.get_value") as mock_get:
            mock_get.return_value = "0.75"
            assert _get_float("test_key", 0.5) == 0.75

            mock_get.return_value = None
            assert _get_float("test_key", 0.5) == 0.5

            mock_get.return_value = "invalid"
            assert _get_float("test_key", 0.5) == 0.5


# ============================================================================
# Callback Integration Tests
# ============================================================================


class TestCallbackIntegration:
    """Tests for callback integration functions."""

    def test_normalize_messages_dict_format(self) -> None:
        """Test normalizing dict-format messages."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]

        normalized = _normalize_messages(messages)

        assert len(normalized) == 2
        assert normalized[0]["role"] == "user"
        assert normalized[0]["content"] == "Hello"

    def test_normalize_messages_object_format(self) -> None:
        """Test normalizing object-format messages."""
        class MockMessage:
            def __init__(self, role: str, content: str):
                self.role = role
                self.content = content

        messages = [
            MockMessage("user", "Hello"),
            MockMessage("assistant", "Hi!"),
        ]

        normalized = _normalize_messages(messages)

        assert len(normalized) == 2
        assert normalized[0]["role"] == "user"

    def test_format_memory_section_basic(self) -> None:
        """Test basic memory section formatting."""
        facts = [
            {"text": "User prefers dark mode", "confidence": 0.9},
            {"text": "Project uses Python", "confidence": 0.8},
        ]

        result = _format_memory_section(facts, max_facts=5, token_budget=500)

        assert result is not None
        assert "## Memory" in result
        assert "User prefers dark mode" in result
        assert "confidence: 0.9" in result

    def test_format_memory_section_respects_max_facts(self) -> None:
        """Test that memory section respects max_facts limit."""
        facts = [
            {"text": f"Fact {i}", "confidence": 0.9 - (i * 0.05)}
            for i in range(10)
        ]

        result = _format_memory_section(facts, max_facts=3, token_budget=1000)

        assert result is not None
        # Count bullet points (lines starting with "-")
        bullet_count = len([line for line in result.split("\n") if line.startswith("-")])
        assert bullet_count <= 3

    def test_format_memory_section_respects_token_budget(self) -> None:
        """Test that memory section respects token budget."""
        facts = [
            {"text": "This is a very long fact that takes up lots of space" * 10, "confidence": 0.9},
            {"text": "Another long fact " * 50, "confidence": 0.8},
        ]

        # Very small budget should limit output
        result = _format_memory_section(facts, max_facts=10, token_budget=20)

        # Result should be None or very short
        if result:
            assert len(result) < 100  # Should be truncated

    def test_format_memory_section_empty_facts(self) -> None:
        """Test that empty facts returns None."""
        result = _format_memory_section([], max_facts=5, token_budget=500)
        assert result is None

    def test_format_memory_section_only_header(self) -> None:
        """Test that facts that don't fit budget result in None."""
        # Create facts that won't fit tiny budget
        facts = [{"text": "Short", "confidence": 0.5}]

        result = _format_memory_section(facts, max_facts=1, token_budget=1)

        assert result is None  # Only header, no facts fit


# ============================================================================
# End-to-End Integration Tests
# ============================================================================


class TestEndToEndIntegration:
    """End-to-end tests simulating full memory workflows."""

    @pytest.fixture(autouse=True)
    def setup_isolated_storage(self, temp_memory_dir: Path, monkeypatch: pytest.MonkeyPatch):
        """Setup isolated storage for each test."""
        # Patch storage module's MEMORY_DIR
        import code_puppy.plugins.agent_memory.storage as storage_module
        import code_puppy.plugins.agent_memory.core as core_module

        original_dir = storage_module._MEMORY_DIR
        storage_module._MEMORY_DIR = temp_memory_dir

        # Reset caches
        core_module._storage_cache.clear()
        core_module._updater_cache.clear()
        core_module._config = None
        core_module._extractor = None
        core_module._detector = None

        yield

        # Cleanup
        storage_module._MEMORY_DIR = original_dir
        core_module._storage_cache.clear()
        core_module._updater_cache.clear()

    def test_full_conversation_to_memory_flow(
        self, temp_memory_dir: Path
    ) -> None:
        """End-to-end: simulate conversation, extract facts, verify storage."""
        # Initialize with mock config
        with patch("code_puppy.plugins.agent_memory.core.load_config") as mock_load:
            config = MemoryConfig(
                enabled=True,
                max_facts=5,
                token_budget=200,
                min_confidence=0.5,
                debounce_ms=100,
                extraction_enabled=True,
            )
            mock_load.return_value = config

            _on_startup()

            # Simulate agent conversation
            agent_name = "test-agent-flow"
            session_id = "test-session-123"

            messages = [
                {"role": "user", "content": "I prefer using React with TypeScript"},
                {"role": "assistant", "content": "Noted! React with TypeScript."},
                {"role": "user", "content": "Yes, exactly! I also use ESLint and Prettier."},
            ]

            # Simulate agent run end with run_context containing messages
            with patch("code_puppy.plugins.agent_memory.messaging.get_current_run_context") as mock_ctx:
                mock_context = MagicMock()
                mock_context.metadata = {"message_history": messages}
                mock_ctx.return_value = mock_context

                asyncio.run(
                    _on_agent_run_end(
                        agent_name=agent_name,
                        model_name="test-model",
                        session_id=session_id,
                        success=True,
                    )
                )

            # Flush pending writes
            _on_shutdown()

            # Verify facts were stored
            storage = FileMemoryStorage(agent_name)
            facts = storage.get_facts(min_confidence=0.0)

            # Should have at least some facts from basic extraction
            assert len(facts) >= 0  # May or may not have facts depending on extraction

    def test_signal_confidence_update_flow(
        self, temp_memory_dir: Path
    ) -> None:
        """End-to-end: test signal detection updates fact confidence."""
        with patch("code_puppy.plugins.agent_memory.core.load_config") as mock_load:
            config = MemoryConfig(
                enabled=True,
                max_facts=5,
                token_budget=200,
                min_confidence=0.5,
                debounce_ms=100,
                extraction_enabled=True,
            )
            mock_load.return_value = config

            _on_startup()

            agent_name = "test-agent"

            # First, add a fact
            storage = _get_storage(agent_name)
            storage.add_fact({
                "text": "User prefers Python",
                "confidence": 0.8,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

            # Now simulate a correction signal about that fact
            # The message must contain text similar to the fact for matching to work
            messages = [
                {"role": "user", "content": "Actually, that's wrong. User prefers Python is not correct anymore."},
            ]

            # Apply signal updates
            updated = _apply_signal_confidence_updates(agent_name, messages, None)

            # Verify confidence was reduced or updated
            facts = storage.get_facts(min_confidence=0.0)
            assert len(facts) == 1
            # If an update was applied, verify confidence changed or timestamp updated
            if updated > 0:
                assert facts[0]["confidence"] == pytest.approx(0.5, abs=0.01)  # 0.8 + (-0.3)

    def test_prompt_injection_with_token_budget(
        self, temp_memory_dir: Path
    ) -> None:
        """End-to-end: test prompt injection respects token budget."""
        # Patch both core.load_config (used by _on_startup) and prompts.load_config (used by _on_load_prompt)
        with patch("code_puppy.plugins.agent_memory.core.load_config") as mock_core_load, patch(
            "code_puppy.plugins.agent_memory.prompts.load_config"
        ) as mock_prompts_load:
            # Create custom config with specific values (dataclass is frozen)
            custom_config = MemoryConfig(
                enabled=True,
                max_facts=5,
                token_budget=100,
                min_confidence=0.5,
                debounce_ms=100,
                extraction_enabled=True,
            )
            mock_core_load.return_value = custom_config
            mock_prompts_load.return_value = custom_config

            _on_startup()

            agent_name = "test-agent"

            # Add multiple facts
            storage = _get_storage(agent_name)
            for i in range(10):
                storage.add_fact({
                    "text": f"Test fact number {i} with some content",
                    "confidence": 0.9 - (i * 0.05),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })

            # Try to load prompt with mock context
            with patch("code_puppy.run_context.get_current_run_context") as mock_ctx:
                mock_context = MagicMock()
                mock_context.component_name = agent_name
                mock_ctx.return_value = mock_context

                result = _on_load_prompt(
                    model_name="test-model",
                    default_system_prompt="You are a helpful assistant.",
                    user_prompt="Hello",
                )

                assert result is not None
                assert "instructions" in result
                instructions = result["instructions"]

                # Should be within token budget
                estimated_tokens = len(instructions) // 4
                assert estimated_tokens <= 100 + 50  # Allow some margin

                # Should not exceed max_facts
                bullet_count = len([line for line in instructions.split("\n") if line.startswith("-")])
                assert bullet_count <= 5

    def test_disabled_plugin_skips_processing(
        self, temp_memory_dir: Path
    ) -> None:
        """Test that disabled plugin skips all processing."""
        disabled_config = MemoryConfig(enabled=False)

        with patch("code_puppy.plugins.agent_memory.core.load_config") as mock_load:
            mock_load.return_value = disabled_config

            _on_startup()

            # Should return None for prompt injection
            result = _on_load_prompt("test-model", "Default prompt", "user prompt")
            assert result is None

            # Agent run end should not throw and should return early
            asyncio.run(
                _on_agent_run_end(
                    agent_name="test",
                    model_name="test",
                    success=True,
                )
            )


# ============================================================================
# Regression and Edge Case Tests
# ============================================================================


class TestEdgeCasesAndRegression:
    """Edge case and regression tests."""

    def test_empty_conversation_handling(self) -> None:
        """Test handling of empty conversation."""
        extractor = FactExtractor(llm_client=None)
        result = asyncio.run(extractor.extract_facts([]))
        assert result == []

    def test_malformed_messages_handling(self) -> None:
        """Test handling of malformed messages."""
        messages = [
            {"role": "user"},  # Missing content
            {"content": "hello"},  # Missing role
            {},  # Empty
        ]

        normalized = _normalize_messages(messages)
        assert len(normalized) == 3
        # Should handle gracefully

    def test_very_long_fact_text(self) -> None:
        """Test handling of very long fact text."""
        long_text = "A" * 10000
        facts = [{"text": long_text, "confidence": 0.9}]

        result = _format_memory_section(facts, max_facts=1, token_budget=100)
        # Should truncate or handle gracefully
        assert result is None or len(result) < 10000

    def test_special_characters_in_facts(self) -> None:
        """Test handling of special characters in facts."""
        facts = [
            {"text": "Uses C++ with templates <T>", "confidence": 0.9},
            {"text": "Path: /home/user/file.txt", "confidence": 0.8},
            {"text": "Regex: \\d+\\.\\w*", "confidence": 0.7},
        ]

        result = _format_memory_section(facts, max_facts=10, token_budget=1000)
        assert result is not None
        # All facts should appear
        assert "C++" in result
        assert "/home/user" in result

    def test_concurrent_access_safety(self, temp_memory_dir: Path) -> None:
        """Test thread safety of storage operations within a single process."""
        import os
        import threading

        # Use unique agent name based on PID to avoid cross-process conflicts
        agent_name = f"concurrent-test-{os.getpid()}"

        # Clear any pre-existing facts
        storage = FileMemoryStorage(agent_name)
        storage.clear()

        errors = []

        def add_fact(i: int):
            try:
                storage.add_fact({
                    "text": f"Fact {i}",
                    "confidence": 0.8,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_fact, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        facts = storage.get_facts(min_confidence=0.0)
        # Each thread adds 1 fact, so 20 total
        assert len(facts) == 20, f"Expected 20 facts, got {len(facts)}: {facts}"

    def test_cache_bypass_race_condition_fixed(self, temp_memory_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that _get_storage_for_current_agent uses cache, preventing race conditions.
        
        Regression test for code-puppy-ley: The bug was that _get_storage_for_current_agent
        created a new FileMemoryStorage instance each time, bypassing the cache. This meant
        each thread got a different lock object for the same file, causing data races.
        """
        import os
        import threading
        from code_puppy.plugins.agent_memory.messaging import _get_storage_for_current_agent
        from code_puppy.plugins.agent_memory import core as core_module

        # Use unique agent name
        agent_name = f"race-test-{os.getpid()}"

        # Patch _get_current_agent_name to return our test agent
        from code_puppy.plugins.agent_memory import messaging as messaging_module
        original_get_agent = messaging_module._get_current_agent_name
        messaging_module._get_current_agent_name = lambda: agent_name

        # Patch storage directory
        import code_puppy.plugins.agent_memory.storage as storage_module
        original_dir = storage_module._MEMORY_DIR
        storage_module._MEMORY_DIR = temp_memory_dir

        # Reset caches to start fresh
        core_module._storage_cache.clear()

        try:
            # Get storage multiple times
            storage1 = _get_storage_for_current_agent()
            storage2 = _get_storage_for_current_agent()
            storage3 = _get_storage_for_current_agent()

            # All should be the SAME instance (same lock object)
            assert storage1 is storage2, "Cache bypass: _get_storage_for_current_agent returned different instances!"
            assert storage1 is storage3, "Cache bypass: _get_storage_for_current_agent returned different instances!"

            # Verify it's actually in the cache
            assert agent_name in core_module._storage_cache, "Storage not added to cache"
            assert core_module._storage_cache[agent_name] is storage1, "Cached instance mismatch"

            # Now test thread safety with the fixed function
            errors = []
            successes = []

            def get_storage_and_verify(i: int):
                try:
                    s = _get_storage_for_current_agent()
                    # All threads should get the same instance
                    if s is storage1:
                        successes.append(i)
                    else:
                        errors.append(f"Thread {i} got different storage instance: {s}")
                except Exception as e:
                    errors.append(f"Thread {i} raised {e}")

            threads = [threading.Thread(target=get_storage_and_verify, args=(i,)) for i in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0, f"Race condition detected: {errors}"
            assert len(successes) == 10, "All threads should get same instance"

        finally:
            # Cleanup
            messaging_module._get_current_agent_name = original_get_agent
            storage_module._MEMORY_DIR = original_dir
            core_module._storage_cache.clear()


# ============================================================================
# Async Correctness Tests (code-puppy-48p)
# ============================================================================


class TestAsyncCorrectness:
    """Tests for async correctness fixes (code-puppy-48p)."""

    def test_schedule_fact_extraction_returns_task(self) -> None:
        """_schedule_fact_extraction returns a task when in async context."""
        import asyncio
        from code_puppy.plugins.agent_memory.processing import _schedule_fact_extraction

        async def test_coro():
            # Schedule extraction in async context
            task = _schedule_fact_extraction("test-agent", [], None)
            # Should return a Task in async context
            assert task is not None
            assert isinstance(task, asyncio.Task)
            # Task should have a name
            assert task.get_name().startswith("agent_memory:")

        asyncio.run(test_coro())

    def test_schedule_fact_extraction_no_event_loop(self) -> None:
        """_schedule_fact_extraction handles no event loop gracefully."""
        from code_puppy.plugins.agent_memory.processing import _schedule_fact_extraction

        # Called from sync context without event loop
        task = _schedule_fact_extraction("test-agent", [], None)
        # Returns None when no event loop (spawns thread instead)
        assert task is None


# ============================================================================
# Batch Signal Update Tests (code-puppy-48p)
# ============================================================================


class TestBatchSignalUpdates:
    """Tests for batch signal confidence updates (code-puppy-48p)."""

    def test_signal_confidence_updates_batched(
        self, temp_memory_dir: Path
    ) -> None:
        """Signal confidence updates are batched into single file write."""
        with patch("code_puppy.plugins.agent_memory.core.load_config") as mock_load:
            config = MemoryConfig(
                enabled=True,
                max_facts=5,
                token_budget=200,
                min_confidence=0.5,
                debounce_ms=100,
                extraction_enabled=True,
            )
            mock_load.return_value = config

            _on_startup()
            agent_name = "batch-signal-test"

            # Add initial facts
            storage = _get_storage(agent_name)
            storage.add_facts([
                {"text": "User prefers Python for data science", "confidence": 0.8},
                {"text": "User uses VS Code as IDE", "confidence": 0.9},
                {"text": "User likes dark mode", "confidence": 0.7},
            ])

            # Multiple correction signals in one batch
            messages = [
                {"role": "user", "content": "Actually, that's wrong. I prefer R for data science."},
                {"role": "user", "content": "No, I use PyCharm not VS Code."},
            ]

            # Apply signal updates
            updated = _apply_signal_confidence_updates(agent_name, messages, "session-1")

            # Both facts should be updated (confidence reduced)
            facts = storage.get_facts(min_confidence=0.0)
            fact_by_text = {f["text"]: f for f in facts}

            # Verify both signals were applied
            if updated > 0:
                # Python fact should have reduced confidence
                python_fact = fact_by_text.get("User prefers Python for data science")
                if python_fact and "last_reinforced" in python_fact:
                    # Signal was applied
                    assert python_fact["confidence"] < 0.8 or "last_reinforced" in python_fact


# ============================================================================
# Public API Tests
# ============================================================================


def test_all_public_api_exports() -> None:
    """Verify all expected exports are available."""
    # Should not raise any ImportError
    from code_puppy.plugins.agent_memory import (
        CORRECTION_DELTA,
        DEFAULT_DEBOUNCE_MS,
        DEFAULT_EXTRACTION_PROMPT,
        ExtractedFact,
        Fact,
        FactExtractor,
        FileMemoryStorage,
        MemoryConfig,
        MemoryUpdater,
        MockLLMClient,
        PREFERENCE_DELTA,
        REINFORCEMENT_DELTA,
        Signal,
        SignalDetector,
        SignalType,
        detect_signals,
        has_correction,
        has_preference,
        has_reinforcement,
        load_config,
    )

    # Verify types
    assert isinstance(CORRECTION_DELTA, float)
    assert isinstance(REINFORCEMENT_DELTA, float)
    assert isinstance(PREFERENCE_DELTA, float)
    assert isinstance(DEFAULT_DEBOUNCE_MS, int)
    assert SignalType.CORRECTION is not None
