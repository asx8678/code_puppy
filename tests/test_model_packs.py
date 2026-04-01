"""Tests for model packs functionality."""

import pytest

from code_puppy.model_packs import (
    RoleConfig,
    ModelPack,
    get_pack,
    list_packs,
    set_current_pack,
    get_current_pack,
    get_model_for_role,
    create_user_pack,
    delete_user_pack,
    DEFAULT_PACKS,
)


class TestRoleConfig:
    """Test RoleConfig dataclass."""
    
    def test_basic_role_config(self):
        """Test creating a basic role config."""
        config = RoleConfig(primary="gpt-4o")
        assert config.primary == "gpt-4o"
        assert config.fallbacks == []
        assert config.trigger == "provider_failure"
    
    def test_role_config_with_fallbacks(self):
        """Test role config with fallback chain."""
        config = RoleConfig(
            primary="claude-sonnet-4",
            fallbacks=["gpt-4o", "gemini-2.5-flash"],
            trigger="context_overflow"
        )
        assert config.primary == "claude-sonnet-4"
        assert config.fallbacks == ["gpt-4o", "gemini-2.5-flash"]
        assert config.trigger == "context_overflow"
    
    def test_get_model_chain(self):
        """Test getting full model chain."""
        config = RoleConfig(
            primary="model-a",
            fallbacks=["model-b", "model-c"]
        )
        chain = config.get_model_chain()
        assert chain == ["model-a", "model-b", "model-c"]


class TestModelPack:
    """Test ModelPack dataclass."""
    
    def test_basic_pack(self):
        """Test creating a basic model pack."""
        pack = ModelPack(
            name="test",
            description="Test pack",
            roles={
                "coder": RoleConfig(primary="gpt-4o"),
            },
            default_role="coder"
        )
        assert pack.name == "test"
        assert pack.description == "Test pack"
        assert pack.get_model_for_role("coder") == "gpt-4o"
    
    def test_get_model_for_role_with_fallback(self):
        """Test getting model for role with fallback chain."""
        pack = ModelPack(
            name="test",
            description="Test pack",
            roles={
                "coder": RoleConfig(primary="model-a", fallbacks=["model-b"]),
            },
            default_role="coder"
        )
        model = pack.get_model_for_role("coder")
        assert model == "model-a"
        
        chain = pack.get_fallback_chain("coder")
        assert chain == ["model-a", "model-b"]
    
    def test_get_model_for_unknown_role(self):
        """Test getting model for unknown role falls back to default."""
        pack = ModelPack(
            name="test",
            description="Test pack",
            roles={
                "coder": RoleConfig(primary="gpt-4o"),
            },
            default_role="coder"
        )
        # Should return default role's model
        model = pack.get_model_for_role("unknown_role")
        assert model == "gpt-4o"


class TestDefaultPacks:
    """Test built-in default packs."""
    
    def test_single_pack_exists(self):
        """Test single pack is defined."""
        assert "single" in DEFAULT_PACKS
        pack = DEFAULT_PACKS["single"]
        assert pack.name == "single"
        assert pack.roles["coder"].primary == "auto"
    
    def test_coding_pack_exists(self):
        """Test coding pack is defined."""
        assert "coding" in DEFAULT_PACKS
        pack = DEFAULT_PACKS["coding"]
        assert pack.name == "coding"
        assert pack.roles["coder"].primary != "auto"  # Has specific model
        assert len(pack.roles["coder"].fallbacks) > 0  # Has fallbacks
    
    def test_economical_pack_exists(self):
        """Test economical pack is defined."""
        assert "economical" in DEFAULT_PACKS
        pack = DEFAULT_PACKS["economical"]
        assert pack.name == "economical"
    
    def test_capacity_pack_exists(self):
        """Test capacity pack is defined."""
        assert "capacity" in DEFAULT_PACKS
        pack = DEFAULT_PACKS["capacity"]
        assert pack.name == "capacity"


class TestPackOperations:
    """Test pack operations."""
    
    def test_list_packs(self):
        """Test listing all packs."""
        packs = list_packs()
        pack_names = [p.name for p in packs]
        assert "single" in pack_names
        assert "coding" in pack_names
    
    def test_get_pack_by_name(self):
        """Test getting a pack by name."""
        pack = get_pack("single")
        assert pack.name == "single"
    
    def test_get_unknown_pack_returns_single(self):
        """Test getting unknown pack returns single pack."""
        pack = get_pack("nonexistent")
        assert pack.name == "single"  # Falls back to single


class TestUserPacks:
    """Test user-defined packs."""
    
    def test_create_and_delete_user_pack(self):
        """Test creating and deleting a user pack."""
        # Create a user pack
        pack = create_user_pack(
            name="test_user_pack",
            description="Test user pack",
            roles={
                "coder": {"primary": "test-model", "fallbacks": []}
            },
            default_role="coder"
        )
        assert pack.name == "test_user_pack"
        
        # Verify it can be retrieved
        retrieved = get_pack("test_user_pack")
        assert retrieved.name == "test_user_pack"
        
        # Clean up
        result = delete_user_pack("test_user_pack")
        assert result is True
        
        # Verify it's gone
        fallback = get_pack("test_user_pack")
        assert fallback.name == "single"  # Falls back
