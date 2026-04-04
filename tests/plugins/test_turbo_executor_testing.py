"""Unit tests for the Turbo Executor testing operations.

Tests the run_tests and discover_tests operations including:
- Operation parsing and results
- Pytest output parsing
- Test discovery parsing
- Result formatting
"""

from __future__ import annotations

import pytest

from code_puppy.plugins.turbo_executor.models import (
    Operation,
    OperationType,
    Plan,
)
from code_puppy.plugins.turbo_executor.orchestrator import TurboOrchestrator


class TestRunTestsOperation:
    """Test run_tests operation execution and result parsing."""

    @pytest.fixture
    def orchestrator(self):
        """Create a TurboOrchestrator instance."""
        return TurboOrchestrator(prefer_native_python=True)

    @pytest.mark.asyncio
    async def test_run_tests_operation_type(self, orchestrator):
        """Test that run_tests operation type is handled."""
        plan = Plan(
            id="test-run",
            operations=[
                Operation(
                    type=OperationType.RUN_TESTS,
                    args={"test_path": "tests/plugins", "runner": "pytest", "verbose": False},
                )
            ],
        )

        result = await orchestrator.execute(plan)

        # Should complete (may have errors but operation should run)
        assert result.plan_id == "test-run"
        assert len(result.operation_results) == 1
        op_result = result.operation_results[0]
        assert op_result.type == OperationType.RUN_TESTS

    @pytest.mark.asyncio
    async def test_run_tests_pytest_runner(self, orchestrator):
        """Test run_tests with pytest runner."""
        plan = Plan(
            id="pytest-test",
            operations=[
                Operation(
                    type=OperationType.RUN_TESTS,
                    args={
                        "test_path": "tests/plugins/test_turbo_executor.py",
                        "runner": "pytest",
                        "verbose": False,
                    },
                )
            ],
        )

        result = await orchestrator.execute(plan)
        op_result = result.operation_results[0]

        # Check result structure
        assert "test_path" in op_result.data
        assert "runner" in op_result.data
        assert "command" in op_result.data
        assert "exit_code" in op_result.data
        assert "output" in op_result.data

    @pytest.mark.asyncio
    async def test_run_tests_result_structure(self, orchestrator):
        """Test that run_tests result has all expected fields."""
        plan = Plan(
            id="result-structure-test",
            operations=[
                Operation(
                    type=OperationType.RUN_TESTS,
                    args={"test_path": "tests/plugins/test_turbo_executor.py::TestPlanModels::test_operation_creation", "runner": "pytest"},
                )
            ],
        )

        result = await orchestrator.execute(plan)
        op_result = result.operation_results[0]
        data = op_result.data

        # Check all expected fields
        assert "test_path" in data
        assert "runner" in data
        assert "command" in data
        assert "exit_code" in data
        assert "output" in data
        assert "passed" in data
        assert "failed" in data
        assert "skipped" in data
        assert "total" in data
        assert "duration_seconds" in data
        assert "success" in data
        assert "source" in data


