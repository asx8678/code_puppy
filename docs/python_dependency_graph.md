# Python Module Dependency Graph

> Generated for Python-to-Elixir migration planning. See [ADR-004](adr/ADR-004-python-to-elixir-migration-strategy.md).

**Generated**: 2026-01-01T00:00:00+00:00
**Total modules analyzed**: 521

## Summary Statistics

| Metric | Value |
|--------|-------|
| Total modules | 521 |
| Total lines of code | 145,692 |
| Leaf modules (no internal deps) | 144 |
| Hub modules (≥10 importers) | 22 |
| Import cycles detected | 106 |

## High-Fan-In Hub Modules (Port LAST)

> These modules are imported by many others. Porting them early breaks dependents.

| Module | Fan-In | Fan-Out | LOC |
|--------|--------|---------|-----|
| `messaging` | 131 | 10 | 268 |
| `config` | 109 | 12 | 2,694 |
| `callbacks` | 72 | 5 | 1,228 |
| `code_puppy` | 31 | 2 | 93 |
| `config_paths` | 31 | 1 | 427 |
| `tools.command_runner` | 27 | 8 | 1,812 |
| `agents` | 26 | 2 | 31 |
| `agents.base_agent` | 26 | 25 | 2,901 |
| `tools.common` | 25 | 9 | 1,315 |
| `agents.agent_manager` | 19 | 9 | 1,038 |
| `tui.base_screen` | 18 | 0 | 25 |
| `command_line.mcp.base` | 15 | 1 | 32 |
| `command_line.command_registry` | 14 | 0 | 150 |
| `mcp_.managed_server` | 14 | 5 | 442 |
| `model_factory` | 14 | 13 | 1,143 |

## Low-Dependency Leaf Candidates (Port FIRST)

> These modules have few or no internal dependencies. Safe to port early.

| Module | Fan-In | LOC | Notes |
|--------|--------|-----|-------|
| `tools.process_runner_protocol` | 0 | 370 | Pure leaf |
| `tool_schema` | 0 | 369 | Pure leaf |
| `mcp_.system_tools` | 0 | 207 | Pure leaf |
| `utils.editor_detect` | 0 | 137 | Pure leaf |
| `utils.gitignore` | 0 | 121 | Pure leaf |
| `utils.symbol_hierarchy` | 0 | 110 | Pure leaf |
| `plugins.frontend_emitter` | 0 | 24 | Pure leaf |
| `plugins.prompt_store` | 0 | 20 | Pure leaf |
| `plugins.session_logger` | 0 | 9 | Pure leaf |
| `plugins.ttsr` | 0 | 9 | Pure leaf |
| `plugins.repo_compass` | 0 | 8 | Pure leaf |
| `plugins.loop_detection` | 0 | 6 | Pure leaf |
| `plugins.shell_safety` | 0 | 6 | Pure leaf |
| `plugins.tracing_langfuse` | 0 | 6 | Pure leaf |
| `plugins.ollama_setup` | 0 | 5 | Pure leaf |
| `plugins.tracing_langsmith` | 0 | 5 | Pure leaf |
| `tui.screens` | 0 | 5 | Pure leaf |
| `plugins.file_permission_handler` | 0 | 4 | Pure leaf |
| `plugins.completion_notifier` | 0 | 3 | Pure leaf |
| `plugins.render_check` | 0 | 3 | Pure leaf |

## Import Cycles Detected

> Cycles must be broken before porting (refactor to remove circular deps).

1. `code_puppy → agents → agents.agent_manager → agents.base_agent → agents.agent_prompt_mixin → code_puppy`
2. `code_puppy → agents → agents.agent_manager → agents.base_agent → agents.agent_prompt_mixin → callbacks → code_puppy`
3. `code_puppy → agents → agents.agent_manager → agents.base_agent → agents.agent_prompt_mixin → callbacks → plugins → config → code_puppy`
4. `code_puppy → agents → agents.agent_manager → agents.base_agent → agents.agent_prompt_mixin → callbacks → plugins → config → config_package.loader → code_puppy`
5. `code_puppy → agents → agents.agent_manager → agents.base_agent → agents.agent_prompt_mixin → callbacks → plugins → config → model_factory → code_puppy`
6. `code_puppy → agents → agents.agent_manager → agents.base_agent → agents.agent_prompt_mixin → callbacks → plugins → config → model_factory → claude_cache_client → plugins.claude_code_oauth.utils → plugins.claude_code_oauth.config → code_puppy`
7. `code_puppy → agents → agents.agent_manager → agents.base_agent → agents.agent_prompt_mixin → callbacks → plugins → config → model_factory → model_utils → code_puppy`
8. `code_puppy → agents → agents.agent_manager → agents.base_agent → agents.agent_prompt_mixin → callbacks → plugins → config → session_storage → code_puppy`
9. `code_puppy → agents → agents.agent_manager → agents.base_agent → agents.agent_prompt_mixin → callbacks → plugins → config → session_storage → command_line.prompt_toolkit_completion → code_puppy`
10. `code_puppy → agents → agents.agent_manager → agents.base_agent → agents.agent_prompt_mixin → callbacks → plugins → config → session_storage → command_line.prompt_toolkit_completion → command_line.mcp_completion → mcp_.manager → mcp_.registry → code_puppy`

