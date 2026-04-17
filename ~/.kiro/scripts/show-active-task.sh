#!/bin/bash
# show-active-task.sh - Display active task context for AgentSpawn
# Reads from ~/.kiro/state/active_task.json and shows task details
#
# Usage: show-active-task.sh [options]
#
# Options:
#   -h, --help       Show this help message
#   -j, --json       Output as JSON (for programmatic use)
#   -q, --quiet      Suppress warning output (exit code only)
#
# Examples:
#   show-active-task.sh              # Display active task info
#   show-active-task.sh --json       # Output JSON for scripts
#   show-active-task.sh --quiet      # Check if task exists (exit 1 if none)

set -euo pipefail

# Colors (disable with NO_COLOR=1)
if [[ -z "${NO_COLOR:-}" ]]; then
    BOLD='\033[1m'
    GREEN='\033[0;32m'
    YELLOW='\033[0;33m'
    BLUE='\033[0;34m'
    CYAN='\033[0;36m'
    MAGENTA='\033[0;35m'
    RED='\033[0;31m'
    GRAY='\033[0;90m'
    RESET='\033[0m'
else
    BOLD=''
    GREEN=''
    YELLOW=''
    BLUE=''
    CYAN=''
    MAGENTA=''
    RED=''
    GRAY=''
    RESET=''
fi

# Configuration
TASK_FILE="${KIRO_TASK_FILE:-$HOME/.kiro/state/active_task.json}"
OUTPUT_FORMAT="text"
QUIET=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            echo "Usage: $0 [options]"
            echo ""
            echo "Display active task context from ~/.kiro/state/active_task.json"
            echo ""
            echo "Options:"
            echo "  -h, --help       Show this help message"
            echo "  -j, --json       Output as JSON"
            echo "  -q, --quiet      Suppress output, exit code only"
            echo ""
            echo "Environment:"
            echo "  NO_COLOR=1              Disable colors"
            echo "  KIRO_TASK_FILE=<path>   Override task file path"
            exit 0
            ;;
        -j|--json)
            OUTPUT_FORMAT="json"
            shift
            ;;
        -q|--quiet)
            QUIET=true
            shift
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Run '$0 --help' for usage" >&2
            exit 1
            ;;
    esac
done

# Check if task file exists and is readable
check_task_file() {
    if [[ ! -f "$TASK_FILE" ]]; then
        return 1
    fi
    if [[ ! -r "$TASK_FILE" ]]; then
        return 2
    fi
    # Validate it's valid JSON with at least an 'id' field
    if ! jq -e '.id' "$TASK_FILE" > /dev/null 2>&1; then
        return 3
    fi
    return 0
}

# Read task data with safe fallbacks
read_task_data() {
    TASK_ID=$(jq -r '.id // empty' "$TASK_FILE" 2>/dev/null || echo "")
    TASK_CATEGORY=$(jq -r '.category // "uncategorized"' "$TASK_FILE" 2>/dev/null || echo "uncategorized")
    TASK_PRIORITY=$(jq -r '.priority // "normal"' "$TASK_FILE" 2>/dev/null || echo "normal")
    TASK_DESCRIPTION=$(jq -r '.description // ""' "$TASK_FILE" 2>/dev/null || echo "")
    TASK_STATUS=$(jq -r '.status // "active"' "$TASK_FILE" 2>/dev/null || echo "active")
}

# Escape string for JSON output
json_escape() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\t'/\\t}"
    s="${s//$'\n'/\\n}"
    s="${s//$'\r'/\\r}"
    printf '%s' "$s"
}

# JSON output
output_json() {
    local file_exists="false"
    local file_readable="false"
    local has_valid_task="false"
    
    if [[ -f "$TASK_FILE" ]]; then
        file_exists="true"
        if [[ -r "$TASK_FILE" ]]; then
            file_readable="true"
            if jq -e '.id' "$TASK_FILE" > /dev/null 2>&1; then
                has_valid_task="true"
            fi
        fi
    fi
    
    if [[ "$has_valid_task" == "true" ]]; then
        read_task_data
        cat <<EOF
{
    "active": true,
    "task": {
        "id": "$(json_escape "$TASK_ID")",
        "category": "$(json_escape "$TASK_CATEGORY")",
        "priority": "$(json_escape "$TASK_PRIORITY")",
        "description": "$(json_escape "$TASK_DESCRIPTION")",
        "status": "$(json_escape "$TASK_STATUS")"
    },
    "file": {
        "path": "$(json_escape "$TASK_FILE")",
        "exists": $file_exists,
        "readable": $file_readable
    }
}
EOF
    else
        cat <<EOF
{
    "active": false,
    "task": null,
    "file": {
        "path": "$(json_escape "$TASK_FILE")",
        "exists": $file_exists,
        "readable": $file_readable
    },
    "warning": "No active task found"
}
EOF
    fi
}

