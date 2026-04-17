#!/bin/bash
# show-active-task.sh - Display AgentSpawn context and active task information
# Usage: show-active-task.sh [options]
#
# This script displays information about the currently active task context,
# including agent hierarchy, task goals, and related state. Useful for
# understanding what Code Puppy is currently working on.
#
# Options:
#   -h, --help       Show this help message
#   -j, --json       Output as JSON (for programmatic use)
#   -v, --verbose    Show detailed information
#   --tree           Show agent hierarchy as a tree
#
# Examples:
#   show-active-task.sh              # Display basic active task info
#   show-active-task.sh --verbose    # Show detailed info
#   show-active-task.sh --json       # Output JSON for scripts

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_FORMAT="text"
VERBOSE=false
SHOW_TREE=false

# Colors
if [[ -z "${NO_COLOR:-}" ]]; then
    BOLD='\033[1m'
    GREEN='\033[0;32m'
    YELLOW='\033[0;33m'
    BLUE='\033[0;34m'
    CYAN='\033[0;36m'
    MAGENTA='\033[0;35m'
    GRAY='\033[0;90m'
    RESET='\033[0m'
else
    BOLD=''
    GREEN=''
    YELLOW=''
    BLUE=''
    CYAN=''
    MAGENTA=''
    GRAY=''
    RESET=''
fi

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            echo "Usage: $0 [options]"
            echo ""
            echo "Display AgentSpawn context and active task information"
            echo ""
            echo "Options:"
            echo "  -h, --help       Show this help message"
            echo "  -j, --json       Output as JSON"
            echo "  -v, --verbose    Show detailed information"
            echo "  --tree           Show agent hierarchy as tree"
            echo ""
            echo "Environment:"
            echo "  NO_COLOR=1       Disable colors"
            echo "  PUP_TASK_ID      Override task ID detection"
            exit 0
            ;;
        -j|--json)
            OUTPUT_FORMAT="json"
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        --tree)
            SHOW_TREE=true
            shift
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Run '$0 --help' for usage" >&2
            exit 1
            ;;
    esac
done

# Get environment info
get_env_info() {
    cat <<EOF
{
    "cwd": "$(pwd)",
    "home": "${HOME:-unknown}",
    "shell": "${SHELL:-unknown}",
    "term": "${TERM:-unknown}",
    "user": "${USER:-unknown}",
    "pup_task_id": "${PUP_TASK_ID:-${PUPPY_TASK_ID:-auto-detected}}"
}
EOF
}

# Get git info
get_git_info() {
    local git_info="{}"
    
    if git rev-parse --git-dir > /dev/null 2>&1; then
        git_info=$(cat <<EOF
{
    "branch": "$(git branch --show-current 2>/dev/null || echo 'unknown')",
    "commit": "$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')",
    "dirty": $(git diff --quiet 2>/dev/null && echo "false" || echo "true"),
    "remote_url": "$(git remote get-url origin 2>/dev/null || echo 'none')"
}
EOF
)
    fi
    
    echo "$git_info"
}

# Get project info
get_project_info() {
    local project_type="unknown"
    local project_files="[]"
    
    # Detect project type
    if [[ -f "pyproject.toml" ]]; then
        project_type="python"
        project_files='["pyproject.toml", "requirements.txt"]'
    elif [[ -f "package.json" ]]; then
        project_type="nodejs"
        project_files='["package.json", "package-lock.json", "node_modules/"]'
    elif [[ -f "Cargo.toml" ]]; then
        project_type="rust"
        project_files='["Cargo.toml", "Cargo.lock", "target/"]'
    elif [[ -f "go.mod" ]]; then
        project_type="go"
        project_files='["go.mod", "go.sum"]'
    elif [[ -f "pom.xml" ]] || [[ -f "build.gradle" ]]; then
        project_type="java"
        project_files='["pom.xml", "build.gradle"]'
    elif [[ -f "Makefile" ]] || [[ -f "CMakeLists.txt" ]]; then
        project_type="c/c++"
        project_files='["Makefile", "CMakeLists.txt"]'
    fi
    
    cat <<EOF
{
    "type": "$project_type",
    "key_files": $project_files
}
EOF
}

# Build agent hierarchy tree
# In real implementation, this would read from Code Puppy's state
build_agent_tree() {
    local depth="${1:-0}"
    local prefix=""
    
    for ((i=0; i<depth; i++)); do
        prefix="$prefix  "
    done
    
    if [[ "$SHOW_TREE" == true ]]; then
        echo -e "${BOLD}Agent Hierarchy:${RESET}"
        echo ""
        echo -e "${CYAN}🐕 code-puppy${RESET} (root agent)"
        echo -e "  ${MAGENTA}🤖 turbo-executor${RESET} (active, Phase 3)"
        echo -e "    ${MAGENTA}🤖 file_service${RESET} (file ops)"
        echo -e "    ${MAGENTA}🤖 parse_agent${RESET} (tree-sitter)"
        echo -e "  ${MAGENTA}🤖 proactive-guidance${RESET} (this plugin)"
        echo ""
    fi
}