... and 96 more cycles

## Recommended Porting Order

> Ordered by dependency depth (leaves first). Within each depth, sorted by fan-in (lowest first).

| Phase | Modules | Criteria |
|-------|---------|----------|
| Foundation (depth=0) | `command_line`, `mcp_.system_tools`, `mcp_prompts`, `plugins.agent_shortcuts`, `plugins.auto_test_control` (+139 more) | Leaves → Hubs |
| Utilities (depth=1) | `code_puppy` | Leaves → Hubs |
| Core Services (depth=2) | `__main__`, `agent_pinning_transport`, `agents.agent_code_puppy`, `agents.agent_code_reviewer`, `agents.agent_code_scout` (+371 more) | Leaves → Hubs |

## Limitations

1. **Static analysis only**: Dynamic imports (importlib, __import__) not detected.
2. **Conditional imports**: Imports inside try/except or TYPE_CHECKING treated equally.
3. **Star imports**: `from x import *` dependencies may be incomplete.
4. **External dependencies**: Third-party package internals not analyzed.
5. **Runtime dependencies**: Plugin loading, config-driven imports not captured.

## Appendix: Modules by Depth

Full module data in [python_dependency_graph.json](python_dependency_graph.json).

### Depth 0 (144 modules)

| Module | Fan-In | Fan-Out | LOC |
|--------|--------|---------|-----|
| `tui.base_screen` | 18 | 0 | 25 |
| `command_line.command_registry` | 14 | 0 | 150 |
| `tui.widgets.searchable_list` | 14 | 0 | 256 |
| `tui.widgets.split_panel` | 14 | 0 | 47 |
| `messaging.messages` | 10 | 0 | 584 |
| `command_line.pagination` | 9 | 0 | 42 |
| `command_line.utils` | 9 | 0 | 92 |
| `permission_decision` | 8 | 0 | 67 |
| `run_context` | 8 | 0 | 264 |
| `tools.subagent_context` | 8 | 0 | 158 |
| `plugins.agent_trace.schema` | 7 | 0 | 264 |
| `utils.thread_safe_cache` | 7 | 0 | 43 |
| `plugins.agent_skills.metadata` | 6 | 0 | 260 |
| `tools.ask_user_question.constants` | 6 | 0 | 73 |
| `api.security` | 5 | 0 | 282 |
| `config_package.env_helpers` | 5 | 0 | 153 |
| `mcp_.mcp_security` | 5 | 0 | 513 |
| `plugins.turbo_executor.models` | 5 | 0 | 151 |
| `utils.file_display` | 5 | 0 | 389 |
| `command_line.clipboard` | 4 | 0 | 544 |

> ... 124 more at this depth

### Depth 1 (1 modules)

| Module | Fan-In | Fan-Out | LOC |
|--------|--------|---------|-----|
| `code_puppy` | 31 | 2 | 93 |

### Depth 2 (376 modules)

| Module | Fan-In | Fan-Out | LOC |
|--------|--------|---------|-----|
| `messaging` | 131 | 10 | 268 |
| `config` | 109 | 12 | 2,694 |
| `callbacks` | 72 | 5 | 1,228 |
| `config_paths` | 31 | 1 | 427 |
| `tools.command_runner` | 27 | 8 | 1,812 |
| `agents` | 26 | 2 | 31 |
| `agents.base_agent` | 26 | 25 | 2,901 |
| `tools.common` | 25 | 9 | 1,315 |
| `agents.agent_manager` | 19 | 9 | 1,038 |
| `command_line.mcp.base` | 15 | 1 | 32 |
| `mcp_.managed_server` | 14 | 5 | 442 |
| `model_factory` | 14 | 13 | 1,143 |
| `command_line.mcp.utils` | 12 | 2 | 127 |
| `config_package` | 12 | 4 | 63 |
| `plugins.elixir_bridge` | 12 | 1 | 725 |
| `command_line.model_picker_completion` | 10 | 6 | 423 |
| `async_utils` | 8 | 1 | 284 |
| `mcp_.manager` | 8 | 7 | 978 |
| `tools.browser.browser_manager` | 8 | 5 | 377 |
| `elixir_transport_helpers` | 7 | 1 | 263 |

> ... 356 more at this depth
