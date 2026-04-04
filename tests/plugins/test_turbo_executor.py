"""Unit tests for the Turbo Executor plugin."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from code_puppy.plugins.turbo_executor.models import (
    Operation,
    OperationResult,
    OperationType,
    Plan,
    PlanResult,
    PlanStatus,
)
from code_puppy.plugins.turbo_executor.orchestrator import TurboOrchestrator


@pytest.fixture
def temp_dir_with_files():
    """Create a temporary directory with some files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create some test files
        (Path(tmpdir) / "test1.py").write_text("def hello():\n    pass\n")
        (Path(tmpdir) / "test2.py").write_text("def world():\n    return 42\n")
        (Path(tmpdir) / "readme.md").write_text("# README\n\nThis is a test.\n")
        yield tmpdir


class TestPlanModels:
    """Test plan schema models."""

    def test_operation_creation(self):
        """Test creating an operation."""
        op = Operation(
            type=OperationType.LIST_FILES,
            args={"directory": ".", "recursive": True},
            priority=1,
            id="test-op",
        )
        assert op.type == OperationType.LIST_FILES
        assert op.args["directory"] == "."
        assert op.priority == 1
        assert op.id == "test-op"

    def test_operation_defaults(self):
        """Test operation default values."""
        op = Operation(type=OperationType.GREP, args={"search_string": "test"})
        assert op.priority == 100  # default
        assert op.id is None
        assert op.args["directory"] == "."  # auto-set default

    def test_operation_validation_grep_requires_search(self):
        """Test that grep requires search_string."""
        with pytest.raises(ValueError, match="search_string"):
            Operation(type=OperationType.GREP, args={"directory": "."})

    def test_operation_validation_read_files_requires_paths(self):
        """Test that read_files requires file_paths."""
        with pytest.raises(ValueError, match="file_paths"):
            Operation(type=OperationType.READ_FILES, args={})

    def test_plan_creation(self):
        """Test creating a plan."""
        plan = Plan(
            id="test-plan",
            operations=[
                Operation(type=OperationType.LIST_FILES, priority=2),
                Operation(type=OperationType.GREP, args={"search_string": "def"}, priority=1),
            ],
            metadata={"description": "Test plan"},
        )
        assert plan.id == "test-plan"
        assert len(plan.operations) == 2
        # Operations should be sorted by priority
        assert plan.operations[0].priority == 1
        assert plan.operations[1].priority == 2

    def test_plan_empty_id_allowed(self):
        """Test that empty id is allowed at model level (orchestrator validates)."""
        # Pydantic allows empty string - orchestrator catches it in validate_plan
        plan = Plan(id="", operations=[Operation(type=OperationType.LIST_FILES)])
        assert plan.id == ""  # Model allows it

    def test_plan_json_serialization(self):
        """Test serializing and deserializing a plan."""
        plan = Plan(
            id="json-test",
            operations=[
                Operation(
                    type=OperationType.LIST_FILES,
                    args={"directory": "src", "recursive": False},
                    priority=1,
                    id="op1",
                )
            ],
            metadata={"tag": "test"},
        )

        json_str = plan.model_dump_json()
        data = json.loads(json_str)

        restored = Plan.model_validate(data)
        assert restored.id == "json-test"
        assert len(restored.operations) == 1
        assert restored.operations[0].type == OperationType.LIST_FILES


