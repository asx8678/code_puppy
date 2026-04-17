#!/bin/bash
# test_show_active_task.sh - Focused tests for show-active-task.sh
# Run: bash test_show_active_task.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$SCRIPT_DIR/show-active-task.sh"
TEST_DIR="/tmp/test_kiro_$$"
TASK_FILE="$TEST_DIR/active_task.json"
FAILED=0
PASSED=0

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RESET='\033[0m'

# Test helper
pass() {
    echo -e "${GREEN}✓${RESET} $1"
    PASSED=$((PASSED + 1))
}

fail() {
    echo -e "${RED}✗${RESET} $1"
    FAILED=$((FAILED + 1))
}

# Setup
mkdir -p "$TEST_DIR"

echo "═══════════════════════════════════════════════════"
echo "   Testing show-active-task.sh"
echo "═══════════════════════════════════════════════════"
echo ""

# Check prerequisites
if ! command -v jq &> /dev/null; then
    echo -e "${RED}✗${RESET} jq is required but not installed"
    exit 1
fi

echo "Running tests..."
echo ""

# Test 1: Script exists
if [[ -f "$SCRIPT" ]]; then
    pass "Script exists"
else
    fail "Script exists"
fi

# Test 2: Script is executable
if [[ -x "$SCRIPT" ]]; then
    pass "Script is executable"
else
    fail "Script is executable"
fi

# Test 3: No task file exits with code 1 (quiet)
rm -f "$TASK_FILE"
exit_code=0
KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --quiet 2>/dev/null || exit_code=$?
if [[ $exit_code -eq 1 ]]; then
    pass "No task file exits with code 1 (quiet)"
else
    fail "No task file exits with code 1 (quiet) - got $exit_code"
fi

# Test 4: No task file JSON has active:false
rm -f "$TASK_FILE"
output=$(KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --json)
if [[ $(echo "$output" | jq -r '.active') == "false" ]]; then
    pass "No task JSON has active:false"
else
    fail "No task JSON has active:false"
fi

# Test 5: No task JSON has warning
if [[ $(echo "$output" | jq -r '.warning') == "No active task found" ]]; then
    pass "No task JSON has warning"
else
    fail "No task JSON has warning"
fi

# Test 6: No task JSON file.exists is false
if [[ $(echo "$output" | jq -r '.file.exists') == "false" ]]; then
    pass "No task JSON file.exists is false"
else
    fail "No task JSON file.exists is false"
fi

# Test 7: Valid task exits with code 0 (quiet)
cat > "$TASK_FILE" << 'EOF'
{"id": "bd-test", "category": "test", "priority": "1", "description": "Test task", "status": "active"}
EOF
exit_code=0
KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --quiet || exit_code=$?
if [[ $exit_code -eq 0 ]]; then
    pass "Valid task exits with code 0 (quiet)"
else
    fail "Valid task exits with code 0 (quiet) - got $exit_code"
fi

# Test 8: Valid task JSON has active:true
json_output=$(KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --json)
if [[ $(echo "$json_output" | jq -r '.active') == "true" ]]; then
    pass "Valid task JSON has active:true"
else
    fail "Valid task JSON has active:true"
fi

# Test 9: Valid task JSON has correct ID
if [[ $(echo "$json_output" | jq -r '.task.id') == "bd-test" ]]; then
    pass "Valid task JSON has correct ID"
else
    fail "Valid task JSON has correct ID"
fi

# Test 10: Valid task JSON has correct category
if [[ $(echo "$json_output" | jq -r '.task.category') == "test" ]]; then
    pass "Valid task JSON has correct category"
else
    fail "Valid task JSON has correct category"
fi

# Test 11: Valid task JSON has correct priority
if [[ $(echo "$json_output" | jq -r '.task.priority') == "1" ]]; then
    pass "Valid task JSON has correct priority"
else
    fail "Valid task JSON has correct priority"
fi

# Test 12: Valid task JSON has correct status
if [[ $(echo "$json_output" | jq -r '.task.status') == "active" ]]; then
    pass "Valid task JSON has correct status"
else
    fail "Valid task JSON has correct status"
fi

# Test 13: Missing ID field exits with code 1
cat > "$TASK_FILE" << 'EOF'
{"category": "test", "priority": "1"}
EOF
exit_code=0
KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --quiet 2>/dev/null || exit_code=$?
if [[ $exit_code -eq 1 ]]; then
    pass "Missing ID field exits with code 1"
