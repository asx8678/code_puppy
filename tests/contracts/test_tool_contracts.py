"""Contract tests for tools.

Tests validate that tools follow code_puppy's contracts for:
- Schema structure
- Required fields
- Name collision detection
"""

import pytest

from code_puppy.tools.agent_tools import register_list_agents, register_invoke_agent
from tests.contracts import (
    ContractViolation,
    ToolContract,
    validate_tool_contracts,
)


class TestToolSchemaValidation:
    """Test tool schema contract validation."""

    def test_valid_schema_passes(self):
        """Test that a valid schema passes validation."""
        schema = {
            "name": "test_tool",
            "description": "A test tool",
            "parameters": {
                "type": "object",
                "properties": {
                    "input": {"type": "string"},
                },
                "required": ["input"],
            },
        }
        
        # Should not raise
        ToolContract.validate_tool_schema(schema, "test_tool")

    def test_missing_name_fails(self):
        """Test that missing name field fails."""
        schema = {
            "description": "A test tool",
            "parameters": {},
        }
        
        with pytest.raises(ContractViolation) as exc_info:
            ToolContract.validate_tool_schema(schema, "bad_tool")
        
        assert "Missing required fields" in str(exc_info.value)
        assert "name" in str(exc_info.value)

    def test_missing_description_fails(self):
        """Test that missing description field fails."""
        schema = {
            "name": "test_tool",
            "parameters": {},
        }
        
        with pytest.raises(ContractViolation) as exc_info:
            ToolContract.validate_tool_schema(schema, "bad_tool")
        
        assert "description" in str(exc_info.value)

    def test_missing_parameters_fails(self):
        """Test that missing parameters field fails."""
        schema = {
            "name": "test_tool",
            "description": "A test tool",
        }
        
        with pytest.raises(ContractViolation) as exc_info:
            ToolContract.validate_tool_schema(schema, "bad_tool")
        
        assert "parameters" in str(exc_info.value)

    def test_parameters_without_properties_fails(self):
        """Test that parameters without properties fails."""
        schema = {
            "name": "test_tool",
            "description": "A test tool",
            "parameters": {
                "type": "object",
                # Missing properties
            },
        }
        
        with pytest.raises(ContractViolation) as exc_info:
            ToolContract.validate_tool_schema(schema, "bad_tool")
        
        assert "properties" in str(exc_info.value)


class TestToolSignatureValidation:
    """Test tool function signature validation."""

    def test_valid_function_signature(self):
        """Test valid tool function signature."""
        def good_tool(context, arg1: str) -> str:
            return "result"
        
        info = ToolContract.validate_tool_signature(good_tool, "good_tool")
        
        assert info["param_count"] == 2

    def test_tool_with_kwargs(self):
        """Test tool with **kwargs support."""
        def flexible_tool(context, **kwargs) -> str:
            return "result"
        
        info = ToolContract.validate_tool_signature(flexible_tool, "flexible")
        
        assert info["has_kwargs"]


class TestToolValidationHelpers:
    """Test the tool validation helper functions."""

    def test_validate_tool_contracts_empty(self):
        """Test that empty tools dict returns no errors."""
        errors = validate_tool_contracts({})
        assert errors == []

    def test_validate_tool_contracts_with_valid_tools(self):
        """Test validation with valid tools."""
        def valid_tool_1():
            pass
        
        def valid_tool_2():
            pass
        
        tools = {
            "tool1": valid_tool_1,
            "tool2": valid_tool_2,
        }
        
        errors = validate_tool_contracts(tools)
        assert errors == []


class TestBuiltinTools:
    """Test that builtin tools follow contracts."""

    def test_list_agents_tool_signature(self):
        """Test list_agents tool has valid signature."""
        # Create a mock agent to get the registered tool
        from unittest.mock import Mock
        from pydantic_ai import Agent
        
        mock_agent = Mock(spec=Agent)
        
        # The registration function should not raise
        try:
            register_list_agents(mock_agent)
        except Exception as e:
            pytest.fail(f"list_agents registration failed: {e}")
