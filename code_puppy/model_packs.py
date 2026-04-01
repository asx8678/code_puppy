"""Model packs with role-based routing and fallback chains.

This module implements model packs inspired by Plandex that route different
task roles to different models, with fallback chains for:
- Context-window overflow
- Provider failure
- Task complexity

Example pack configuration:
    {
        "name": "default",
        "roles": {
            "planner": {
                "primary": "claude-sonnet-4",
                "fallbacks": ["gpt-4o", "gemini-2.5-flash"],
                "trigger": "context_overflow"
            },
            "coder": {
                "primary": "zai-glm-5.1-coding",
                "fallbacks": ["synthetic-GLM-5", "firepass-kimi-k2p5-turbo"],
                "trigger": "provider_failure"
            }
        }
    }
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from code_puppy.config import DATA_DIR, get_global_model_name
from code_puppy.messaging import emit_error, emit_info, emit_warning

logger = logging.getLogger(__name__)

# Default model packs configuration
DEFAULT_PACKS: dict[str, "ModelPack"] = {}


@dataclass(frozen=True)
class RoleConfig:
    """Configuration for a specific role within a model pack.
    
    Attributes:
        primary: The primary model for this role
        fallbacks: Ordered list of fallback models
        trigger: What triggers fallback ("context_overflow", "provider_failure", "always")
    """
    primary: str
    fallbacks: list[str] = field(default_factory=list)
    trigger: str = "provider_failure"
    
    def get_model_chain(self) -> list[str]:
        """Return the full model chain: primary + fallbacks."""
        return [self.primary] + self.fallbacks


@dataclass(frozen=True)
class ModelPack:
    """A model pack defining models for different roles.
    
    Attributes:
        name: Pack identifier
        description: Human-readable description
        roles: Mapping of role names to RoleConfig
        default_role: Role to use when no specific role is requested
    """
    name: str
    description: str
    roles: dict[str, RoleConfig]
    default_role: str = "coder"
    
    def get_model_for_role(self, role: str | None = None) -> str:
        """Get the primary model for a role.
        
        Args:
            role: Role name, or None for default role
            
        Returns:
            Primary model name for the role
        """
        role = role or self.default_role
        if role not in self.roles:
            logger.warning(f"Role '{role}' not found in pack '{self.name}', using default")
            role = self.default_role
        return self.roles[role].primary
    
    def get_fallback_chain(self, role: str | None = None) -> list[str]:
        """Get the full fallback chain for a role.
        
        Args:
            role: Role name, or None for default role
            
        Returns:
            List of models: [primary, fallback1, fallback2, ...]
        """
        role = role or self.default_role
        if role not in self.roles:
            role = self.default_role
        return self.roles[role].get_model_chain()


# Define built-in default packs
def _init_default_packs():
    """Initialize default model packs."""
    global DEFAULT_PACKS
    
    # Single model pack - uses one model for all roles
    single_pack = ModelPack(
        name="single",
        description="Use one model for all tasks",
        roles={
            "planner": RoleConfig(primary="auto"),
            "coder": RoleConfig(primary="auto"),
            "reviewer": RoleConfig(primary="auto"),
            "summarizer": RoleConfig(primary="auto"),
            "title": RoleConfig(primary="auto"),
        },
        default_role="coder"
    )
    
    # Coding-optimized pack - uses coding-specialized models
    coding_pack = ModelPack(
        name="coding",
        description="Optimized for coding tasks with specialized models",
        roles={
            "planner": RoleConfig(
                primary="claude-sonnet-4",
                fallbacks=["gpt-4o", "gemini-2.5-flash"],
                trigger="context_overflow"
            ),
            "coder": RoleConfig(
                primary="zai-glm-5.1-coding",
                fallbacks=["synthetic-GLM-5", "firepass-kimi-k2p5-turbo"],
                trigger="provider_failure"
            ),
            "reviewer": RoleConfig(
                primary="claude-sonnet-4",
                fallbacks=["gpt-4o-mini"],
                trigger="always"
            ),
            "summarizer": RoleConfig(
                primary="gemini-2.5-flash",
                fallbacks=["gpt-4o-mini"],
                trigger="context_overflow"
            ),
            "title": RoleConfig(
                primary="gpt-4o-mini",
                fallbacks=["gemini-2.5-flash"],
                trigger="always"
            ),
        },
        default_role="coder"
    )
    
    # Cost-effective pack - uses cheaper models where appropriate
    economical_pack = ModelPack(
        name="economical",
        description="Cost-effective model selection for budget-conscious usage",
        roles={
            "planner": RoleConfig(
                primary="gemini-2.5-flash",
                fallbacks=["gpt-4o-mini"],
                trigger="context_overflow"
            ),
            "coder": RoleConfig(
                primary="synthetic-GLM-5",
                fallbacks=["gemini-2.5-flash"],
                trigger="provider_failure"
            ),
            "reviewer": RoleConfig(
                primary="gpt-4o-mini",
                fallbacks=["gemini-2.5-flash"],
                trigger="always"
            ),
            "summarizer": RoleConfig(
                primary="gemini-2.5-flash",
                fallbacks=["gpt-4o-mini"],
                trigger="always"
            ),
            "title": RoleConfig(
                primary="gpt-4o-mini",
                trigger="always"
            ),
        },
        default_role="coder"
    )
    
    # High-capacity pack - uses models with large context windows
    capacity_pack = ModelPack(
        name="capacity",
        description="Models with large context windows for big tasks",
        roles={
            "planner": RoleConfig(
                primary="synthetic-Kimi-K2.5-Thinking",
                fallbacks=["firepass-kimi-k2p5-turbo"],
                trigger="context_overflow"
            ),
            "coder": RoleConfig(
                primary="synthetic-qwen3.5-397b",
                fallbacks=["synthetic-Kimi-K2.5-Thinking"],
                trigger="context_overflow"
            ),
            "reviewer": RoleConfig(
                primary="synthetic-Kimi-K2.5-Thinking",
                fallbacks=["claude-sonnet-4"],
                trigger="context_overflow"
            ),
            "summarizer": RoleConfig(
                primary="synthetic-Kimi-K2.5-Thinking",
                fallbacks=["synthetic-qwen3.5-397b"],
                trigger="context_overflow"
            ),
            "title": RoleConfig(
                primary="gpt-4o-mini",
                trigger="always"
            ),
        },
        default_role="coder"
    )
    
    DEFAULT_PACKS = {
        single_pack.name: single_pack,
        coding_pack.name: coding_pack,
        economical_pack.name: economical_pack,
        capacity_pack.name: capacity_pack,
    }


# Initialize default packs on module load
_init_default_packs()


# User-defined packs storage
_user_packs: dict[str, ModelPack] = {}
_current_pack_name: str = "single"


def get_packs_file() -> Path:
    """Get the path to the user-defined packs file."""
    return Path(DATA_DIR) / "model_packs.json"


def load_user_packs() -> None:
    """Load user-defined model packs from disk."""
    global _user_packs
    packs_file = get_packs_file()
    
    if not packs_file.exists():
        return
    
    try:
        with open(packs_file, "r") as f:
            data = json.load(f)
        
        for pack_name, pack_data in data.items():
            roles = {}
            for role_name, role_config in pack_data.get("roles", {}).items():
                roles[role_name] = RoleConfig(
                    primary=role_config.get("primary", "auto"),
                    fallbacks=role_config.get("fallbacks", []),
                    trigger=role_config.get("trigger", "provider_failure")
                )
            
            _user_packs[pack_name] = ModelPack(
                name=pack_name,
                description=pack_data.get("description", "User-defined pack"),
                roles=roles,
                default_role=pack_data.get("default_role", "coder")
            )
    except Exception as e:
        logger.warning(f"Failed to load user model packs: {e}")


def save_user_packs() -> None:
    """Save user-defined model packs to disk."""
    packs_file = get_packs_file()
    packs_file.parent.mkdir(parents=True, exist_ok=True)
    
    data = {}
    for name, pack in _user_packs.items():
        data[name] = {
            "description": pack.description,
            "default_role": pack.default_role,
            "roles": {
                role_name: {
                    "primary": role_config.primary,
                    "fallbacks": role_config.fallbacks,
                    "trigger": role_config.trigger,
                }
                for role_name, role_config in pack.roles.items()
            }
        }
    
    with open(packs_file, "w") as f:
        json.dump(data, f, indent=2)


def get_pack(name: str | None = None) -> ModelPack:
    """Get a model pack by name.
    
    Args:
        name: Pack name, or None for current pack
        
    Returns:
        ModelPack instance
    """
    if name is None:
        name = _current_pack_name
    
    # Check built-in packs first
    if name in DEFAULT_PACKS:
        return DEFAULT_PACKS[name]
    
    # Check user packs
    if name in _user_packs:
        return _user_packs[name]
    
    # Fallback to single pack
    logger.warning(f"Pack '{name}' not found, using 'single'")
    return DEFAULT_PACKS["single"]


def list_packs() -> list[ModelPack]:
    """List all available model packs.
    
    Returns:
        List of all built-in and user-defined packs
    """
    # Ensure user packs are loaded
    if not _user_packs:
        load_user_packs()
    
    return list(DEFAULT_PACKS.values()) + list(_user_packs.values())


def set_current_pack(name: str) -> bool:
    """Set the current model pack.
    
    Args:
        name: Pack name to use
        
    Returns:
        True if pack was set successfully, False otherwise
    """
    global _current_pack_name
    
    if name not in DEFAULT_PACKS and name not in _user_packs:
        available = ", ".join(list(DEFAULT_PACKS.keys()) + list(_user_packs.keys()))
        emit_error(f"Unknown model pack: {name}")
        emit_info(f"Available packs: {available}")
        return False
    
    _current_pack_name = name
    emit_info(f"Switched to model pack: {name}")
    return True


def get_current_pack() -> ModelPack:
    """Get the currently active model pack."""
    return get_pack(_current_pack_name)


def get_model_for_role(role: str | None = None) -> str:
    """Get the model for a specific role using current pack.
    
    Args:
        role: Role name (planner, coder, reviewer, summarizer, title)
        
    Returns:
        Model name, or "auto" to use global default
    """
    pack = get_current_pack()
    model = pack.get_model_for_role(role)
    
    # "auto" means use the global model setting
    if model == "auto":
        return get_global_model_name()
    
    return model


def create_user_pack(
    name: str,
    description: str,
    roles: dict[str, dict[str, Any]],
    default_role: str = "coder"
) -> ModelPack:
    """Create a new user-defined model pack.
    
    Args:
        name: Pack name (must be unique)
        description: Human-readable description
        roles: Dict mapping role names to role config dicts
        default_role: Default role for the pack
        
    Returns:
        The created ModelPack
    """
    if name in DEFAULT_PACKS:
        raise ValueError(f"Cannot override built-in pack: {name}")
    
    role_configs = {}
    for role_name, role_data in roles.items():
        role_configs[role_name] = RoleConfig(
            primary=role_data.get("primary", "auto"),
            fallbacks=role_data.get("fallbacks", []),
            trigger=role_data.get("trigger", "provider_failure")
        )
    
    pack = ModelPack(
        name=name,
        description=description,
        roles=role_configs,
        default_role=default_role
    )
    
    _user_packs[name] = pack
    save_user_packs()
    
    return pack


def delete_user_pack(name: str) -> bool:
    """Delete a user-defined model pack.
    
    Args:
        name: Pack name to delete
        
    Returns:
        True if deleted, False if not found or built-in
    """
    if name in DEFAULT_PACKS:
        emit_error(f"Cannot delete built-in pack: {name}")
        return False
    
    if name not in _user_packs:
        emit_error(f"Pack not found: {name}")
        return False
    
    global _current_pack_name
    
    del _user_packs[name]
    save_user_packs()
    
    # Reset to single if we just deleted the current pack
    if _current_pack_name == name:
        _current_pack_name = "single"
        emit_info("Reset to 'single' pack (previous pack was deleted)")
    
    return True


# Load user packs on module import
load_user_packs()
