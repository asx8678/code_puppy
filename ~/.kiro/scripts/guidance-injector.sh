#!/bin/bash
# guidance-injector.sh - PostToolUse guidance hook for Kiro
# Injects follow-up guidance after tool execution based on tool type and context
# Receives tool info via KIRO_* environment variables

# Colors for output (optional, disabled if NO_COLOR is set)
if [[ -z "${NO_COLOR:-}" ]]; then
    BOLD='\033[1m'
    GREEN='\033[0;32m'
    YELLOW='\033[0;33m'
    BLUE='\033[0;34m'
    CYAN='\033[0;36m'
    RESET='\033[0m'
else
    BOLD=''
    GREEN=''
    YELLOW=''
    BLUE=''
    CYAN=''
    RESET=''
fi

# Get verbosity level from env or default to normal
VERBOSITY="${GUIDANCE_VERBOSITY:-normal}"

# Skip if guidance is disabled
[[ "${GUIDANCE_ENABLED:-true}" == "false" ]] && exit 0

# Skip if minimal verbosity and not a significant tool
if [[ "$VERBOSITY" == "minimal" ]]; then
    case "${KIRO_TOOL_NAME:-unknown}" in
        write_file|create_file|replace_in_file|run_shell_command|invoke_agent) ;;
        *) exit 0 ;;
    esac
fi

# Read tool info from environment variables
TOOL_NAME="${KIRO_TOOL_NAME:-unknown}"
TOOL_ARGS="${KIRO_TOOL_ARGS:-}"
TOOL_EXIT="${KIRO_TOOL_EXIT_CODE:-0}"
TOOL_DURATION="${KIRO_TOOL_DURATION_MS:-0}"
TOOL_OUTPUT="${KIRO_TOOL_OUTPUT:-}"

# Show header (skip if minimal verbosity)
if [[ "$VERBOSITY" != "minimal" ]]; then
    echo -e "${BOLD}🐾 Post-Tool Guidance${RESET}"
    echo ""
fi