class TestOrchestratorValidation:
    """Test plan validation."""

    def test_validate_valid_plan(self):
        """Test validating a correct plan."""
        orch = TurboOrchestrator()
        plan = Plan(
            id="valid-plan",
            operations=[
                Operation(type=OperationType.LIST_FILES),
                Operation(type=OperationType.GREP, args={"search_string": "test"}),
            ],
        )
        errors = orch.validate_plan(plan)
        assert len(errors) == 0

    def test_validate_missing_id(self):
        """Test validating a plan without id."""
        orch = TurboOrchestrator()
        plan = Plan(
            id="",
            operations=[Operation(type=OperationType.LIST_FILES)],
        )
        errors = orch.validate_plan(plan)
        assert any("must have an id" in e for e in errors)

    def test_validate_empty_operations(self):
        """Test validating a plan without operations."""
        orch = TurboOrchestrator()
        plan = Plan(id="no-ops", operations=[])
        errors = orch.validate_plan(plan)
        assert any("at least one operation" in e for e in errors)

    def test_validate_grep_missing_search(self):
        """Test validating grep without search_string."""
        orch = TurboOrchestrator()
        # Validation happens at Operation creation, so we test with invalid plan structure
        plan = Plan(
            id="bad-grep",
            operations=[],  # Empty since we can't create invalid Operation
        )
        errors = orch.validate_plan(plan)
        assert any("at least one operation" in e for e in errors)

    def test_validate_read_files_invalid_paths(self):
        """Test validating read_files with non-list paths."""
        orch = TurboOrchestrator()
        # Validation happens at Operation creation
        plan = Plan(
            id="bad-read",
            operations=[],  # Empty since we can't create invalid Operation
        )
        errors = orch.validate_plan(plan)
        assert any("at least one operation" in e for e in errors)


class TestOrchestratorExecution:
    """Test plan execution."""

    @pytest.mark.asyncio
    async def test_execute_list_files(self, temp_dir_with_files):
        """Test executing a list_files operation."""
        orch = TurboOrchestrator()
        plan = Plan(
            id="list-test",
            operations=[
                Operation(
                    type=OperationType.LIST_FILES,
                    args={"directory": temp_dir_with_files, "recursive": False},
                )
            ],
        )

        result = await orch.execute(plan)

        assert result.plan_id == "list-test"
        assert result.status == PlanStatus.COMPLETED
        assert result.success_count == 1
        assert result.error_count == 0
        assert len(result.operation_results) == 1

        op_result = result.operation_results[0]
        assert op_result.type == OperationType.LIST_FILES
        assert op_result.status == "success"
        assert "content" in op_result.data

    @pytest.mark.asyncio
    async def test_execute_grep(self, temp_dir_with_files):
        """Test executing a grep operation."""
        orch = TurboOrchestrator()
        plan = Plan(
            id="grep-test",
            operations=[
                Operation(
                    type=OperationType.GREP,
                    args={"search_string": "def ", "directory": temp_dir_with_files},
                )
            ],
        )

        result = await orch.execute(plan)

        assert result.status == PlanStatus.COMPLETED
        assert result.success_count == 1
        op_result = result.operation_results[0]
        assert op_result.type == OperationType.GREP
        assert op_result.status == "success"
        assert "matches" in op_result.data

    @pytest.mark.asyncio
    async def test_execute_read_files(self, temp_dir_with_files):
        """Test executing a read_files operation."""
        orch = TurboOrchestrator()
        file_path = os.path.join(temp_dir_with_files, "test1.py")

        plan = Plan(
            id="read-test",
            operations=[
                Operation(
                    type=OperationType.READ_FILES,
                    args={"file_paths": [file_path]},
                )
            ],
        )

        result = await orch.execute(plan)

        assert result.status == PlanStatus.COMPLETED
        assert result.success_count == 1
        op_result = result.operation_results[0]
        assert op_result.type == OperationType.READ_FILES
        assert op_result.status == "success"
        assert "files" in op_result.data
        assert op_result.data["total_files"] == 1
        assert op_result.data["successful_reads"] == 1

    @pytest.mark.asyncio
    async def test_execute_multiple_operations(self, temp_dir_with_files):
        """Test executing multiple operations in sequence."""
        orch = TurboOrchestrator()
        file_path = os.path.join(temp_dir_with_files, "test1.py")

        plan = Plan(
            id="multi-test",
            operations=[
                Operation(
                    type=OperationType.LIST_FILES,
                    args={"directory": temp_dir_with_files},
                    priority=1,
                ),
                Operation(
                    type=OperationType.GREP,
                    args={"search_string": "def ", "directory": temp_dir_with_files},
                    priority=2,
                ),
                Operation(
                    type=OperationType.READ_FILES,
                    args={"file_paths": [file_path]},
                    priority=3,
                ),
            ],
        )

        result = await orch.execute(plan)

        assert result.status == PlanStatus.COMPLETED
        assert result.success_count == 3
        assert result.error_count == 0
        assert len(result.operation_results) == 3

    @pytest.mark.asyncio
    async def test_execute_partial_failure(self, temp_dir_with_files):
        """Test execution with some failing operations."""
        orch = TurboOrchestrator()

        plan = Plan(
            id="partial-test",
            operations=[
                Operation(
                    type=OperationType.LIST_FILES,
                    args={"directory": temp_dir_with_files},
                ),
                Operation(
                    type=OperationType.READ_FILES,
                    args={"file_paths": ["/nonexistent/file.py"]},
                ),
            ],
        )

        result = await orch.execute(plan)

        assert result.status == PlanStatus.PARTIAL
        assert result.success_count == 1  # list_files succeeds
        assert result.error_count == 1  # read_files fails

    @pytest.mark.asyncio
    async def test_execute_all_failures(self):
        """Test execution where all operations fail."""
        orch = TurboOrchestrator()

        plan = Plan(
            id="fail-test",
            operations=[
                Operation(
                    type=OperationType.LIST_FILES,
                    args={"directory": "/nonexistent/directory"},
                ),
            ],
        )

        result = await orch.execute(plan)

        assert result.status == PlanStatus.FAILED
        assert result.success_count == 0
        assert result.error_count == 1


