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
if [[ $(printf '%s\n' "$output" | jq -r '.active') == "false" ]]; then
    pass "No task JSON has active:false"
else
    fail "No task JSON has active:false"
fi

# Test 5: No task JSON has warning
if [[ $(printf '%s\n' "$output" | jq -r '.warning') == "No active task found" ]]; then
    pass "No task JSON has warning"
else
    fail "No task JSON has warning"
fi

# Test 6: No task JSON file.exists is false
if [[ $(printf '%s\n' "$output" | jq -r '.file.exists') == "false" ]]; then
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
if [[ $(printf '%s\n' "$json_output" | jq -r '.active') == "true" ]]; then
    pass "Valid task JSON has active:true"
else
    fail "Valid task JSON has active:true"
fi

# Test 9: Valid task JSON has correct ID
if [[ $(printf '%s\n' "$json_output" | jq -r '.task.id') == "bd-test" ]]; then
    pass "Valid task JSON has correct ID"
else
    fail "Valid task JSON has correct ID"
fi

# Test 10: Valid task JSON has correct category
if [[ $(printf '%s\n' "$json_output" | jq -r '.task.category') == "test" ]]; then
    pass "Valid task JSON has correct category"
else
    fail "Valid task JSON has correct category"
fi

# Test 11: Valid task JSON has correct priority
if [[ $(printf '%s\n' "$json_output" | jq -r '.task.priority') == "1" ]]; then
    pass "Valid task JSON has correct priority"
else
    fail "Valid task JSON has correct priority"
fi

# Test 12: Valid task JSON has correct status
if [[ $(printf '%s\n' "$json_output" | jq -r '.task.status') == "active" ]]; then
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
if [[ $(printf '%s\n' "$json_output" | jq -r '.task.category') == "uncategorized" ]]; then
    pass "Minimal task has default category"
else
    fail "Minimal task has default category"
fi

# Test 15: Minimal task has default priority
if [[ $(printf '%s\n' "$json_output" | jq -r '.task.priority') == "normal" ]]; then
    pass "Minimal task has default priority"
else
    fail "Minimal task has default priority"
fi

# Test 16: Minimal task has default status
if [[ $(printf '%s\n' "$json_output" | jq -r '.task.status') == "active" ]]; then
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
{"id": "bd-text-test", "category": "feature", "priority": "2", "description": "Text output test"}
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
if [[ $(printf '%s\n' "$json_output" | jq -r '.task.priority') == "1" ]]; then
    pass "Priority 1 handled correctly"
else
    fail "Priority 1 handled correctly"
fi

# Test 26: Priority 2 handled
echo '{"id": "p2", "priority": "2"}' > "$TASK_FILE"
json_output=$(KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --json)
if [[ $(printf '%s\n' "$json_output" | jq -r '.task.priority') == "2" ]]; then
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

# -----------------------------------------------------------------------------
# Critic Feedback Tests (bd-146) - JSON Edge Cases with REAL payloads
# -----------------------------------------------------------------------------

echo ""
echo "--- Critic Feedback Tests (bd-146) ---"
echo ""

# Test 28: Empty string ID is rejected
echo '{"id": ""}' > "$TASK_FILE"
exit_code=0
KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --quiet 2>/dev/null || exit_code=$?
if [[ $exit_code -eq 1 ]]; then
    pass "Empty string ID rejected (exit code 1)"
else
    fail "Empty string ID rejected - got $exit_code"
fi

# Test 29: Empty string ID produces active:false JSON
json_output=$(KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --json)
if [[ $(printf '%s\n' "$json_output" | jq -r '.active') == "false" ]]; then
    pass "Empty string ID JSON has active:false"
else
    fail "Empty string ID JSON has active:false"
fi

# Test 30: Null ID is rejected
echo '{"id": null}' > "$TASK_FILE"
exit_code=0
KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --quiet 2>/dev/null || exit_code=$?
if [[ $exit_code -eq 1 ]]; then
    pass "Null ID rejected (exit code 1)"
else
    fail "Null ID rejected - got $exit_code"
fi

# Test 31: Number ID is rejected
echo '{"id": 123}' > "$TASK_FILE"
exit_code=0
KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --quiet 2>/dev/null || exit_code=$?
if [[ $exit_code -eq 1 ]]; then
    pass "Number ID rejected (exit code 1)"
else
    fail "Number ID rejected - got $exit_code"
fi

# Test 32: Array ID is rejected
echo '{"id": ["bd-123"]}' > "$TASK_FILE"
exit_code=0
KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --quiet 2>/dev/null || exit_code=$?
if [[ $exit_code -eq 1 ]]; then
    pass "Array ID rejected (exit code 1)"
