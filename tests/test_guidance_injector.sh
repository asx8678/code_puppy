#!/bin/bash
# Test suite for guidance-injector.sh
# Run with: bash tests/test_guidance_injector.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
GUIDANCE_SCRIPT="$REPO_ROOT/~/.kiro/scripts/guidance-injector.sh"

# Colors for test output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RESET='\033[0m'

PASS=0
FAIL=0

# Test runner
run_test() {
    local test_name="$1"
    local test_func="$2"
    
    echo -n "Testing: $test_name ... "
    if $test_func 2>/dev/null; then
        echo -e "${GREEN}PASS${RESET}"
        ((PASS++)) || true
    else
        echo -e "${RED}FAIL${RESET}"
        ((FAIL++)) || true
    fi
}

# Test functions
test_script_exists() {
    [[ -f "$GUIDANCE_SCRIPT" ]]
}

test_script_executable() {
    [[ -x "$GUIDANCE_SCRIPT" ]]
}

test_bash_syntax() {
    bash -n "$GUIDANCE_SCRIPT"
}

test_guidance_disabled() {
    local output
    output=$(GUIDANCE_ENABLED=false NO_COLOR=1 KIRO_TOOL_NAME="write_file" bash "$GUIDANCE_SCRIPT")
    [[ -z "$output" ]]
}

test_minimal_verbosity() {
    local output
    output=$(GUIDANCE_VERBOSITY=minimal NO_COLOR=1 KIRO_TOOL_NAME="write_file" bash "$GUIDANCE_SCRIPT")
    [[ -n "$output" ]]
    [[ ! "$output" =~ "🐾 Post-Tool Guidance" ]]
}

test_normal_verbosity() {
    local output
    output=$(GUIDANCE_VERBOSITY=normal NO_COLOR=1 KIRO_TOOL_NAME="write_file" bash "$GUIDANCE_SCRIPT")
    [[ "$output" =~ "🐾 Post-Tool Guidance" ]]
}

test_no_color() {
    local output
    output=$(NO_COLOR=1 KIRO_TOOL_NAME="read_file" bash "$GUIDANCE_SCRIPT")
    # Check no ANSI escape codes
    [[ ! "$output" =~ $'\e[' ]]
}

test_write_file_python() {
    local output
    output=$(NO_COLOR=1 KIRO_TOOL_NAME="write_file" KIRO_TOOL_ARGS="test.py" KIRO_TOOL_OUTPUT="Created test.py" bash "$GUIDANCE_SCRIPT")
    [[ "$output" =~ "pytest" ]]
    [[ "$output" =~ "py_compile" ]]
}

test_write_file_shell() {
    local output
    output=$(NO_COLOR=1 KIRO_TOOL_NAME="create_file" KIRO_TOOL_ARGS="script.sh" KIRO_TOOL_OUTPUT="Created script.sh" bash "$GUIDANCE_SCRIPT")
    [[ "$output" =~ "shellcheck" ]] || [[ "$output" =~ "chmod +x" ]]
}

test_run_shell_command_success() {
    local output
    output=$(NO_COLOR=1 KIRO_TOOL_NAME="run_shell_command" KIRO_TOOL_ARGS="pytest" KIRO_TOOL_EXIT_CODE="0" bash "$GUIDANCE_SCRIPT")
    [[ "$output" =~ "Tests passed" ]] || [[ "$output" =~ "Command completed" ]]
}

test_run_shell_command_failure() {
    local output
    output=$(NO_COLOR=1 KIRO_TOOL_NAME="run_shell_command" KIRO_TOOL_ARGS="false" KIRO_TOOL_EXIT_CODE="1" bash "$GUIDANCE_SCRIPT")
    [[ "$output" =~ "failed" ]] || [[ "$output" =~ "exit code 1" ]]
}

test_invoke_agent() {
    local output
    output=$(NO_COLOR=1 KIRO_TOOL_NAME="invoke_agent" KIRO_TOOL_ARGS="turbo-executor do work" bash "$GUIDANCE_SCRIPT")
    [[ "$output" =~ "turbo-executor" ]]
    [[ "$output" =~ "completed" ]]
}

test_subagent_alias() {
    local output
    output=$(NO_COLOR=1 KIRO_TOOL_NAME="subagent" KIRO_TOOL_ARGS="turbo-executor do work" bash "$GUIDANCE_SCRIPT")
    [[ "$output" =~ "turbo-executor" ]]
    [[ "$output" =~ "completed" ]]
}