class TestDiscoverTestsOperation:
    """Test discover_tests operation execution and result parsing."""

    @pytest.fixture
    def orchestrator(self):
        """Create a TurboOrchestrator instance."""
        return TurboOrchestrator(prefer_native_python=True)

    @pytest.mark.asyncio
    async def test_discover_tests_operation_type(self, orchestrator):
        """Test that discover_tests operation type is handled."""
        plan = Plan(
            id="test-discover",
            operations=[
                Operation(
                    type=OperationType.DISCOVER_TESTS,
                    args={"test_path": "tests/plugins", "runner": "pytest"},
                )
            ],
        )

        result = await orchestrator.execute(plan)

        # Should complete
        assert result.plan_id == "test-discover"
        assert len(result.operation_results) == 1
        op_result = result.operation_results[0]
        assert op_result.type == OperationType.DISCOVER_TESTS

    @pytest.mark.asyncio
    async def test_discover_tests_result_structure(self, orchestrator):
        """Test that discover_tests result has all expected fields."""
        plan = Plan(
            id="discover-structure-test",
            operations=[
                Operation(
                    type=OperationType.DISCOVER_TESTS,
                    args={"test_path": "tests/plugins", "runner": "pytest"},
                )
            ],
        )

        result = await orchestrator.execute(plan)
        op_result = result.operation_results[0]
        data = op_result.data

        # Check all expected fields
        assert "test_path" in data
        assert "runner" in data
        assert "pattern" in data
        assert "command" in data
        assert "exit_code" in data
        assert "output" in data
        assert "test_files" in data
        assert "test_count" in data
        assert "success" in data
        assert "source" in data

    @pytest.mark.asyncio
    async def test_discover_tests_with_pattern(self, orchestrator):
        """Test discover_tests with pattern filtering."""
        plan = Plan(
            id="pattern-test",
            operations=[
                Operation(
                    type=OperationType.DISCOVER_TESTS,
                    args={
                        "test_path": "tests/plugins",
                        "runner": "pytest",
                        "pattern": "test_turbo",
                    },
                )
            ],
        )

        result = await orchestrator.execute(plan)
        op_result = result.operation_results[0]

        # Check that pattern was passed
        assert "pattern" in op_result.data


class TestPytestOutputParsing:
    """Test the pytest output parsing methods."""

    @pytest.fixture
    def orchestrator(self):
        """Create a TurboOrchestrator instance."""
        return TurboOrchestrator()

    def test_parse_pytest_output_passed(self, orchestrator):
        """Test parsing pytest output with passed tests."""
        output = """
        ============================= test session starts ==============================
        platform darwin -- Python 3.14.3, pytest-9.0.2, pluggy-1.6.0
        rootdir: /Users/adam2/projects/code_puppy
        configfile: pyproject.toml
        collecting ... collected 5 items

        tests/test_example.py::test_one PASSED                                   [ 20%]
        tests/test_example.py::test_two PASSED                                   [ 40%]
        tests/test_example.py::test_three PASSED                                 [ 60%]
        tests/test_example.py::test_four PASSED                                   [ 80%]
        tests/test_example.py::test_five PASSED                                   [100%]

        ============================== 5 passed in 0.15s ===============================
        """

        result = orchestrator._parse_pytest_output(output, 0)

        assert result["passed"] == 5
        assert result["failed"] == 0
        assert result["skipped"] == 0
        assert result["errors"] == 0
        assert result["total"] == 5
        assert result["success"] is True
        assert result["duration_seconds"] == 0.15

    def test_parse_pytest_output_with_failures(self, orchestrator):
        """Test parsing pytest output with failed tests."""
        output = """
        ============================= test session starts ==============================
        platform darwin -- Python 3.14.3, pytest-9.0.2
        collected 10 items

        tests/test_example.py::test_one PASSED                                   [ 10%]
        tests/test_example.py::test_two FAILED                                   [ 20%]
        tests/test_example.py::test_three PASSED                                 [ 30%]
        tests/test_example.py::test_four FAILED                                   [ 40%]

        ============================== 2 failed, 8 passed in 0.25s ======================
        """

        result = orchestrator._parse_pytest_output(output, 1)

        assert result["passed"] == 8
        assert result["failed"] == 2
        assert result["total"] == 10
        assert result["success"] is False  # Failed tests mean not successful

    def test_parse_pytest_output_with_skipped(self, orchestrator):
        """Test parsing pytest output with skipped tests."""
        output = """
        ============================= test session starts ==============================
        collected 15 items

        tests/test_example.py::test_one PASSED                                   [  6%]
        tests/test_example.py::test_two SKIPPED                                  [ 13%]
        tests/test_example.py::test_three PASSED                                 [ 20%]

        ===================== 12 passed, 3 skipped in 0.35s =============================
        """

        result = orchestrator._parse_pytest_output(output, 0)

        assert result["passed"] == 12
        assert result["skipped"] == 3
        assert result["failed"] == 0
        assert result["total"] == 15
        assert result["success"] is True

    def test_parse_pytest_output_with_errors(self, orchestrator):
        """Test parsing pytest output with test errors."""
        output = """
        ============================= test session starts ==============================
        collected 8 items

        tests/test_example.py::test_one PASSED                                   [ 12%]
        tests/test_example.py::test_two ERROR                                    [ 25%]
        tests/test_example.py::test_three PASSED                                 [ 37%]

        ================= 6 passed, 2 errors in 0.45s ================================
        """

        result = orchestrator._parse_pytest_output(output, 1)

        assert result["passed"] == 6
        assert result["errors"] == 2
        assert result["failed"] == 0
        assert result["total"] == 8
        assert result["success"] is False

    def test_parse_pytest_output_empty(self, orchestrator):
        """Test parsing empty pytest output."""
        result = orchestrator._parse_pytest_output("", 0)

        assert result["passed"] == 0
        assert result["failed"] == 0
        assert result["skipped"] == 0
        assert result["errors"] == 0
        assert result["total"] == 0
        assert result["success"] is True

    def test_parse_pytest_output_no_summary(self, orchestrator):
        """Test parsing pytest output without summary line."""
        output = """
        Some random output without summary
        """

        result = orchestrator._parse_pytest_output(output, 0)

        assert result["passed"] == 0
        assert result["failed"] == 0
        # Success is False because no tests were found (total=0)
        assert result["success"] is False