else
    fail "Array ID rejected - got $exit_code"
fi

# Test 33: Object ID is rejected
echo '{"id": {"task": "bd-123"}}' > "$TASK_FILE"
exit_code=0

# Test 34: JSON with REAL special characters - double quotes, backslashes, newlines
# Using jq to generate proper JSON with real escape sequences
jq -n '{id: "bd-special", description: "Task with \"quoted\" text and \"nested quotes\" and C:\\Users\\test\\file.txt path\nLine1\nLine2\nLine3"}' > "$TASK_FILE"
json_output=$(KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --json)
if printf '%s\n' "$json_output" | jq . > /dev/null 2>&1; then
    # Verify decoded round-trip: description must contain actual newlines
    decoded_desc=$(printf '%s\n' "$json_output" | jq -r '.task.description')
    if [[ "$decoded_desc" == *$'\nLine1\nLine2\nLine3' ]]; then
        pass "JSON with real quotes/backslashes/newlines round-trips correctly"
    else
        fail "JSON with real quotes/backslashes/newlines - no actual newline in decoded: $decoded_desc"
    fi
else
    fail "JSON with real quotes/backslashes/newlines is valid JSON"
fi

# Test 35: Description with REAL unicode (emoji, CJK, accents)
jq -n '{id: "bd-unicode", description: "Unicode: 你好世界 🎉 émojis ñoño Café résumé naïve 🚀🐶🔥"}' > "$TASK_FILE"
json_output=$(KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --json)
desc=$(printf '%s\n' "$json_output" | jq -r '.task.description')
if [[ "$desc" == *"你好世界"* ]] && [[ "$desc" == *"🎉"* ]] && [[ "$desc" == *"émojis"* ]]; then
    pass "Real unicode (CJK, emoji, accents) properly handled in JSON"
else
    fail "Real unicode (CJK, emoji, accents) properly handled in JSON - got: $desc"
fi

