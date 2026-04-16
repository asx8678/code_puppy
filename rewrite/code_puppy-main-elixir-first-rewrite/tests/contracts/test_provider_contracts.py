"""Contract tests for model providers.

Tests validate that providers follow code_puppy's contracts for:
- Interface requirements
- Required methods
- Configuration validation
"""

import pytest

from tests.contracts import (
    ContractViolation,
    ProviderContract,
)


class TestProviderInterfaceValidation:
    """Test provider interface contract validation."""

    def test_valid_provider_passes(self):
        """Test that a valid provider class passes validation."""

        class ValidProvider:
            def create_model(self, model_name: str, **kwargs):
                return None

            def is_available(self) -> bool:
                return True

        # Should not raise
        ProviderContract.validate_provider_interface(ValidProvider, "valid")

    def test_missing_create_model_fails(self):
        """Test that missing create_model method fails."""

        class BadProvider:
            def is_available(self) -> bool:
                return True

            # Missing create_model

        with pytest.raises(ContractViolation) as exc_info:
            ProviderContract.validate_provider_interface(BadProvider, "bad")

        assert "create_model" in str(exc_info.value)

    def test_missing_is_available_fails(self):
        """Test that missing is_available method fails."""

        class BadProvider:
            def create_model(self, model_name: str, **kwargs):
                return None

            # Missing is_available

        with pytest.raises(ContractViolation) as exc_info:
            ProviderContract.validate_provider_interface(BadProvider, "bad")

        assert "is_available" in str(exc_info.value)

    def test_non_callable_method_fails(self):
        """Test that non-callable methods are flagged."""

        class BadProvider:
            create_model = "not a function"  # Not callable

            def is_available(self) -> bool:
                return True

        with pytest.raises(ContractViolation) as exc_info:
            ProviderContract.validate_provider_interface(BadProvider, "bad")

        assert "not callable" in str(exc_info.value)


class TestModelConfigValidation:
    """Test model configuration contract validation."""

    def test_valid_config_passes(self):
        """Test that a valid model config passes."""
        config = {
            "model_name": "gpt-4",
            "provider": "openai",
            "temperature": 0.7,
        }

        # Should not raise
        ProviderContract.validate_model_config(config, "openai")

    def test_missing_model_name_fails(self):
        """Test that missing model_name fails."""
        config = {
            "provider": "openai",
        }

        with pytest.raises(ContractViolation) as exc_info:
            ProviderContract.validate_model_config(config, "openai")

        assert "model_name" in str(exc_info.value)

    def test_missing_provider_fails(self):
        """Test that missing provider fails."""
        config = {
            "model_name": "gpt-4",
        }

        with pytest.raises(ContractViolation) as exc_info:
            ProviderContract.validate_model_config(config, "openai")

        assert "provider" in str(exc_info.value)


class TestContractViolation:
    """Test ContractViolation exception."""

    def test_contract_violation_attributes(self):
        """Test that ContractViolation has correct attributes."""
        violation = ContractViolation(
            "test:component",
            "Something went wrong",
            {"detail": "info"},
        )

        assert violation.component == "test:component"
        assert violation.issue == "Something went wrong"
        assert violation.details == {"detail": "info"}
        assert "test:component" in str(violation)
        assert "Something went wrong" in str(violation)
