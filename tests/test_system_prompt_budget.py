"""Tests for system prompt budget management."""

import pytest
from unittest.mock import patch, MagicMock

from code_puppy.system_prompt_budget import (
    BudgetConfig,
    BudgetTracker,
    PluginContribution,
    load_budget_config,
    create_budget_tracker,
    get_current_budget_tracker,
    set_current_budget_tracker,
    reset_budget_tracker,
)


def test_budget_config_defaults():
    """Test BudgetConfig default values."""
    config = BudgetConfig()
    assert config.max_tokens is None
    assert config.warning_threshold == 0.8
    assert config.condensed_mode == "auto"
    assert config.enabled is True


def test_budget_config_custom_values():
    """Test BudgetConfig with custom values."""
    config = BudgetConfig(
        max_tokens=4000,
        warning_threshold=0.7,
        condensed_mode="always",
        enabled=False
    )
    assert config.max_tokens == 4000
    assert config.warning_threshold == 0.7
    assert config.condensed_mode == "always"
    assert config.enabled is False


def test_budget_tracker_effective_max_tokens():
    """Test BudgetTracker effective max tokens calculation."""
    config = BudgetConfig(max_tokens=None)
    tracker = BudgetTracker(config=config, model_context_length=100000)
    # Default: 20% of model context length
    assert tracker.effective_max_tokens == 20000
    
    config = BudgetConfig(max_tokens=5000)
    tracker = BudgetTracker(config=config, model_context_length=100000)
    assert tracker.effective_max_tokens == 5000


def test_budget_tracker_add_contribution():
    """Test adding contributions to budget tracker."""
    config = BudgetConfig(max_tokens=1000)
    tracker = BudgetTracker(config=config)
    
    contribution = tracker.add_contribution("test_plugin", "This is test content", condensed=False)
    assert contribution.plugin_name == "test_plugin"
    assert contribution.content == "This is test content"
    assert contribution.tokens > 0
    assert contribution.condensed is False
    assert len(tracker.contributions) == 1


def test_budget_tracker_total_tokens_used():
    """Test total tokens calculation."""
    config = BudgetConfig(max_tokens=1000)
    tracker = BudgetTracker(config=config)
    
    tracker.add_contribution("plugin1", "Short content")
    tracker.add_contribution("plugin2", "Another piece of content")
    
    assert tracker.total_tokens_used > 0
    assert tracker.budget_remaining < 1000


def test_budget_tracker_usage_ratio():
    """Test usage ratio calculation."""
    config = BudgetConfig(max_tokens=1000)
    tracker = BudgetTracker(config=config)
    
    # Mock estimate_token_count to return a predictable value
    with patch('code_puppy.system_prompt_budget.estimate_token_count', return_value=500):
        tracker.add_contribution("plugin1", "Content")
        assert tracker.usage_ratio == 0.5


def test_budget_tracker_should_use_condensed():
    """Test condensed mode logic."""
    # Test auto mode
    config = BudgetConfig(max_tokens=1000, warning_threshold=0.8, condensed_mode="auto")
    tracker = BudgetTracker(config=config)
    
    # Mock estimate_token_count to return a predictable value
    with patch('code_puppy.system_prompt_budget.estimate_token_count', return_value=700):
        tracker.add_contribution("plugin1", "Content")
        # 700/1000 = 0.7, below threshold
        assert tracker.should_use_condensed is False
    
    with patch('code_puppy.system_prompt_budget.estimate_token_count', return_value=900):
        tracker.add_contribution("plugin2", "More content")
        # 1600/1000 = 1.6, above threshold
        assert tracker.should_use_condensed is True
    
    # Test always mode
    config = BudgetConfig(condensed_mode="always")
    tracker = BudgetTracker(config=config)
    assert tracker.should_use_condensed is True
    
    # Test never mode
    config = BudgetConfig(condensed_mode="never")
    tracker = BudgetTracker(config=config)
    assert tracker.should_use_condensed is False


def test_budget_tracker_get_combined_content():
    """Test getting combined content from all plugins."""
    config = BudgetConfig()
    tracker = BudgetTracker(config=config)
    
    tracker.add_contribution("plugin1", "Content from plugin 1")
    tracker.add_contribution("plugin2", "Content from plugin 2")
    
    combined = tracker.get_combined_content()
    assert "Content from plugin 1" in combined
    assert "Content from plugin 2" in combined
    assert "\n\n" in combined


def test_load_budget_config_defaults():
    """Test loading budget config with defaults."""
    with patch('code_puppy.system_prompt_budget.get_value') as mock_get_value:
        mock_get_value.return_value = None
        config = load_budget_config()
        
        assert config.max_tokens is None
        assert config.warning_threshold == 0.8
        assert config.condensed_mode == "auto"
        assert config.enabled is True


def test_load_budget_config_custom():
    """Test loading budget config with custom values."""
    def mock_get_value(key):
        values = {
            "system_prompt_budget_tokens": "5000",
            "system_prompt_budget_warning_threshold": "0.7",
            "system_prompt_condensed_mode": "always",
            "system_prompt_budget_enabled": "false"
        }
        return values.get(key)
    
    with patch('code_puppy.system_prompt_budget.get_value', side_effect=mock_get_value):
        config = load_budget_config()
        
        assert config.max_tokens == 5000
        assert config.warning_threshold == 0.7
        assert config.condensed_mode == "always"
        assert config.enabled is False


def test_create_budget_tracker():
    """Test creating a budget tracker."""
    tracker = create_budget_tracker(model_context_length=100000)
    assert tracker is not None
    assert tracker.model_context_length == 100000
    assert tracker.config is not None


def test_budget_tracker_singleton():
    """Test budget tracker singleton pattern."""
    reset_budget_tracker()
    assert get_current_budget_tracker() is None
    
    tracker = create_budget_tracker()
    set_current_budget_tracker(tracker)
    assert get_current_budget_tracker() is tracker
    
    reset_budget_tracker()
    assert get_current_budget_tracker() is None


def test_budget_tracker_warning_logging(caplog):
    """Test that warnings are logged when budget is exceeded."""
    config = BudgetConfig(max_tokens=100, warning_threshold=0.8, enabled=True)
    tracker = BudgetTracker(config=config)
    
    with patch('code_puppy.system_prompt_budget.estimate_token_count', return_value=150):
        with caplog.at_level("WARNING"):
            tracker.add_contribution("test_plugin", "Large content that exceeds budget")
            
            assert "System prompt budget exceeded" in caplog.text
            assert "test_plugin" in caplog.text


def test_budget_tracker_info_logging(caplog):
    """Test that info is logged when approaching budget."""
    config = BudgetConfig(max_tokens=100, warning_threshold=0.8, enabled=True)
    tracker = BudgetTracker(config=config)
    
    with patch('code_puppy.system_prompt_budget.estimate_token_count', return_value=85):
        with caplog.at_level("INFO"):
            tracker.add_contribution("test_plugin", "Content approaching budget")
            
            assert "System prompt budget at" in caplog.text
            assert "85" in caplog.text


def test_plugin_contribution_dataclass():
    """Test PluginContribution dataclass."""
    contribution = PluginContribution(
        plugin_name="test",
        content="test content",
        tokens=10,
        condensed=True
    )
    
    assert contribution.plugin_name == "test"
    assert contribution.content == "test content"
    assert contribution.tokens == 10
    assert contribution.condensed is True