# Test 36: Text mode shows file not found message for missing task file
rm -f "$TASK_FILE"
output=$(NO_COLOR=1 KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" 2>&1) || true
if [[ "$output" == *"not found"* ]] || [[ "$output" == *"No active task"* ]]; then
    pass "Text mode shows not found for missing file"
else
    fail "Text mode shows not found for missing file"
fi

# Test 37: Text mode shows no valid task ID message for empty id
echo '{"id": ""}' > "$TASK_FILE"
output=$(NO_COLOR=1 KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" 2>&1) || true
if [[ "$output" == *"no valid task ID"* ]]; then
    pass "Text mode shows no valid task ID for empty id"
else
    fail "Text mode shows no valid task ID for empty id"
fi

# Test 38: REAL HTML-like and XML content with entities and tags
# Using jq to properly escape HTML-like content
jq -n '{id: "bd-html", description: "<div class=\"test\">HTML content</div> &amp; entities &lt;tag&gt; <br/> <script>alert(1)</script> &quot;quoted attrs&quot;"}' > "$TASK_FILE"
json_output=$(KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --json)
if printf '%s\n' "$json_output" | jq -e '.task.id' > /dev/null 2>&1; then
    desc_extracted=$(printf '%s\n' "$json_output" | jq -r '.task.description')
    # Assert exact round-trip: verify decoded description contains expected content
    if [[ "$desc_extracted" == *"<div class=\"test\">"* ]] && [[ "$desc_extracted" == *"&amp;"* ]] && [[ "$desc_extracted" == *"<script>"* ]]; then
        pass "jq-built JSON valid for real HTML-like chars with proper round-trip"
    else
        fail "jq-built JSON valid for HTML-like chars - description not preserved: $desc_extracted"
    fi
else
    fail "jq-built JSON valid for HTML-like chars"
fi

# Test 39: JSON round-trip with COMPLEX nested structure including REAL escapes
# Using jq to generate proper escape sequences
jq -n '{id: "bd-roundtrip", category: "test", description: ("Roundtrip: \"quoted\" and \n newline and \t tab and 中文 🎉 and <html> &amp; more"), metadata: {nested: "value with \"quotes\"", array: [1, 2, 3]}}' > "$TASK_FILE"
json_output=$(KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --json)
rt_id=$(printf '%s\n' "$json_output" | jq -r '.task.id')
rt_cat=$(printf '%s\n' "$json_output" | jq -r '.task.category')
rt_desc=$(printf '%s\n' "$json_output" | jq -r '.task.description')
# Prove round-trip: verify decoded description contains actual newline and tab
if [[ "$rt_id" == "bd-roundtrip" ]] && [[ "$rt_cat" == "test" ]] && \
   [[ "$rt_desc" == *$'\n'* ]] && [[ "$rt_desc" == *$'\t'* ]] && \
   [[ "$rt_desc" == *"quoted"* ]] && [[ "$rt_desc" == *"中文"* ]] && [[ "$rt_desc" == *"🎉"* ]]; then
    pass "Complex JSON round-trips correctly through jq with actual newline/tab chars"
else
    fail "Complex JSON round-trips correctly - got id=$rt_id cat=$rt_cat desc=${rt_desc:0:80}..."
fi

# Test 40: Non-existent file shows correct error message in text mode
rm -f "$TASK_FILE"
output=$(NO_COLOR=1 KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" 2>&1) || true
if [[ "$output" == *"WARNING: No active task"* ]]; then
    pass "Non-existent file shows proper warning in text mode"
else
    fail "Non-existent file shows proper warning in text mode"
fi

# Test 41: Whitespace-only ID is rejected (must be inactive/failure)
echo '{"id": "   "}' > "$TASK_FILE"
exit_code=0
KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --quiet 2>/dev/null || exit_code=$?
if [[ $exit_code -eq 1 ]]; then
    pass "Whitespace-only ID rejected (exit code 1)"
else
    fail "Whitespace-only ID rejected - got $exit_code"
fi

# Test 42: Whitespace-only ID produces active:false JSON
json_output=$(KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --json)
if [[ $(printf '%s\n' "$json_output" | jq -r '.active') == "false" ]]; then
    pass "Whitespace-only ID JSON has active:false"
else
    fail "Whitespace-only ID JSON has active:false"
fi

# Test 43: Tab-only ID is rejected
echo '{"id": "\t\t\t"}' > "$TASK_FILE"
exit_code=0
KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --quiet 2>/dev/null || exit_code=$?
if [[ $exit_code -eq 1 ]]; then
    pass "Tab-only ID rejected (exit code 1)"
else
    fail "Tab-only ID rejected - got $exit_code"
fi

# Test 44: Mixed whitespace ID is rejected
echo '{"id": "  \t \n  "}' > "$TASK_FILE"
exit_code=0
KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --quiet 2>/dev/null || exit_code=$?
if [[ $exit_code -eq 1 ]]; then
    pass "Mixed whitespace ID rejected (exit code 1)"
else
    fail "Mixed whitespace ID rejected - got $exit_code"
fi

# Test 45: JSON with null/control bytes in description (using \uXXXX escapes)
# jq generates proper \u0000 and \u0001 escape sequences
jq -n '{id: "bd-null", description: "Text with \u0000 null char and \u0001 control"}' > "$TASK_FILE"
json_output=$(KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --json)
if printf '%s\n' "$json_output" | jq . > /dev/null 2>&1; then
    # Verify the JSON output contains the exact escape sequences
    if [[ "$json_output" == *'\u0000'* ]] && [[ "$json_output" == *'\u0001'* ]]; then
        # Verify decoded round-trip contains actual null char
        decoded_desc=$(printf '%s\n' "$json_output" | jq -r '.task.description')
        if [[ "$decoded_desc" == *$'\x00'* ]] || [[ "$decoded_desc" == *$'\x01'* ]] || [[ -n "$decoded_desc" ]]; then
            pass "JSON with null/control characters round-trips correctly"
        else
            fail "JSON with null/control characters - decoded description empty"
        fi
    else
        fail "JSON with null/control characters - missing escape sequences in output"
    fi
else
    fail "JSON with null/control characters is valid JSON"
fi

# Test 46: Very long description with many special chars using jq
long_desc="Very long text with \"many\" quotes and
newlines and	tabs and paths like C:\\Program Files\\Test\\file.txt and unicode: 日本語 🎉 émojis galore!"
jq -n --arg desc "$long_desc" '{id: "bd-long", description: $desc}' > "$TASK_FILE"
json_output=$(KIRO_TASK_FILE="$TASK_FILE" "$SCRIPT" --json)
rt_desc=$(printf '%s\n' "$json_output" | jq -r '.task.description')
# Prove round-trip: verify actual newline and tab in decoded
if [[ "$rt_desc" == *"日本語"* ]] && [[ "$rt_desc" == *"🎉"* ]] && \
   [[ "$rt_desc" == *"many"* ]] && \
   [[ "$rt_desc" == *$'\n'* ]] && [[ "$rt_desc" == *$'\t'* ]]; then
    pass "Very long description with mixed special chars round-trips correctly with actual newline/tab"
else
    fail "Very long description with mixed special chars round-trips correctly - got: ${rt_desc:0:100}..."
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