test_use_subagent_alias() {
    local output
    output=$(NO_COLOR=1 KIRO_TOOL_NAME="use_subagent" KIRO_TOOL_ARGS="turbo-executor do work" bash "$GUIDANCE_SCRIPT")
    [[ "$output" =~ "turbo-executor" ]]
    [[ "$output" =~ "completed" ]]
}

test_agent_run_shell_command_alias() {
    local output
    output=$(NO_COLOR=1 KIRO_TOOL_NAME="agent_run_shell_command" KIRO_TOOL_ARGS="pytest" KIRO_TOOL_EXIT_CODE="0" bash "$GUIDANCE_SCRIPT")
    [[ "$output" =~ "pytest" ]] || [[ "$output" =~ "Command completed" ]] || [[ "$output" =~ "Tests passed" ]]
}

test_replace_in_file() {
    local output
    output=$(NO_COLOR=1 KIRO_TOOL_NAME="replace_in_file" bash "$GUIDANCE_SCRIPT")
    [[ "$output" =~ "modified" ]] || [[ "$output" =~ "git diff" ]]
}

test_exploratory_tools() {
    local output
    output=$(NO_COLOR=1 KIRO_TOOL_NAME="grep" bash "$GUIDANCE_SCRIPT")
    [[ "$output" =~ "Exploratory" ]] || [[ "$output" =~ "findings" ]]
}

test_unknown_tool_verbose() {
    local output
    output=$(NO_COLOR=1 GUIDANCE_VERBOSITY=verbose KIRO_TOOL_NAME="unknown_tool" bash "$GUIDANCE_SCRIPT")
    [[ "$output" =~ "unknown_tool" ]]
}

test_unknown_tool_minimal() {
    local output
    output=$(NO_COLOR=1 GUIDANCE_VERBOSITY=minimal KIRO_TOOL_NAME="unknown_tool" bash "$GUIDANCE_SCRIPT")
    [[ -z "$output" ]]
}

test_delete_file() {
    local output
    output=$(NO_COLOR=1 KIRO_TOOL_NAME="delete_file" bash "$GUIDANCE_SCRIPT")
    [[ "$output" =~ "removed" ]] || [[ "$output" =~ "deletion" ]]
}

test_ask_user() {
    local output
    output=$(NO_COLOR=1 KIRO_TOOL_NAME="ask_user_question" bash "$GUIDANCE_SCRIPT")
    [[ "$output" =~ "input" ]] || [[ "$output" =~ "response" ]]
}

# Main
echo "======================================"
echo "Guidance Injector Test Suite"
echo "======================================"
echo ""

# Check if script exists before running all tests
if [[ ! -f "$GUIDANCE_SCRIPT" ]]; then
    echo -e "${RED}ERROR: guidance-injector.sh not found at $GUIDANCE_SCRIPT${RESET}"
    exit 1
fi

# Run all tests
run_test "Script exists" test_script_exists
run_test "Script is executable" test_script_executable
run_test "Bash syntax is valid" test_bash_syntax
run_test "GUIDANCE_ENABLED=false disables output" test_guidance_disabled
run_test "Minimal verbosity skips header" test_minimal_verbosity
run_test "Normal verbosity shows header" test_normal_verbosity
run_test "NO_COLOR disables colors" test_no_color
run_test "write_file Python suggestions" test_write_file_python
run_test "create_file Shell suggestions" test_write_file_shell
run_test "run_shell_command success" test_run_shell_command_success
run_test "run_shell_command failure" test_run_shell_command_failure
run_test "agent_run_shell_command alias" test_agent_run_shell_command_alias
run_test "invoke_agent shows agent name" test_invoke_agent
run_test "subagent alias" test_subagent_alias
run_test "use_subagent alias" test_use_subagent_alias
run_test "replace_in_file guidance" test_replace_in_file
run_test "Exploratory tools (grep)" test_exploratory_tools
run_test "Unknown tool with verbose" test_unknown_tool_verbose
run_test "Unknown tool with minimal (silent)" test_unknown_tool_minimal
run_test "delete_file guidance" test_delete_file
run_test "ask_user_question guidance" test_ask_user

echo ""
echo "======================================"
echo -e "Results: ${GREEN}$PASS passed${RESET}, ${RED}$FAIL failed${RESET}"
echo "======================================"

if [[ $FAIL -eq 0 ]]; then
    echo -e "${GREEN}All tests passed!${RESET}"
    exit 0
else
    echo -e "${RED}Some tests failed.${RESET}"
    exit 1
fi