class TestPytestDiscoveryParsing:
    """Test the pytest discovery parsing methods."""

    @pytest.fixture
    def orchestrator(self):
        """Create a TurboOrchestrator instance."""
        return TurboOrchestrator()

    def test_parse_pytest_discovery_basic(self, orchestrator):
        """Test basic pytest discovery output parsing."""
        output = """
        ============================= test session starts ==============================
        platform darwin -- Python 3.14.3, pytest-9.0.2
        rootdir: /Users/adam2/projects/code_puppy
        configfile: pyproject.toml
        collected 5 items
        <Dir tests>
          <Dir plugins>
            <Module test_turbo_executor.py>
              <Function test_operation_creation>
              <Function test_operation_defaults>
            </Module>
          </Dir>
        </Dir>

        ============================= 5 tests found =============================
        """

        result = orchestrator._parse_pytest_discovery(output, 0)

        assert result["test_count"] == 5
        assert "test_files" in result
        assert "test_turbo_executor.py" in result["test_files"]
        assert "test_items" in result
        assert len(result["test_items"]) >= 2

    def test_parse_pytest_discovery_with_dirs(self, orchestrator):
        """Test discovery parsing with directory structure."""
        output = """
        <Dir tests>
          <Dir plugins>
            <Module test_one.py>
              <Function test_a>
            </Module>
            <Module test_two.py>
              <Function test_b>
              <Function test_c>
            </Module>
          </Dir>
          <Dir agents>
            <Module test_agent.py>
              <Function test_agent_method>
            </Module>
          </Dir>
        </Dir>
        """

        result = orchestrator._parse_pytest_discovery(output, 0)

        # Should find modules
        assert any("test_one.py" in f for f in result["test_files"])
        assert any("test_two.py" in f for f in result["test_files"])
        assert any("test_agent.py" in f for f in result["test_files"])

        # Should find test items
        test_names = [item["name"] for item in result["test_items"]]
        assert "test_a" in test_names
        assert "test_b" in test_names
        assert "test_c" in test_names

    def test_parse_pytest_discovery_empty(self, orchestrator):
        """Test parsing empty discovery output."""
        result = orchestrator._parse_pytest_discovery("", 0)

        assert result["test_count"] == 0
        assert result["test_files"] == []
        assert result["test_items"] == []
        assert result["test_modules"] == []

    def test_parse_pytest_discovery_no_collected_line(self, orchestrator):
        """Test discovery parsing without 'collected' line."""
        output = """
        <Module test_example.py>
          <Function test_one>
          <Function test_two>
        </Module>
        """

        result = orchestrator._parse_pytest_discovery(output, 0)

        # Should count test items even without "collected" line
        assert result["test_count"] == 2
        assert len(result["test_items"]) == 2

    def test_parse_pytest_discovery_with_test_class(self, orchestrator):
        """Test discovery parsing with test classes."""
        output = """
        <Module test_class.py>
          <TestClass TestExample>
            <Function test_method_one>
            <Function test_method_two>
          </TestClass>
        </Module>
        """

        result = orchestrator._parse_pytest_discovery(output, 0)

        # Should find test items inside classes
        test_names = [item["name"] for item in result["test_items"]]
        assert "test_method_one" in test_names
        assert "test_method_two" in test_names