else
    fail "Missing ID field exits with code 1 - got $exit_code"
fi

# Test 14: Minimal task has default category
cat > "$TASK_FILE" << 'EOF'
{"id": "bd-minimal"}
EOF
json_output=$(KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --json)
if [[ $(echo "$json_output" | jq -r '.task.category') == "uncategorized" ]]; then
    pass "Minimal task has default category"
else
    fail "Minimal task has default category"
fi

# Test 15: Minimal task has default priority
if [[ $(echo "$json_output" | jq -r '.task.priority') == "normal" ]]; then
    pass "Minimal task has default priority"
else
    fail "Minimal task has default priority"
fi

# Test 16: Minimal task has default status
if [[ $(echo "$json_output" | jq -r '.task.status') == "active" ]]; then
    pass "Minimal task has default status"
else
    fail "Minimal task has default status"
fi

# Test 17: Help shows usage
output=$("$SCRIPT" --help 2>&1) || true
if [[ "$output" == *"Usage:"* ]]; then
    pass "Help shows usage"
else
    fail "Help shows usage"
fi

# Test 18: Help mentions --json
if [[ "$output" == *"--json"* ]]; then
    pass "Help mentions --json"
else
    fail "Help mentions --json"
fi

# Test 19: Help mentions --quiet
if [[ "$output" == *"--quiet"* ]]; then
    pass "Help mentions --quiet"
else
    fail "Help mentions --quiet"
fi

# Test 20: Text output shows task ID
cat > "$TASK_FILE" << 'EOF'
{"id": "bd-text-test", "category": "feature", "priority": "2", "description": "Text output test", "status": "active"}
EOF
output=$(NO_COLOR=1 KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT")
if [[ "$output" == *"bd-text-test"* ]]; then
    pass "Text output shows task ID"
else
    fail "Text output shows task ID"
fi

# Test 21: Text output shows category
if [[ "$output" == *"feature"* ]]; then
    pass "Text output shows category"
else
    fail "Text output shows category"
fi

# Test 22: Text output shows description
if [[ "$output" == *"Text output test"* ]]; then
    pass "Text output shows description"
else
    fail "Text output shows description"
fi

# Test 23: Unknown option exits with code 1
exit_code=0
"$SCRIPT" --unknown-option 2>/dev/null || exit_code=$?
if [[ $exit_code -eq 1 ]]; then
    pass "Unknown option exits with code 1"
else
    fail "Unknown option exits with code 1 - got $exit_code"
fi

# Test 24: Invalid JSON exits with code 1
echo "not valid json" > "$TASK_FILE"
exit_code=0
KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --quiet 2>/dev/null || exit_code=$?
if [[ $exit_code -eq 1 ]]; then
    pass "Invalid JSON exits with code 1"
else
    fail "Invalid JSON exits with code 1 - got $exit_code"
fi

# Test 25: Priority 1 handled
echo '{"id": "p1", "priority": "1"}' > "$TASK_FILE"
json_output=$(KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --json)
if [[ $(echo "$json_output" | jq -r '.task.priority') == "1" ]]; then
    pass "Priority 1 handled correctly"
else
    fail "Priority 1 handled correctly"
fi

# Test 26: Priority 2 handled
echo '{"id": "p2", "priority": "2"}' > "$TASK_FILE"
json_output=$(KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --json)
if [[ $(echo "$json_output" | jq -r '.task.priority') == "2" ]]; then
    pass "Priority 2 handled correctly"
else
    fail "Priority 2 handled correctly"
fi

# Test 27: Bug category shown
echo '{"id": "bc", "category": "bug"}' > "$TASK_FILE"
output=$(NO_COLOR=1 KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT")
if [[ "$output" == *"bug"* ]]; then
    pass "Bug category shown"
else
    fail "Bug category shown"
fi

# Cleanup
rm -rf "$TEST_DIR"

echo ""
echo "═══════════════════════════════════════════════════"
echo -e "   PASSED: $PASSED  FAILED: $FAILED"
echo "═══════════════════════════════════════════════════"

if [[ $FAILED -gt 0 ]]; then
    exit 1
fi

echo -e "${GREEN}All tests passed!${RESET}"
exit 0
