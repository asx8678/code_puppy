# Agent Tests

This directory contains tests for code-puppy's agent system.

## Snapshot Tests for System Prompts

System prompts are composed dynamically from multiple sources:
- Base agent prompt (`get_system_prompt()`)
- Platform context (OS, shell, date, git status)
- Agent identity (unique ID for task ownership coordination)
- Plugin additions (via `get_model_system_prompt` hook)

To prevent accidental drift, we snapshot-test each major agent's composed prompt.

### Running Snapshot Tests

```bash
# Compare against saved snapshots (normal CI/test run)
pytest tests/agents/test_system_prompt_snapshots.py -v

# Update snapshots after intentional prompt changes
pytest tests/agents/test_system_prompt_snapshots.py --update-snapshots -v
```

### When a Test Fails

1. **Check the diff**: The error message shows the first difference position
2. **If the change is intentional** (you meant to update the prompt):
   - Run with `--update-snapshots`
   - Review the refreshed snapshot in `tests/snapshots/system_prompts/`
   - Commit the updated `.md` file alongside your code change
3. **If the change was NOT intentional**:
   - Investigate what plugin or code change caused the drift
   - Fix the regression before merging

### Snapshot Organization

```
tests/snapshots/
├── system_prompts/          # Full prompts with platform context + identity
│   ├── code-puppy.md
│   ├── pack-leader.md
│   └── ...
└── base_prompts/            # Base prompts only (no platform/identity)
    ├── code-puppy.md
    └── ...
```

### Adding a New Agent to Snapshot Tests

1. Edit `AGENTS_TO_SNAPSHOT` in `test_system_prompt_snapshots.py`
2. Run with `--update-snapshots` to create the initial snapshot:
   ```bash
   pytest tests/agents/test_system_prompt_snapshots.py --update-snapshots -v
   ```
3. Review the snapshot for sensitive content (should contain no:
   - API keys, tokens, credentials
   - Absolute paths to user home directories
   - Timestamps, session IDs, or other ephemeral data
4. Commit both the test change and the new snapshot file

### Snapshotted Agents

The following agents have snapshot tests:

| Agent | File | Description |
|-------|------|-------------|
| code-puppy | `code-puppy.md` | Main code assistant agent |
| pack-leader | `pack-leader.md` | Multi-agent workflow orchestrator |
| turbo-executor | `turbo-executor.md` | Batch file operations specialist |
| security-auditor | `security-auditor.md` | Security audit and risk assessment |
| code-reviewer | `code-reviewer.md` | Code review specialist |
| terminal-qa | `terminal-qa.md` | Terminal/CLI question answering |
| python-programmer | `python-programmer.md` | Python-specific programming |
| qa-expert | `qa-expert.md` | Quality assurance testing |

### Normalization Details

Dynamic content is normalized to ensure deterministic snapshots:

| Dynamic Value | Placeholder | Example |
|---------------|-------------|---------|
| Current date | `<DATE>` | `2025-04-09` → `<DATE>` |
| Agent ID | `<AGENT_ID>` | `code-puppy-a3f2b1` → `<AGENT_ID>` |
| Working directory | `<CWD>` | `/home/user/projects/code_puppy` → `<CWD>` |
| Home directory | `<HOME>` | `/home/user` → `<HOME>` |
| Platform string | `<PLATFORM>` | `macOS-14.5-arm64` → `<PLATFORM>` |

See `_snapshot_helpers.py` for the normalization implementation.