# Get active tasks info from real context sources
get_active_tasks() {
    # Detect task ID from env or git branch heuristic
    local task_id="${PUP_TASK_ID:-${PUPPY_TASK_ID:-}}"
    if [[ -z "$task_id" ]]; then
        local branch=""
        branch=$(git branch --show-current 2>/dev/null || true)
        if [[ -n "$branch" ]]; then
            task_id=$(echo "$branch" | grep -oE 'bd-[0-9]+' | head -1 || true)
        fi
    fi

    local task_name="unknown"
    local task_status="unknown"
    if [[ -n "$task_id" ]]; then
        # Try to get task info from bd tool
        local bd_output=""
        bd_output=$(bd show "$task_id" 2>/dev/null || true)
        if [[ -n "$bd_output" ]]; then
            task_name=$(echo "$bd_output" | grep '^Title:' | sed 's/Title: *//' || echo "Task $task_id")
            task_status=$(echo "$bd_output" | grep '^Status:' | sed 's/Status: *//' || echo "unknown")
        else
            task_name="Task $task_id"
            task_status="active"
        fi
    fi

    cat <<EOF
{
    "current_task": {
        "id": "${task_id:-none}",
        "name": "$task_name",
        "status": "$task_status"
    },
    "source": "${task_id:+bd}${task_id:-env/git}"
}
EOF
}

# JSON output
output_json() {
    cat <<EOF
{
    "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
    "environment": $(get_env_info),
    "git": $(get_git_info),
    "project": $(get_project_info),
    "tasks": $(get_active_tasks),
    "plugin": {
        "name": "proactive_guidance",
        "guidance_count": ${PUP_GUIDANCE_COUNT:-${PUPPY_GUIDANCE_COUNT:-0}},
        "enabled": ${PUP_GUIDANCE_ENABLED:-${PUPPY_GUIDANCE_ENABLED:-true}}
    }
}
EOF
}

# Text output
output_text() {
    echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}"
    echo -e "${BOLD}        🐾 CODE PUPPY - ACTIVE TASK CONTEXT         ${RESET}"
    echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}"
    echo ""
    
    # Current Task
    echo -e "${BOLD}${CYAN}📋 Current Task:${RESET}"
    # Detect task ID from env or git branch
    _task_id="${PUP_TASK_ID:-${PUPPY_TASK_ID:-}}"
    if [[ -z "$_task_id" ]]; then
        _branch=$(git branch --show-current 2>/dev/null || true)
        _task_id=$(echo "$_branch" | grep -oE 'bd-[0-9]+' | head -1 || true)
    fi
    echo -e "   ID: ${_task_id:-none detected}"
    if [[ -n "$_task_id" ]]; then
        _task_name=$(bd show "$_task_id" 2>/dev/null | grep '^Title:' | sed 's/Title: *//' || echo "Task $_task_id")
        echo -e "   Name: $_task_name"
    fi
    echo -e "   Branch: ${GREEN}$(git branch --show-current 2>/dev/null || echo 'unknown')${RESET}"
    echo ""
    
    # Environment
    echo -e "${BOLD}${YELLOW}💻 Environment:${RESET}"
    echo -e "   CWD: $(pwd)"
    echo -e "   User: ${USER:-unknown}"
    echo -e "   Shell: ${SHELL:-unknown}"
    
    if git rev-parse --git-dir > /dev/null 2>&1; then
        echo -e "   Git Branch: ${CYAN}$(git branch --show-current 2>/dev/null || echo 'unknown')${RESET}"
        echo -e "   Commit: ${GRAY}$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')${RESET}"
    fi
    echo ""
    
    # Project
    echo -e "${BOLD}${MAGENTA}📁 Project:${RESET}"
    local proj_type="unknown"
    [[ -f "pyproject.toml" ]] && proj_type="Python"
    [[ -f "package.json" ]] && proj_type="Node.js"
    [[ -f "Cargo.toml" ]] && proj_type="Rust"
    [[ -f "go.mod" ]] && proj_type="Go"
    echo -e "   Type: $proj_type"
    
    # Detect Code Puppy project specifically
    if [[ -d "code_puppy" ]] && [[ -f "pyproject.toml" ]]; then
        echo -e "   ${GREEN}✓${RESET} This is the Code Puppy project!"
    fi
    echo ""
    
    # Agent tree
    if [[ "$SHOW_TREE" == true ]] || [[ "$VERBOSE" == true ]]; then
        build_agent_tree
    fi
    
    # Guidance stats
    echo -e "${BOLD}${GREEN}📊 Guidance Stats:${RESET}"
    echo -e "   Enabled: ${PUP_GUIDANCE_ENABLED:-${PUPPY_GUIDANCE_ENABLED:-true}}"
    echo -e "   Guidance shown: ${PUP_GUIDANCE_COUNT:-${PUPPY_GUIDANCE_COUNT:-0}}"
    echo ""
    
    # Suggested next actions
    echo -e "${BOLD}${BLUE}🎯 Suggested Actions:${RESET}"
    echo -e "   • Continue with current implementation"
    echo -e "   • Run tests: ${GRAY}pytest code_puppy/plugins/proactive_guidance/${RESET}"
    echo -e "   • Check progress: ${GRAY}bd list${RESET}"
    echo -e "   • View files: ${GRAY}ls -la code_puppy/plugins/proactive_guidance/${RESET}"
    echo ""
    
    echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}"
    echo -e "${GRAY}Run with --verbose for more details, --json for parsing${RESET}"
}

# Main
main() {
    case "$OUTPUT_FORMAT" in
        json)
            output_json
            ;;
        text)
            output_text
            ;;
    esac
}

main "$@"