class TestTestingOperationValidation:
    """Test validation for testing operations."""

    def test_run_tests_validates_runner(self):
        """Test that run_tests validates the runner argument."""
        orch = TurboOrchestrator()

        # Valid runners
        valid_plan = Plan(
            id="valid",
            operations=[
                Operation(type=OperationType.RUN_TESTS, args={"runner": "pytest"}),
                Operation(type=OperationType.RUN_TESTS, args={"runner": "unittest"}),
                Operation(type=OperationType.RUN_TESTS, args={"runner": "tox"}),
                Operation(type=OperationType.RUN_TESTS, args={"runner": "nox"}),
            ],
        )
        errors = orch.validate_plan(valid_plan)
        assert len(errors) == 0

        # Invalid runner
        invalid_plan = Plan(
            id="invalid",
            operations=[Operation(type=OperationType.RUN_TESTS, args={"runner": "invalid"})],
        )
        errors = orch.validate_plan(invalid_plan)
        assert any("unsupported" in e.lower() for e in errors)

    def test_discover_tests_validates_runner(self):
        """Test that discover_tests validates the runner argument."""
        orch = TurboOrchestrator()

        # Valid runners
        valid_plan = Plan(
            id="valid",
            operations=[
                Operation(type=OperationType.DISCOVER_TESTS, args={"runner": "pytest"}),
                Operation(type=OperationType.DISCOVER_TESTS, args={"runner": "unittest"}),
            ],
        )
        errors = orch.validate_plan(valid_plan)
        assert len(errors) == 0

        # Invalid runner
        invalid_plan = Plan(
            id="invalid",
            operations=[Operation(type=OperationType.DISCOVER_TESTS, args={"runner": "nose"})],
        )
        errors = orch.validate_plan(invalid_plan)
        assert any("unsupported" in e.lower() for e in errors)

    def test_run_tests_default_runner(self):
        """Test that run_tests defaults to pytest."""
        op = Operation(type=OperationType.RUN_TESTS, args={})
        assert op.args["runner"] == "pytest"

    def test_discover_tests_default_runner(self):
        """Test that discover_tests defaults to pytest."""
        op = Operation(type=OperationType.DISCOVER_TESTS, args={})
        assert op.args["runner"] == "pytest"


class TestTestingIntegration:
    """Integration tests for testing operations."""

    @pytest.mark.asyncio
    async def test_run_and_discover_in_same_plan(self):
        """Test running both run_tests and discover_tests in one plan."""
        orch = TurboOrchestrator(prefer_native_python=True)

        plan = Plan(
            id="combined-test",
            operations=[
                Operation(
                    type=OperationType.DISCOVER_TESTS,
                    args={"test_path": "tests/plugins", "runner": "pytest"},
                    priority=1,
                ),
                Operation(
                    type=OperationType.RUN_TESTS,
                    args={
                        "test_path": "tests/plugins/test_turbo_executor.py::TestPlanModels::test_operation_creation",
                        "runner": "pytest",
                    },
                    priority=2,
                ),
            ],
        )

        result = await orch.execute(plan)

        # Should complete with both operations
        assert len(result.operation_results) == 2
        assert result.operation_results[0].type == OperationType.DISCOVER_TESTS
        assert result.operation_results[1].type == OperationType.RUN_TESTS
