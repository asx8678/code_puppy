#!/bin/bash
# session-log.sh - Capture session events (temporary, auto-cleaned)
# Replaces bronze-capture.sh with clearer naming

LOG_DIR="$HOME/.kiro/memory/session-logs/$(date +%Y/%m/%d)"
mkdir -p "$LOG_DIR"

TASK_FILE="$HOME/.kiro/state/active_task.json"
TASK_ID=$(jq -r '.id // "no-task"' "$TASK_FILE" 2>/dev/null || echo "no-task")
TASK_CATEGORY=$(jq -r '.category // "unknown"' "$TASK_FILE" 2>/dev/null || echo "unknown")

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
EVENT_ID=$(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "evt-$(date +%s%N)")
EVENT_ID=$(echo "$EVENT_ID" | tr '[:upper:]' '[:lower:]')

TOOL_NAME="${KIRO_TOOL_NAME:-unknown}"
TOOL_ARGS="${KIRO_TOOL_ARGS:-}"
TOOL_EXIT="${KIRO_TOOL_EXIT_CODE:-0}"
TOOL_DURATION="${KIRO_TOOL_DURATION_MS:-0}"
TOOL_OUTPUT="${KIRO_TOOL_OUTPUT:-}"

# Truncate for storage
ARGS_EXCERPT="${TOOL_ARGS:0:200}"
OUTPUT_EXCERPT="${TOOL_OUTPUT:0:500}"

# Escape JSON
ARGS_EXCERPT=$(echo "$ARGS_EXCERPT" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\t/\\t/g' | tr '\n' ' ')
OUTPUT_EXCERPT=$(echo "$OUTPUT_EXCERPT" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\t/\\t/g' | tr '\n' ' ')

SUCCESS="true"
[[ "$TOOL_EXIT" != "0" ]] && SUCCESS="false"

# Append to daily log
cat >> "$LOG_DIR/events.jsonl" << EOF
{"id":"$EVENT_ID","ts":"$TIMESTAMP","task_id":"$TASK_ID","task_category":"$TASK_CATEGORY","tool":"$TOOL_NAME","args":"$ARGS_EXCERPT","exit_code":$TOOL_EXIT,"duration_ms":$TOOL_DURATION,"success":$SUCCESS,"excerpt":"$OUTPUT_EXCERPT"}
EOF

# Maintain quick-access recent events (last 100)
RECENT_FILE="$HOME/.kiro/memory/session-logs/recent.jsonl"
if [[ -f "$RECENT_FILE" ]]; then
  tail -99 "$RECENT_FILE" > "$RECENT_FILE.tmp" && mv "$RECENT_FILE.tmp" "$RECENT_FILE"
fi
echo "{\"id\":\"$EVENT_ID\",\"ts\":\"$TIMESTAMP\",\"tool\":\"$TOOL_NAME\",\"success\":$SUCCESS}" >> "$RECENT_FILE"

exit 0
