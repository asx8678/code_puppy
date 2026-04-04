"""System prompt budget management for plugin-contributed content.

This module provides budget tracking and enforcement for system prompt
content contributed by plugins via the get_model_system_prompt hook.

Plugins can inject content into system prompts, but without budget awareness,
a large repo with many skills can push the system prompt to 20K+ tokens,
leaving less room for conversation.

Features:
- Configurable budget limits
- Token tracking per plugin
- Warning logs when budget is exceeded
- Condensed mode for plugins when near budget limit
"""

import logging
from dataclasses import dataclass
from typing import Any

from code_puppy.config import get_value, _is_truthy
from code_puppy.token_utils import estimate_token_count

logger = logging.getLogger(__name__)


@dataclass
class BudgetConfig:
    """Configuration for system prompt budget management."""
    
    # Maximum tokens allowed for plugin-contributed system prompt content
    # None means use 20% of model context length
    max_tokens: int | None = None
    
    # Warning threshold (0.0-1.0) - log warning when usage exceeds this ratio
    warning_threshold: float = 0.8
    
    # Condensed mode: "auto", "always", "never"
    # "auto": Use condensed mode when budget usage > warning_threshold
    condensed_mode: str = "auto"
    
    # Whether budget management is enabled
    enabled: bool = True


@dataclass
class PluginContribution:
    """Track a plugin's contribution to system prompt."""
    
    plugin_name: str
    content: str
    tokens: int
    condensed: bool = False


@dataclass
class BudgetTracker:
    """Track system prompt budget usage across plugins."""
    
    config: BudgetConfig
    model_context_length: int = 128000
    contributions: list[PluginContribution] = None
    
    def __post_init__(self):
        if self.contributions is None:
            self.contributions = []
    
    @property
    def effective_max_tokens(self) -> int:
        """Get effective max tokens for plugin content."""
        if self.config.max_tokens is not None:
            return self.config.max_tokens
        # Default: 20% of model context length
        return int(self.model_context_length * 0.2)
    
    @property
    def total_tokens_used(self) -> int:
        """Total tokens used by all plugins."""
        return sum(c.tokens for c in self.contributions)
    
    @property
    def budget_remaining(self) -> int:
        """Remaining budget tokens."""
        return max(0, self.effective_max_tokens - self.total_tokens_used)
    
    @property
    def usage_ratio(self) -> float:
        """Current usage as ratio of max tokens."""
        if self.effective_max_tokens == 0:
            return 1.0
        return self.total_tokens_used / self.effective_max_tokens
    
    @property
    def should_use_condensed(self) -> bool:
        """Check if condensed mode should be used."""
        if self.config.condensed_mode == "always":
            return True
        if self.config.condensed_mode == "never":
            return False
        # "auto" mode: use condensed when over threshold
        return self.usage_ratio >= self.config.warning_threshold
    
    def add_contribution(self, plugin_name: str, content: str, condensed: bool = False) -> PluginContribution:
        """Add a plugin's contribution and track tokens."""
        tokens = estimate_token_count(content)
        contribution = PluginContribution(
            plugin_name=plugin_name,
            content=content,
            tokens=tokens,
            condensed=condensed
        )
        self.contributions.append(contribution)
        
        # Log warning if budget exceeded
        if self.config.enabled and self.total_tokens_used > self.effective_max_tokens:
            logger.warning(
                f"System prompt budget exceeded: {self.total_tokens_used} tokens used "
                f"(limit: {self.effective_max_tokens}). Plugin '{plugin_name}' contributed {tokens} tokens."
            )
        elif self.config.enabled and self.usage_ratio >= self.config.warning_threshold:
            logger.info(
                f"System prompt budget at {self.usage_ratio:.1%}: {self.total_tokens_used} tokens used "
                f"(limit: {self.effective_max_tokens})."
            )
        
        return contribution
    
    def get_combined_content(self) -> str:
        """Get combined content from all plugins."""
        return "\n\n".join(c.content for c in self.contributions if c.content)


def load_budget_config() -> BudgetConfig:
    """Load budget configuration from config file."""
    max_tokens_raw = get_value("system_prompt_budget_tokens")
    max_tokens = None
    if max_tokens_raw:
        try:
            max_tokens = int(max_tokens_raw)
            if max_tokens <= 0:
                max_tokens = None
        except (TypeError, ValueError):
            max_tokens = None
    
    warning_threshold_raw = get_value("system_prompt_budget_warning_threshold")
    warning_threshold = 0.8
    if warning_threshold_raw:
        try:
            warning_threshold = float(warning_threshold_raw)
            warning_threshold = max(0.0, min(1.0, warning_threshold))
        except (TypeError, ValueError):
            pass
    
    condensed_mode = get_value("system_prompt_condensed_mode") or "auto"
    if condensed_mode not in ("auto", "always", "never"):
        condensed_mode = "auto"
    
    enabled = _is_truthy(get_value("system_prompt_budget_enabled"), default=True)
    
    return BudgetConfig(
        max_tokens=max_tokens,
        warning_threshold=warning_threshold,
        condensed_mode=condensed_mode,
        enabled=enabled
    )


def create_budget_tracker(model_context_length: int = 128000) -> BudgetTracker:
    """Create a new budget tracker with current configuration."""
    config = load_budget_config()
    return BudgetTracker(config=config, model_context_length=model_context_length)


# Global budget tracker for current request
_current_budget_tracker: BudgetTracker | None = None


def get_current_budget_tracker() -> BudgetTracker | None:
    """Get the current budget tracker."""
    return _current_budget_tracker


def set_current_budget_tracker(tracker: BudgetTracker | None) -> None:
    """Set the current budget tracker."""
    global _current_budget_tracker
    _current_budget_tracker = tracker


def reset_budget_tracker() -> None:
    """Reset the budget tracker."""
    global _current_budget_tracker
    _current_budget_tracker = None