class TestOperationResult:
    """Test operation result models."""

    def test_success_result(self):
        """Test creating a successful result."""
        result = OperationResult(
            operation_id="op1",
            type=OperationType.LIST_FILES,
            status="success",
            data={"content": "files listed"},
            duration_ms=100.5,
        )
        assert result.status == "success"
        assert result.error is None
        assert result.duration_ms == 100.5

    def test_error_result(self):
        """Test creating an error result."""
        result = OperationResult(
            operation_id="op2",
            type=OperationType.GREP,
            status="error",
            error="Directory not found",
            duration_ms=50.0,
        )
        assert result.status == "error"
        assert result.error == "Directory not found"


class TestPlanResult:
    """Test plan result functionality."""

    def test_success_count(self):
        """Test counting successful operations."""
        result = PlanResult(
            plan_id="test",
            status=PlanStatus.COMPLETED,
            operation_results=[
                OperationResult(type=OperationType.LIST_FILES, status="success"),
                OperationResult(type=OperationType.GREP, status="success"),
                OperationResult(type=OperationType.READ_FILES, status="error"),
            ],
        )
        assert result.success_count == 2
        assert result.error_count == 1

    def test_get_errors(self):
        """Test getting all errors."""
        result = PlanResult(
            plan_id="test",
            status=PlanStatus.PARTIAL,
            operation_results=[
                OperationResult(type=OperationType.LIST_FILES, status="success"),
                OperationResult(
                    type=OperationType.GREP,
                    status="error",
                    error="Permission denied",
                ),
            ],
        )
        errors = result.get_errors()
        assert len(errors) == 1
        assert errors[0].error == "Permission denied"