case "$TOOL_NAME" in
    write_file|create_file)
        # Extract file path from args (first argument)
        FILE_PATH=""
        if [[ -n "$TOOL_ARGS" ]]; then
            # Try to extract the first argument as file path
            FILE_PATH=$(echo "$TOOL_ARGS" | awk '{print $1}')
        fi
        
        # Fallback: try to extract from output or common patterns
        if [[ -z "$FILE_PATH" ]]; then
            FILE_PATH=$(echo "$TOOL_OUTPUT" | grep -oE '[./][a-zA-Z0-9_./-]+\.[a-zA-Z0-9]+' | head -1)
        fi
        
        # Determine extension - either from the extracted file path or directly from args
        EXTENSION_LOWER=""
        if [[ -n "$FILE_PATH" ]]; then
            EXTENSION="${FILE_PATH##*.}"
            EXTENSION_LOWER=$(echo "$EXTENSION" | tr '[:upper:]' '[:lower:]')
        fi
        
        # If we can't determine extension, try to extract it from args directly
        if [[ -z "$EXTENSION_LOWER" && -n "$TOOL_ARGS" ]]; then
            EXT=$(echo "$TOOL_ARGS" | grep -oE '\.[a-zA-Z0-9]+$' | sed 's/^\.//' | head -1)
            [[ -n "$EXT" ]] && EXTENSION_LOWER=$(echo "$EXT" | tr '[:upper:]' '[:lower:]')
        fi
        
        # If we still don't have an extension, provide generic guidance
        if [[ -z "$EXTENSION_LOWER" ]]; then
            echo -e "${CYAN}✨ File created!${RESET}"
            echo ""
            echo -e "${GREEN}📂${RESET} Review the new file contents"
            echo -e "${GREEN}🔍${RESET} Check syntax before committing"
            [[ "$VERBOSITY" != "minimal" ]] && echo -e "${YELLOW}📝${RESET} Add tests if this is implementation code"
            exit 0
        fi
        
        # Use the file path in output, or fallback to a placeholder
        FILE_PATH="${FILE_PATH:-<file>}"
        
        echo -e "${CYAN}✨ Next steps for your new file:${RESET}"
        echo ""
        
        # Language-specific suggestions
        case "$EXTENSION_LOWER" in
            py)
                echo -e "${GREEN}💡${RESET} Run tests: pytest $FILE_PATH"
                echo -e "${GREEN}🔍${RESET} Check syntax: python -m py_compile $FILE_PATH"
                [[ "$VERBOSITY" != "minimal" ]] && echo -e "${GREEN}📝${RESET} Type check: mypy $FILE_PATH (if mypy installed)"
                ;;
            js|jsx|ts|tsx)
                echo -e "${GREEN}💡${RESET} Run tests: npm test"
                echo -e "${GREEN}🔍${RESET} Lint: npx eslint $FILE_PATH"
                [[ "$VERBOSITY" != "minimal" ]] && echo -e "${GREEN}📝${RESET} Type check: npx tsc --noEmit"
                ;;
            rs)
                echo -e "${GREEN}💡${RESET} Run tests: cargo test"
                echo -e "${GREEN}🔍${RESET} Check: cargo check"
                [[ "$VERBOSITY" != "minimal" ]] && echo -e "${GREEN}📝${RESET} Format: cargo fmt"
                ;;
            go)
                echo -e "${GREEN}💡${RESET} Run tests: go test ./..."
                echo -e "${GREEN}🔍${RESET} Build: go build"
                ;;
            java)
                echo -e "${GREEN}💡${RESET} Compile: javac $FILE_PATH"
                echo -e "${GREEN}🔍${RESET} Run tests: mvn test (if Maven project)"
                ;;
            sh|bash|zsh)
                echo -e "${GREEN}🔐${RESET} Check script: shellcheck $FILE_PATH (if installed)"
                echo -e "${GREEN}▶️${RESET} Make executable: chmod +x $FILE_PATH"
                [[ "$VERBOSITY" != "minimal" ]] && echo -e "${GREEN}📜${RESET} Run: ./$FILE_PATH"
                ;;
            md|rst|txt)
                echo -e "${GREEN}📝${RESET} Preview: head -20 $FILE_PATH"
                [[ "$VERBOSITY" != "minimal" ]] && echo -e "${GREEN}📊${RESET} Word count: wc -w $FILE_PATH"
                ;;
            json)
                echo -e "${GREEN}✅${RESET} Validate: python -c 'import json; json.load(open(\"$FILE_PATH\"))'"
                [[ "$VERBOSITY" != "minimal" ]] && echo -e "${GREEN}🔍${RESET} Pretty print: cat $FILE_PATH | python -m json.tool"
                ;;
            yaml|yml)
                echo -e "${GREEN}✅${RESET} Validate: python -c 'import yaml; yaml.safe_load(open(\"$FILE_PATH\"))' (if PyYAML installed)"
                ;;
            toml)
                echo -e "${GREEN}✅${RESET} Validate: python -c 'import tomllib; tomllib.load(open(\"$FILE_PATH\", \"rb\"))'"
                ;;
            html|htm)
                echo -e "${GREEN}🌐${RESET} Validate: Use W3C validator or html5validator"
                [[ "$VERBOSITY" != "minimal" ]] && echo -e "${GREEN}🔍${RESET} Preview: open $FILE_PATH (macOS)"
                ;;
            css)
                echo -e "${GREEN}🎨${RESET} Validate: npx stylelint $FILE_PATH"
                [[ "$VERBOSITY" != "minimal" ]] && echo -e "${GREEN}📦${RESET} Minify: npx cssnano $FILE_PATH"
                ;;
            *)
                echo -e "${GREEN}📂${RESET} View file: cat $FILE_PATH"
                echo -e "${GREEN}📊${RESET} File info: ls -la $FILE_PATH"
                ;;
        esac
        
        # General suggestions for all files (non-minimal verbosity)
        if [[ "$VERBOSITY" != "minimal" ]]; then
            echo ""
            echo -e "${YELLOW}📂${RESET} View file: cat $FILE_PATH"
            echo -e "${YELLOW}🔎${RESET} Search for usages: grep -r \"$(basename $FILE_PATH .${EXTENSION})\" ."
        fi
        
        # Verbose suggestions
        if [[ "$VERBOSITY" == "verbose" ]]; then
            echo ""
            echo -e "${BLUE}🧪${RESET} Create a test file for this implementation"
            echo -e "${BLUE}📊${RESET} Check git diff: git diff --stat"
        fi
        ;;
        
    replace_in_file)
        # Try to extract file path from args
        FILE_PATH="${TOOL_ARGS%%"${TOOL_ARGS#?}"}"
        if [[ -n "$TOOL_ARGS" ]]; then
            FILE_PATH=$(echo "$TOOL_ARGS" | awk '{print $1}')
        fi
        
        if [[ -z "$FILE_PATH" || ! -f "$FILE_PATH" ]]; then
            FILE_PATH=$(echo "$TOOL_OUTPUT" | grep -oE '[./][a-zA-Z0-9_./-]+\.[a-zA-Z0-9]+' | head -1)
        fi
        
        echo -e "${CYAN}✨ File modified successfully!${RESET}"
        echo ""
        
        if [[ -n "$FILE_PATH" && -f "$FILE_PATH" ]]; then
            echo -e "${GREEN}📂${RESET} View changes: git diff $FILE_PATH"
            echo -e "${GREEN}🔍${RESET} Check syntax: Depends on file type"
            [[ "$VERBOSITY" != "minimal" ]] && echo -e "${YELLOW}📝${RESET} Review: cat $FILE_PATH | head -30"
        else
            echo -e "${GREEN}📂${RESET} View changes: git diff"
            echo -e "${GREEN}🔍${RESET} Check affected files: git status"
        fi
        ;;
        
    run_shell_command|agent_run_shell_command|shell_command|shell)
        if [[ "$TOOL_EXIT" -eq 0 ]]; then
            echo -e "${CYAN}✅ Command completed successfully!${RESET}"
            echo ""
            
            # Context-aware suggestions based on command type
            # Extract command from args or output
            COMMAND="${TOOL_ARGS:-$TOOL_OUTPUT}"
            
            if [[ "$COMMAND" =~ (pytest|test|npm test|cargo test|go test) ]]; then
                echo -e "${GREEN}🎯${RESET} Tests passed! Ready to commit?"
                echo -e "${GREEN}📊${RESET} Coverage: pytest --cov (if pytest-cov installed)"
                [[ "$VERBOSITY" == "verbose" ]] && echo -e "${BLUE}📝${RESET} Save coverage report: pytest --cov --cov-report=html"
                
            elif [[ "$COMMAND" =~ (git add|git commit) ]]; then
                echo -e "${GREEN}🚀${RESET} Push changes: git push origin \$(git branch --show-current)"
                [[ "$VERBOSITY" != "minimal" ]] && echo -e "${YELLOW}🔄${RESET} Or create PR: gh pr create (if gh CLI installed)"
                
            elif [[ "$COMMAND" =~ (build|make|cargo build|npm run build|go build) ]]; then
                echo -e "${GREEN}🎯${RESET} Build succeeded! Run your binary or check build artifacts"
                [[ "$VERBOSITY" != "minimal" ]] && echo -e "${YELLOW}📦${RESET} Package: Check dist/ or target/ directories"
                
            elif [[ "$COMMAND" =~ (pip install|npm install|cargo add|go get) ]]; then
                echo -e "${GREEN}📦${RESET} Dependencies updated!"
                [[ "$COMMAND" =~ pip ]] && echo -e "${YELLOW}🔒${RESET} Lock: pip freeze > requirements.txt"
                [[ "$COMMAND" =~ npm ]] && echo -e "${YELLOW}🔒${RESET} Lock: npm shrinkwrap"
                [[ "$COMMAND" =~ cargo ]] && echo -e "${YELLOW}🔒${RESET} Lock: Cargo.lock updated automatically"
                
            elif [[ "$COMMAND" =~ (grep|find|rg) ]]; then
                echo -e "${GREEN}🔍${RESET} Found matches! Open interesting files to explore"
                
            elif [[ "$COMMAND" =~ (ls|tree|fd) ]]; then
                echo -e "${GREEN}📂${RESET} Explore further or run a command in those directories"
                
            elif [[ "$COMMAND" =~ (docker|podman) ]]; then
                echo -e "${GREEN}🐳${RESET} Container command executed! Check status with docker ps"
                
            elif [[ "$COMMAND" =~ (kubectl|helm) ]]; then
                echo -e "${GREEN}☸️${RESET} Kubernetes command executed! Check: kubectl get pods"
                
            else
                echo -e "${GREEN}▶️${RESET} Run similar command: Use ↑ in shell or command history"
            fi
            
            # General suggestions
            if [[ "$VERBOSITY" != "minimal" ]]; then
                echo ""
                echo -e "${YELLOW}📜${RESET} Command history: Press ↑ or run 'history | tail'"
            fi
        else
            echo -e "${CYAN}⚠️ Command failed with exit code $TOOL_EXIT${RESET}"
            echo ""
            echo -e "${YELLOW}🔧 Debug options:${RESET}"
            echo "   - Check error output above"
            echo "   - Run with verbose: Add -v or --verbose flags"
            echo "   - Check environment: env | grep -i <key>"
            [[ "$VERBOSITY" != "minimal" ]] && echo "   - Try: $TOOL_ARGS 2>&1 | head -50 (to see errors)"
        fi
        ;;
        
    invoke_agent|subagent)
        AGENT_NAME="${TOOL_ARGS:-agent}"
        # Extract just the agent name (first word)
        AGENT_NAME=$(echo "$AGENT_NAME" | awk '{print $1}')
        
        echo -e "${CYAN}🤖 Agent '$AGENT_NAME' completed!${RESET}"
        echo ""
        echo -e "${GREEN}📋${RESET} Review the agent's output above"
        [[ "$VERBOSITY" != "minimal" ]] && echo -e "${GREEN}🔄${RESET} Iterate: Make adjustments and re-invoke if needed"
        [[ "$VERBOSITY" == "verbose" ]] && echo -e "${BLUE}📝${RESET} Document learnings in code comments"
        ;;
        
    read_file|grep|list_files|search_files)
        echo -e "${CYAN}📖 Exploratory tool used${RESET}"
        echo ""
        echo -e "${GREEN}🔍${RESET} Next: Use findings to make changes or gather more info"
        echo -e "${GREEN}📝${RESET} Consider: read_file on interesting files found"
        [[ "$VERBOSITY" != "minimal" ]] && echo -e "${YELLOW}🎯${RESET} Action: Create or modify files based on what you learned"
        ;;
        
    ask_user_question|get_user_input)
        echo -e "${CYAN}💬 User input received${RESET}"
        echo ""
        echo -e "${GREEN}📝${RESET} Process the user's response"
        echo -e "${GREEN}🎯${RESET} Continue with the task using this input"
        ;;
        
    delete_file|delete_snippet)
        echo -e "${CYAN}🗑️ File/snippet removed${RESET}"
        echo ""
        echo -e "${YELLOW}⚠️${RESET} Verify the deletion was intentional"
        echo -e "${GREEN}🔍${RESET} Check: git status to see staged changes"
        [[ "$VERBOSITY" != "minimal" ]] && echo -e "${GREEN}📝${RESET} Run tests to ensure nothing broke"
        ;;
        
    *)
        # Unknown or generic tool - minimal output
        if [[ "$VERBOSITY" == "verbose" ]]; then
            echo -e "${YELLOW}⚠️ Tool '$TOOL_NAME' completed${RESET}"
            echo ""
            echo -e "${GREEN}📋${RESET} Review output above for next steps"
        fi
        ;;
esac

# Footer tip for non-minimal verbosity
if [[ "$VERBOSITY" != "minimal" ]]; then
    echo ""
    echo -e "${BOLD}💡 Tip:${RESET} Disable guidance with GUIDANCE_ENABLED=false or GUIDANCE_VERBOSITY=minimal"
fi

exit 0