# Text output
output_text() {
    echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}"
    echo -e "${BOLD}           📋 KIRO - ACTIVE TASK CONTEXT            ${RESET}"
    echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}"
    echo ""
    
    if ! check_task_file; then
        local exit_code=$?
        echo -e "${YELLOW}⚠️  WARNING: No active task${RESET}"
        echo ""
        if [[ $exit_code -eq 1 ]]; then
            echo -e "   Task file not found:"
            echo -e "   ${GRAY}$TASK_FILE${RESET}"
        elif [[ $exit_code -eq 2 ]]; then
            echo -e "   Task file not readable:"
            echo -e "   ${GRAY}$TASK_FILE${RESET}"
        elif [[ $exit_code -eq 3 ]]; then
            echo -e "   Task file exists but contains no valid task ID"
            echo -e "   ${GRAY}$TASK_FILE${RESET}"
        fi
        echo ""
        echo -e "   ${CYAN}To set an active task:${RESET}"
        echo -e "   ${GRAY}echo '{\"id\":\"bd-146\",\"category\":\"feature\",\"priority\":\"high\",\"description\":\"...\"}' > ~/.kiro/state/active_task.json${RESET}"
        echo ""
        echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}"
        return 1
    fi
    
    read_task_data
    
    # Task ID (prominent)
    echo -e "${BOLD}${CYAN}🆔 Task ID:${RESET} ${BOLD}$TASK_ID${RESET}"
    echo ""
    
    # Category
    local category_icon="📁"
    case "$TASK_CATEGORY" in
        bug|fix)        category_icon="🐛" ;;
        feature)        category_icon="✨" ;;
        docs)           category_icon="📚" ;;
        refactor)       category_icon="🔧" ;;
        test)           category_icon="🧪" ;;
        chore)          category_icon="🧹" ;;
        release)        category_icon="🚀" ;;
    esac
    echo -e "${BOLD}Category:${RESET}  $category_icon $TASK_CATEGORY"
    
    # Priority with color
    local priority_color="$GRAY"
    case "$TASK_PRIORITY" in
        1|critical|urgent)   priority_color="$RED" ;;
        2|high)              priority_color="$MAGENTA" ;;
        3|normal|medium)     priority_color="$YELLOW" ;;
        4|low)               priority_color="$GREEN" ;;
    esac
    echo -e "${BOLD}Priority:${RESET}  ${priority_color}$TASK_PRIORITY${RESET}"
    
    # Status
    local status_icon="⏳"
    [[ "$TASK_STATUS" == "active" ]] && status_icon="▶️"
    [[ "$TASK_STATUS" == "blocked" ]] && status_icon="🚫"
    [[ "$TASK_STATUS" == "done" ]] && status_icon="✅"
    echo -e "${BOLD}Status:${RESET}    $status_icon $TASK_STATUS"
    echo ""
    
    # Description
    if [[ -n "$TASK_DESCRIPTION" ]]; then
        echo -e "${BOLD}${BLUE}📝 Description:${RESET}"
        # Wrap description at ~50 chars for readability
        echo "$TASK_DESCRIPTION" | fold -s -w 50 | sed 's/^/   /'
        echo ""
    fi
    
    echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}"
    echo -e "${GRAY}Task file: $TASK_FILE${RESET}"
    return 0
}

# Main
main() {
    local exit_code=0
    
    case "$OUTPUT_FORMAT" in
        json)
            if [[ "$QUIET" == true ]]; then
                # Quiet mode with JSON: suppress output, just exit code
                if ! check_task_file; then
                    exit_code=1
                fi
            else
                output_json
            fi
            ;;
        text)
            if [[ "$QUIET" == true ]]; then
                # Quiet mode: suppress output, just exit code
                if ! check_task_file; then
                    exit_code=1
                fi
            else
                if ! output_text; then
                    exit_code=1
                fi
            fi
            ;;
    esac
    
    exit $exit_code
}

main "$@"