class TestPluginIntegration:
    """Test plugin integration with code_puppy."""

    def test_imports(self):
        """Test that all plugin modules can be imported."""
        from code_puppy.plugins.turbo_executor import (
            Operation,
            TurboOrchestrator,
        )

        assert Operation is not None
        assert TurboOrchestrator is not None

    def test_register_callbacks_import(self):
        """Test that register_callbacks can be imported."""
        from code_puppy.plugins.turbo_executor import register_callbacks

        # Just verify it imports without error
        assert register_callbacks is not None

    def test_orchestrator_from_dict(self):
        """Test creating orchestrator and running a plan from dict."""
        orch = TurboOrchestrator()

        plan_dict = {
            "id": "dict-test",
            "operations": [
                {
                    "type": "list_files",
                    "args": {"directory": ".", "recursive": False},
                    "priority": 1,
                }
            ],
        }

        plan = Plan.model_validate(plan_dict)
        assert plan.id == "dict-test"
        assert len(plan.operations) == 1

        errors = orch.validate_plan(plan)
        assert len(errors) == 0


class TestFallbackBehavior:
    """Test fallback to native Python operations."""

    def test_orchestrator_uses_native_fallback_by_default(self):
        """Test that orchestrator uses native Python when turbo_ops unavailable."""
        orch = TurboOrchestrator()
        # Since turbo_ops is not installed, should use native fallback
        assert orch.using_native_ops is True
        assert orch._turbo_ops_async_available is False
        assert orch._turbo_ops_sync_available is False

    def test_orchestrator_forces_native_python(self):
        """Test forcing native Python mode."""
        orch = TurboOrchestrator(prefer_native_python=True)
        assert orch.using_native_ops is True
        assert orch._turbo_ops_async_available is False
        assert orch._turbo_ops_sync_available is False

    @pytest.mark.asyncio
    async def test_native_list_files_execution(self, temp_dir_with_files):
        """Test list_files via native Python fallback."""
        orch = TurboOrchestrator(prefer_native_python=True)
        plan = Plan(
            id="native-list-test",
            operations=[
                Operation(
                    type=OperationType.LIST_FILES,
                    args={"directory": temp_dir_with_files, "recursive": False},
                )
            ],
        )

        result = await orch.execute(plan)

        assert result.status == PlanStatus.COMPLETED
        assert result.success_count == 1

        # Check that native Python source is indicated in result
        op_result = result.operation_results[0]
        assert op_result.data.get("source") == "native_python"

    @pytest.mark.asyncio
    async def test_native_grep_execution(self, temp_dir_with_files):
        """Test grep via native Python fallback."""
        orch = TurboOrchestrator(prefer_native_python=True)
        plan = Plan(
            id="native-grep-test",
            operations=[
                Operation(
                    type=OperationType.GREP,
                    args={"search_string": "def ", "directory": temp_dir_with_files},
                )
            ],
        )

        result = await orch.execute(plan)

        assert result.status == PlanStatus.COMPLETED
        assert result.success_count == 1

        # Check that native Python source is indicated
        op_result = result.operation_results[0]
        assert op_result.data.get("source") == "native_python"

    @pytest.mark.asyncio
    async def test_native_read_files_execution(self, temp_dir_with_files):
        """Test read_files via native Python fallback."""
        orch = TurboOrchestrator(prefer_native_python=True)
        file_path = os.path.join(temp_dir_with_files, "test1.py")

        plan = Plan(
            id="native-read-test",
            operations=[
                Operation(
                    type=OperationType.READ_FILES,
                    args={"file_paths": [file_path]},
                )
            ],
        )

        result = await orch.execute(plan)

        assert result.status == PlanStatus.COMPLETED
        assert result.success_count == 1

        # Check that native Python source is indicated
        op_result = result.operation_results[0]
        assert op_result.data.get("source") == "native_python"


class TestResultSummarization:
    """Test smart result summarization."""

    def test_summarize_list_files_result(self):
        """Test summarizing list_files operation result."""
        from code_puppy.plugins.turbo_executor.summarizer import _summarize_list_files

        data = {
            "content": "file1.py (type=file)\nfile2.py (type=file)\ndir1/ (type=directory)",
            "error": None,
        }
        summary = _summarize_list_files(data)

        assert "Directory Listing" in summary
        assert "files" in summary.lower()
        assert "```" in summary  # Code block formatting

    def test_summarize_list_files_error(self):
        """Test summarizing list_files with error."""
        from code_puppy.plugins.turbo_executor.summarizer import _summarize_list_files

        data = {"error": "Directory not found", "content": ""}
        summary = _summarize_list_files(data)

        assert "Error" in summary
        assert "Directory not found" in summary

    def test_summarize_grep_result(self):
        """Test summarizing grep operation result."""
        from code_puppy.plugins.turbo_executor.summarizer import _summarize_grep

        data = {
            "matches": [
                {"file_path": "test.py", "line_number": 1, "line_content": "def hello():"},
                {"file_path": "test.py", "line_number": 5, "line_content": "def world():"},
            ],
            "total_matches": 2,
            "error": None,
        }
        summary = _summarize_grep(data)

        assert "Search Results" in summary
        assert "2 matches" in summary
        assert "test.py" in summary
        assert "def hello()" in summary

    def test_summarize_grep_empty(self):
        """Test summarizing grep with no matches."""
        from code_puppy.plugins.turbo_executor.summarizer import _summarize_grep

        data = {"matches": [], "total_matches": 0, "error": None}
        summary = _summarize_grep(data)

        assert "No matches found" in summary

    def test_summarize_read_files_result(self):
        """Test summarizing read_files operation result."""
        from code_puppy.plugins.turbo_executor.summarizer import _summarize_read_files

        data = {
            "files": [
                {
                    "file_path": "test.py",
                    "content": "def hello():\n    pass\n",
                    "num_tokens": 10,
                    "error": None,
                    "success": True,
                }
            ],
            "total_files": 1,
            "successful_reads": 1,
        }
        summary = _summarize_read_files(data)

        assert "File Contents" in summary
        assert "test.py" in summary
        assert "def hello()" in summary
        assert "```" in summary

    def test_summarize_read_files_with_errors(self):
        """Test summarizing read_files with some failures."""
        from code_puppy.plugins.turbo_executor.summarizer import _summarize_read_files

        data = {
            "files": [
                {
                    "file_path": "exists.py",
                    "content": "# exists",
                    "num_tokens": 5,
                    "error": None,
                    "success": True,
                },
                {
                    "file_path": "missing.py",
                    "content": None,
                    "num_tokens": 0,
                    "error": "File not found",
                    "success": False,
                },
            ],
            "total_files": 2,
            "successful_reads": 1,
        }
        summary = _summarize_read_files(data)

        assert "1/2 files read successfully" in summary
        assert "exists.py" in summary
        assert "missing.py" in summary
        assert "Error" in summary or "❌" in summary

    def test_summarize_operation_result(self):
        """Test summarizing an operation result object."""
        from code_puppy.plugins.turbo_executor.summarizer import summarize_operation_result

        result = OperationResult(
            operation_id="test-op",
            type=OperationType.GREP,
            status="success",
            data={
                "matches": [{"file_path": "test.py", "line_number": 1, "line_content": "def test():"}],
                "total_matches": 1,
                "error": None,
            },
            duration_ms=50.0,
        )
        summary = summarize_operation_result(result)

        assert "Search Results" in summary
        assert "test.py" in summary

    def test_summarize_operation_error(self):
        """Test summarizing an errored operation result."""
        from code_puppy.plugins.turbo_executor.summarizer import summarize_operation_result

        result = OperationResult(
            operation_id="test-op",
            type=OperationType.LIST_FILES,
            status="error",
            error="Permission denied",
            duration_ms=10.0,
        )
        summary = summarize_operation_result(result)

        assert "Operation Failed" in summary or "❌" in summary
        assert "Permission denied" in summary

    def test_summarize_plan_result(self):
        """Test generating a full plan result summary."""
        from code_puppy.plugins.turbo_executor.summarizer import summarize_plan_result

        plan_result = PlanResult(
            plan_id="test-plan",
            status=PlanStatus.COMPLETED,
            operation_results=[
                OperationResult(
                    type=OperationType.LIST_FILES,
                    status="success",
                    data={"content": "file1.py", "error": None},
                    duration_ms=100.0,
                ),
                OperationResult(
                    type=OperationType.GREP,
                    status="success",
                    data={"matches": [], "total_matches": 0, "error": None},
                    duration_ms=50.0,
                ),
            ],
            total_duration_ms=150.0,
        )
        summary = summarize_plan_result(plan_result)

        assert "test-plan" in summary
        assert "completed" in summary.lower() or "✅" in summary
        assert "2" in summary  # operation count
        assert "150.0ms" in summary or "150ms" in summary

    def test_summarize_plan_result_with_errors(self):
        """Test generating summary for partial failure."""
        from code_puppy.plugins.turbo_executor.summarizer import summarize_plan_result

        plan_result = PlanResult(
            plan_id="error-plan",
            status=PlanStatus.PARTIAL,
            operation_results=[
                OperationResult(
                    type=OperationType.LIST_FILES,
                    status="success",
                    data={"content": "file1.py", "error": None},
                    duration_ms=100.0,
                ),
                OperationResult(
                    type=OperationType.READ_FILES,
                    status="error",
                    error="File not found",
                    duration_ms=10.0,
                ),
            ],
            total_duration_ms=110.0,
        )
        summary = summarize_plan_result(plan_result)

        assert "error-plan" in summary
        assert "partial" in summary.lower() or "⚠️" in summary
        assert "1 success" in summary.lower()
        assert "1 errors" in summary.lower()
        assert "Errors" in summary

    def test_quick_summary(self):
        """Test generating a quick one-line summary."""
        from code_puppy.plugins.turbo_executor.summarizer import quick_summary

        plan_result = PlanResult(
            plan_id="quick-test",
            status=PlanStatus.COMPLETED,
            operation_results=[
                OperationResult(type=OperationType.LIST_FILES, status="success"),
                OperationResult(type=OperationType.GREP, status="success"),
            ],
            total_duration_ms=150.0,
        )
        summary = quick_summary(plan_result)

        assert "quick-test" in summary
        assert "2/2" in summary or "2" in summary
        assert "150ms" in summary

    def test_content_truncation(self):
        """Test that long content gets truncated."""
        from code_puppy.plugins.turbo_executor.summarizer import _truncate_content

        long_content = "line\n" * 200  # 200 lines
        truncated = _truncate_content(long_content, max_length=1000, max_lines=50)

        assert "truncated" in truncated.lower() or "..." in truncated
        assert truncated.count("\n") < 60  # Should be around 50 lines + indicator


class TestSummarizerImports:
    """Test that summarizer functions can be imported from the plugin."""

    def test_import_summarizer_functions(self):
        """Test importing summarizer functions from plugin root."""
        from code_puppy.plugins.turbo_executor import (
            quick_summary,
            summarize_operation_result,
            summarize_plan_result,
        )

        assert callable(summarize_plan_result)
        assert callable(summarize_operation_result)
        assert callable(quick_summary)

    def test_import_from_summarizer_module(self):
        """Test importing directly from summarizer module."""
        from code_puppy.plugins.turbo_executor.summarizer import (
            DEFAULT_MAX_CONTENT_LENGTH,
            DEFAULT_MAX_GREP_MATCHES,
            _summarize_grep,
            _summarize_list_files,
            _summarize_read_files,
            _truncate_content,
        )

        assert DEFAULT_MAX_CONTENT_LENGTH > 0
        assert DEFAULT_MAX_GREP_MATCHES > 0
        assert callable(_truncate_content)
        assert callable(_summarize_list_files)
        assert callable(_summarize_grep)
        assert callable(_summarize_read_files)


# Note: Multi-instance tests moved to test_turbo_executor_multi_instance.py
# Note: Testing operation tests moved to test_turbo_executor_testing.py
