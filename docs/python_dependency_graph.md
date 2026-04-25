# Python Module Dependency Graph

> Generated for Python-to-Elixir migration planning. See [ADR-004](docs/adr/ADR-004-python-to-elixir-migration-strategy.md).

**Generated**: 2026-04-25T13:54:19.742452
**Total modules analyzed**: 521

## Summary Statistics

| Metric | Value |
|--------|-------|
| Total modules | 521 |
| Total lines of code | 145,692 |
| Leaf modules (no internal deps) | 196 |
| Hub modules (≥10 importers) | 15 |
| Import cycles detected | 19 |

## High-Fan-In Hub Modules (Port LAST)

> These modules are imported by many others. Porting them early breaks dependents.

| Module | Fan-In | Fan-Out | LOC | Description |
|--------|--------|---------|-----|-------------|
| `messaging` | 133 | 0 | 268 | |
| `config` | 108 | 29 | 2,694 | |
| `callbacks` | 72 | 13 | 1,228 | |
| `plugins` | 70 | 6 | 600 | |
| `tools` | 45 | 107 | 502 | |
| `agents` | 38 | 0 | 31 | |
| `command_line` | 38 | 0 | 1 | |
| `config_paths` | 31 | 2 | 427 | |
| `tools.command_runner` | 27 | 24 | 1,812 | |
| `mcp_` | 22 | 0 | 101 | |
| `tui` | 21 | 8 | 12 | |
| `utils` | 21 | 0 | 171 | |
| `tui.base_screen` | 18 | 0 | 25 | |
| `model_factory` | 14 | 25 | 1,143 | |
| `config_package` | 13 | 0 | 63 | |
| `scheduler` | 9 | 14 | 58 | |
| `permission_decision` | 8 | 0 | 67 | |
| `async_utils` | 8 | 2 | 284 | |
| `run_context` | 8 | 0 | 264 | |
| `session_storage` | 7 | 14 | 876 | |

## Low-Dependency Leaf Candidates (Port FIRST)

> These modules have few or no internal dependencies. Safe to port early.

| Module | Fan-In | LOC | Notes |
|--------|--------|-----|-------|
| `plugins.elixir_bridge.wire_protocol` | 0 | 1,575 | Pure leaf |
| `elixir_transport` | 3 | 823 | Imported by 3 |
| `plugins.elixir_bridge` | 0 | 725 | Pure leaf |
| `mcp_.health_monitor` | 0 | 606 | Pure leaf |
| `plugins.repo_compass.tech_stack` | 0 | 606 | Pure leaf |
| `plugins.universal_constructor.sandbox` | 0 | 600 | Pure leaf |
| `messaging.messages` | 0 | 584 | Pure leaf |
| `command_line.clipboard` | 0 | 544 | Pure leaf |
| `staged_changes` | 1 | 526 | Imported by 1 |
| `request_cache` | 0 | 515 | Pure leaf |
| `mcp_.mcp_security` | 4 | 513 | Imported by 4 |
| `api.pty_manager` | 2 | 478 | Imported by 2 |
| `mcp_.error_isolation` | 0 | 436 | Pure leaf |
| `tools.ask_user_question.tui_loop` | 0 | 427 | Pure leaf |
| `terminal_utils` | 4 | 421 | Imported by 4 |
| `chatgpt_codex_client` | 1 | 406 | Imported by 1 |
| `command_line.attachments` | 0 | 391 | Pure leaf |
| `utils.file_display` | 0 | 389 | Pure leaf |
| `capability.registry` | 0 | 372 | Pure leaf |
| `tools.process_runner_protocol` | 0 | 370 | Pure leaf |
| `utils.parallel` | 0 | 370 | Pure leaf |
| `tool_schema` | 0 | 369 | Pure leaf |
| `mcp_.status_tracker` | 0 | 355 | Pure leaf |
| `utils.adaptive_render` | 1 | 352 | Imported by 1 |
| `utils.file_mutex` | 0 | 352 | Pure leaf |
| `mcp_.retry_manager` | 1 | 350 | Imported by 1 |
| `plugins.session_logger.writer` | 0 | 337 | Pure leaf |
| `agents.agent_terminal_qa` | 0 | 330 | Pure leaf |
| `utils.config_resolve` | 0 | 324 | Pure leaf |
| `tools.ask_user_question.renderers` | 0 | 313 | Pure leaf |

## Import Cycles Detected

> Cycles must be broken before porting (refactor to remove circular deps).

1. `config_paths → persistence → config_paths`
2. `callbacks → plugins → config → model_factory → model_utils → callbacks`
3. `callbacks → plugins → config → model_factory → model_config → callbacks`
4. `config → model_factory → config`
5. `config → model_factory → plugins → config`
6. `claude_cache_client → plugins → config → model_factory → claude_cache_client`
7. `config → model_factory → round_robin_model → plugins → config`
8. `callbacks → plugins → config → model_factory → callbacks`
9. `config → session_storage → config`
10. `config → runtime_state → config`

... and 9 more cycles

## Recommended Porting Order

> Ordered by dependency depth (leaves first). Modules at same depth sorted by fan-in (lowest first).

| Phase | Modules | Criteria |
|-------|---------|----------|
| Foundation (depth=0) | `messaging`, `agents`, `command_line`, `mcp_`, `utils` (+191 more) | Leaves → Hubs |
| Utilities (depth=1) | `config_paths`, `tui`, `elixir_transport_helpers`, `api`, `console` (+44 more) | Leaves → Hubs |
| Core Services (depth=2) | `model_factory`, `session_storage`, `persistence`, `runtime_state`, `policy_config` (+21 more) | Leaves → Hubs |
| Agents (depth=3) | `config`, `compaction.thresholds`, `test_model_factory`, `plugins.repo_compass.marker_merge`, `plugins.synthetic_status.status_api` | Leaves → Hubs |
| Integration (depth=4) | `plugins`, `error_logging`, `scheduler.config`, `policy_engine`, `keymap` (+46 more) | Leaves → Hubs |
| Integration (depth=5) | `callbacks`, `scheduler`, `model_packs`, `concurrency_limits`, `adaptive_rate_limiter` (+37 more) | Leaves → Hubs |
| Integration (depth=6) | `async_utils`, `model_utils`, `workflow_state`, `http_utils`, `pydantic_patches` (+55 more) | Leaves → Hubs |
| Integration (depth=7) | `tools`, `repl_session`, `summarization_agent`, `resilience`, `tools.file_operations` (+8 more) | Leaves → Hubs |
| Integration (depth=8) | `code_context`, `security`, `command_line.staged_commands`, `tools.display`, `tools.scheduler_tools` (+30 more) | Leaves → Hubs |
| Integration (depth=9) | `tools.command_runner`, `plugins.git_auto_commit.shell_bridge`, `plugins.code_explorer`, `plugins.code_explorer.register_callbacks` | Leaves → Hubs |
| Integration (depth=10) | `agents.base_agent`, `command_line.add_model_menu`, `command_line.colors_menu`, `messaging.queue_console`, `command_line.uc_menu` (+18 more) | Leaves → Hubs |
| Integration (depth=11) | `command_line.command_handler`, `agents.agent_turbo_executor`, `agents.agent_code_scout`, `agents.agent_manager`, `plugins.shell_safety.agent_shell_safety` (+2 more) | Leaves → Hubs |
| Integration (depth=12) | `interactive_loop`, `tui.app`, `command_line.core_commands`, `command_line.config_commands`, `api.routers.commands` (+1 more) | Leaves → Hubs |
| Integration (depth=13) | `app_runner` | Leaves → Hubs |
| Integration (depth=14) | `cli_runner` | Leaves → Hubs |
| Integration (depth=15) | `main` | Leaves → Hubs |
| Integration (depth=16) | `__main__` | Leaves → Hubs |

## Limitations of This Analysis

1. **Static analysis only**: Dynamic imports (`importlib`, `__import__`) are not detected.
2. **Conditional imports**: Imports inside `try/except` or `if TYPE_CHECKING` are treated equally.
3. **Star imports**: `from x import *` dependencies may be incomplete.
4. **External dependencies**: Third-party package internals are not analyzed.
5. **Runtime dependencies**: Plugin loading, config-driven imports are not captured.

For complete accuracy, supplement with runtime profiling and manual review.

## Appendix: All Modules

| Module | Fan-In | Fan-Out | LOC |
|--------|--------|---------|-----|
| `` | 0 | 0 | 93 |
| `__main__` | 0 | 2 | 10 |
| `_backlog` | 1 | 0 | 109 |
| `adaptive_rate_limiter` | 3 | 5 | 1,164 |
| `agent_model_pinning` | 3 | 8 | 190 |
| `agent_pinning_transport` | 0 | 2 | 167 |
| `agents` | 38 | 0 | 31 |
| `agents.agent_code_puppy` | 0 | 3 | 115 |
| `agents.agent_code_reviewer` | 0 | 0 | 97 |
| `agents.agent_code_scout` | 0 | 2 | 152 |
| `agents.agent_creator_agent` | 0 | 9 | 609 |
| `agents.agent_golang_reviewer` | 0 | 0 | 157 |
| `agents.agent_helios` | 0 | 0 | 130 |
| `agents.agent_javascript_reviewer` | 0 | 0 | 167 |
| `agents.agent_manager` | 0 | 20 | 1,038 |
| `agents.agent_pack_leader` | 0 | 2 | 343 |
| `agents.agent_planning` | 0 | 2 | 171 |
| `agents.agent_prompt_mixin` | 1 | 2 | 127 |
| `agents.agent_python_programmer` | 0 | 0 | 188 |
| `agents.agent_python_reviewer` | 0 | 0 | 97 |
| `agents.agent_qa_expert` | 0 | 0 | 170 |
| `agents.agent_qa_kitten` | 0 | 0 | 215 |
| `agents.agent_scheduler` | 0 | 0 | 128 |
| `agents.agent_security_auditor` | 0 | 0 | 188 |
| `agents.agent_state` | 1 | 2 | 152 |
| `agents.agent_terminal_qa` | 0 | 0 | 330 |
| `agents.agent_turbo_executor` | 1 | 11 | 175 |
| `agents.agent_typescript_reviewer` | 0 | 0 | 173 |
| `agents.base_agent` | 4 | 75 | 2,901 |
| `agents.event_stream_handler` | 0 | 14 | 471 |
| `agents.json_agent` | 0 | 7 | 212 |
| `agents.pack` | 0 | 0 | 29 |
| `agents.pack.retriever` | 0 | 2 | 385 |
| `agents.pack.shepherd` | 0 | 2 | 346 |
| `agents.pack.terrier` | 0 | 2 | 287 |
| `agents.pack.watchdog` | 0 | 2 | 368 |
| `agents.prompt_reviewer` | 0 | 2 | 146 |
| `agents.stream_event_normalizer` | 0 | 0 | 155 |
| `agents.subagent_stream_handler` | 0 | 10 | 297 |
| `api` | 5 | 2 | 13 |
| `api.app` | 0 | 13 | 174 |
| `api.main` | 0 | 2 | 21 |
| `api.pty_manager` | 2 | 0 | 478 |
| `api.routers` | 0 | 5 | 12 |
| `api.routers.agents` | 0 | 3 | 36 |
| `api.routers.commands` | 0 | 10 | 382 |
| `api.routers.config` | 0 | 7 | 122 |
| `api.routers.sessions` | 0 | 12 | 406 |
| `api.schemas` | 0 | 0 | 29 |
| `api.security` | 5 | 0 | 282 |
| `api.websocket` | 0 | 9 | 341 |
| `app_runner` | 1 | 56 | 485 |
| `async_utils` | 8 | 2 | 284 |
| `callbacks` | 72 | 13 | 1,228 |
| `capability` | 0 | 0 | 76 |
| `capability.builtin_providers` | 0 | 2 | 187 |
| `capability.registry` | 0 | 0 | 372 |
| `capability.types` | 0 | 0 | 85 |
| `chatgpt_codex_client` | 1 | 0 | 406 |
| `circuit_state` | 3 | 0 | 24 |
| `claude_cache_client` | 3 | 4 | 1,068 |
| `cli_runner` | 1 | 12 | 179 |
| `code_context` | 3 | 8 | 225 |
| `code_context.explorer` | 0 | 9 | 449 |
| `code_context.models` | 2 | 0 | 185 |
| `command_line` | 38 | 0 | 1 |
| `command_line.add_model_menu` | 2 | 20 | 1,155 |
| `command_line.agent_menu` | 0 | 25 | 611 |
| `command_line.attachments` | 0 | 0 | 391 |
| `command_line.autosave_menu` | 0 | 15 | 707 |
| `command_line.clipboard` | 0 | 0 | 544 |
| `command_line.colors_menu` | 2 | 7 | 534 |
| `command_line.command_handler` | 6 | 23 | 314 |
| `command_line.command_registry` | 0 | 0 | 150 |
| `command_line.concurrency_commands` | 0 | 12 | 97 |
| `command_line.config_commands` | 0 | 57 | 673 |
| `command_line.core_commands` | 0 | 59 | 787 |
| `command_line.diff_menu` | 0 | 11 | 864 |
| `command_line.file_path_completion` | 0 | 0 | 71 |
| `command_line.load_context_completion` | 1 | 2 | 52 |
| `command_line.mcp` | 0 | 0 | 10 |
| `command_line.mcp.base` | 0 | 2 | 32 |
| `command_line.mcp.catalog_server_installer` | 0 | 8 | 174 |
| `command_line.mcp.custom_server_form` | 0 | 9 | 675 |
| `command_line.mcp.custom_server_installer` | 0 | 11 | 195 |
| `command_line.mcp.edit_command` | 0 | 8 | 130 |
| `command_line.mcp.handler` | 0 | 2 | 138 |
| `command_line.mcp.help_command` | 0 | 3 | 146 |
| `command_line.mcp.install_command` | 0 | 8 | 212 |
| `command_line.mcp.install_menu` | 0 | 10 | 703 |
| `command_line.mcp.list_command` | 0 | 5 | 93 |
| `command_line.mcp.logs_command` | 0 | 9 | 230 |
| `command_line.mcp.remove_command` | 0 | 5 | 81 |
| `command_line.mcp.restart_command` | 0 | 4 | 99 |
| `command_line.mcp.search_command` | 0 | 6 | 115 |
| `command_line.mcp.start_all_command` | 0 | 4 | 134 |
| `command_line.mcp.start_command` | 0 | 4 | 110 |
| `command_line.mcp.status_command` | 0 | 7 | 184 |
| `command_line.mcp.stop_all_command` | 0 | 4 | 111 |
| `command_line.mcp.stop_command` | 0 | 3 | 78 |
| `command_line.mcp.test_command` | 0 | 3 | 106 |
| `command_line.mcp.utils` | 0 | 4 | 127 |
| `command_line.mcp.wizard_utils` | 0 | 10 | 329 |
| `command_line.mcp_completion` | 0 | 2 | 173 |
| `command_line.model_picker_completion` | 0 | 15 | 423 |
| `command_line.model_settings_menu` | 0 | 22 | 952 |
| `command_line.motd` | 0 | 6 | 93 |
| `command_line.onboarding_slides` | 0 | 0 | 178 |
| `command_line.onboarding_wizard` | 0 | 6 | 346 |
| `command_line.pack_commands` | 0 | 10 | 107 |
| `command_line.pagination` | 0 | 0 | 42 |
| `command_line.pin_command_completion` | 1 | 9 | 329 |
| `command_line.preset_commands` | 1 | 13 | 88 |
| `command_line.prompt_toolkit_completion` | 0 | 39 | 843 |
| `command_line.repl_commands` | 0 | 13 | 181 |
| `command_line.session_commands` | 1 | 25 | 308 |
| `command_line.shell_passthrough` | 0 | 2 | 232 |
| `command_line.skills_completion` | 0 | 2 | 158 |
| `command_line.staged_commands` | 1 | 13 | 342 |
| `command_line.uc_menu` | 1 | 19 | 901 |
| `command_line.utils` | 0 | 0 | 92 |
| `command_line.wiggum_state` | 3 | 0 | 77 |
| `command_line.workflow_commands` | 0 | 10 | 113 |
| `compaction` | 2 | 18 | 48 |
| `compaction.file_ops_tracker` | 0 | 0 | 198 |
| `compaction.history_offload` | 0 | 9 | 281 |
| `compaction.shadow_mode` | 2 | 4 | 154 |
| `compaction.thresholds` | 1 | 9 | 136 |
| `compaction.tool_arg_truncation` | 1 | 0 | 305 |
| `concurrency_limits` | 4 | 6 | 462 |
| `config` | 108 | 29 | 2,694 |
| `config_package` | 13 | 0 | 63 |
| `config_package._resolvers` | 1 | 3 | 229 |
| `config_package.env_helpers` | 4 | 0 | 153 |
| `config_package.loader` | 0 | 16 | 450 |
| `config_package.models` | 1 | 0 | 226 |
| `config_paths` | 31 | 2 | 427 |
| `config_presets` | 2 | 12 | 243 |
| `console` | 4 | 2 | 93 |
| `constants` | 3 | 0 | 107 |
| `dbos_utils` | 3 | 10 | 138 |
| `elixir_transport` | 3 | 0 | 823 |
| `elixir_transport_helpers` | 7 | 2 | 263 |
| `error_logging` | 6 | 2 | 319 |
| `errors` | 1 | 0 | 113 |
| `hook_engine` | 1 | 0 | 21 |
| `hook_engine.aliases` | 0 | 0 | 154 |
| `hook_engine.engine` | 0 | 0 | 213 |
| `hook_engine.executor` | 0 | 0 | 299 |
| `hook_engine.matcher` | 0 | 0 | 201 |
| `hook_engine.models` | 0 | 0 | 227 |
| `hook_engine.registry` | 0 | 0 | 106 |
| `hook_engine.validator` | 0 | 0 | 144 |
| `http_utils` | 3 | 10 | 417 |
| `interactive_loop` | 1 | 79 | 679 |
| `keymap` | 4 | 4 | 128 |
| `main` | 1 | 2 | 10 |
| `mcp_` | 22 | 0 | 101 |
| `mcp_.async_lifecycle` | 1 | 0 | 286 |
| `mcp_.blocking_startup` | 1 | 6 | 474 |
| `mcp_.captured_stdio_server` | 0 | 2 | 274 |
| `mcp_.circuit_breaker` | 0 | 4 | 285 |
| `mcp_.config_wizard` | 0 | 19 | 555 |
| `mcp_.dashboard` | 0 | 0 | 307 |
| `mcp_.error_isolation` | 0 | 0 | 436 |
| `mcp_.examples.retry_example` | 0 | 3 | 226 |
| `mcp_.health_monitor` | 0 | 0 | 606 |
| `mcp_.managed_server` | 0 | 12 | 442 |
| `mcp_.manager` | 0 | 4 | 978 |
| `mcp_.mcp_logs` | 0 | 2 | 223 |
| `mcp_.mcp_security` | 4 | 0 | 513 |
| `mcp_.registry` | 0 | 2 | 450 |
| `mcp_.retry_manager` | 1 | 0 | 350 |
| `mcp_.server_registry_catalog` | 0 | 5 | 1,142 |
| `mcp_.status_tracker` | 0 | 0 | 355 |
| `mcp_.system_tools` | 0 | 0 | 207 |
| `mcp_prompts` | 0 | 0 | 1 |
| `mcp_prompts.hook_creator` | 1 | 0 | 103 |
| `message_transport` | 1 | 2 | 315 |
| `messaging` | 133 | 0 | 268 |
| `messaging.bus` | 0 | 5 | 891 |
| `messaging.commands` | 0 | 0 | 164 |
| `messaging.history_buffer` | 0 | 6 | 313 |
| `messaging.markdown_patches` | 0 | 0 | 53 |
| `messaging.message_queue` | 0 | 4 | 448 |
| `messaging.messages` | 0 | 0 | 584 |
| `messaging.queue_console` | 1 | 2 | 269 |
| `messaging.renderers` | 0 | 0 | 291 |
| `messaging.rich_renderer` | 0 | 25 | 1,564 |
| `messaging.spinner` | 0 | 2 | 184 |
| `messaging.spinner.console_spinner` | 0 | 5 | 252 |
| `messaging.spinner.spinner_base` | 0 | 2 | 95 |
| `messaging.subagent_console` | 1 | 2 | 452 |
| `model_availability` | 1 | 0 | 153 |
| `model_config` | 1 | 2 | 171 |
| `model_factory` | 14 | 25 | 1,143 |
| `model_packs` | 5 | 7 | 237 |
| `model_switching` | 4 | 7 | 57 |
| `model_utils` | 5 | 2 | 124 |
| `models_dev_parser` | 2 | 4 | 685 |
| `permission_decision` | 8 | 0 | 67 |
| `persistence` | 4 | 6 | 368 |
| `plugins` | 70 | 6 | 600 |
| `plugins.agent_memory` | 0 | 0 | 100 |
| `plugins.agent_memory.agent_run_end` | 0 | 2 | 84 |
| `plugins.agent_memory.commands` | 0 | 7 | 303 |
| `plugins.agent_memory.config` | 0 | 2 | 205 |
| `plugins.agent_memory.core` | 0 | 2 | 152 |
| `plugins.agent_memory.extraction` | 0 | 0 | 276 |
| `plugins.agent_memory.messaging` | 0 | 4 | 128 |
| `plugins.agent_memory.processing` | 0 | 2 | 383 |
| `plugins.agent_memory.prompts` | 0 | 4 | 150 |
| `plugins.agent_memory.register_callbacks` | 0 | 2 | 54 |
| `plugins.agent_memory.signal_safeguards` | 0 | 4 | 361 |
| `plugins.agent_memory.signals` | 0 | 0 | 279 |
| `plugins.agent_memory.storage` | 0 | 5 | 387 |
| `plugins.agent_memory.updater` | 0 | 5 | 233 |
| `plugins.agent_shortcuts` | 0 | 0 | 1 |
| `plugins.agent_shortcuts.register_callbacks` | 0 | 12 | 122 |
| `plugins.agent_skills` | 0 | 0 | 22 |
| `plugins.agent_skills.config` | 0 | 5 | 204 |
| `plugins.agent_skills.discovery` | 0 | 4 | 141 |
| `plugins.agent_skills.downloader` | 0 | 9 | 419 |
| `plugins.agent_skills.installer` | 0 | 0 | 19 |
| `plugins.agent_skills.metadata` | 0 | 0 | 260 |
| `plugins.agent_skills.prompt_builder` | 0 | 0 | 134 |
| `plugins.agent_skills.register_callbacks` | 0 | 25 | 374 |
| `plugins.agent_skills.remote_catalog` | 0 | 3 | 335 |
| `plugins.agent_skills.skill_catalog` | 0 | 2 | 253 |
| `plugins.agent_skills.skills_install_menu` | 0 | 22 | 684 |
| `plugins.agent_skills.skills_menu` | 0 | 31 | 798 |
| `plugins.agent_trace` | 0 | 48 | 116 |
| `plugins.agent_trace.analytics` | 0 | 8 | 530 |
| `plugins.agent_trace.cli_analytics` | 0 | 8 | 408 |
| `plugins.agent_trace.cli_renderer` | 0 | 7 | 470 |
| `plugins.agent_trace.emitter` | 0 | 10 | 268 |
| `plugins.agent_trace.reducer` | 0 | 6 | 420 |
| `plugins.agent_trace.register_callbacks` | 0 | 37 | 706 |
| `plugins.agent_trace.schema` | 0 | 0 | 264 |
| `plugins.agent_trace.store` | 0 | 8 | 181 |
| `plugins.auto_test_control` | 0 | 0 | 1 |
| `plugins.auto_test_control.register_callbacks` | 0 | 12 | 340 |
| `plugins.chatgpt_oauth` | 0 | 0 | 6 |
| `plugins.chatgpt_oauth.config` | 0 | 2 | 55 |
| `plugins.chatgpt_oauth.oauth_flow` | 0 | 7 | 313 |
| `plugins.chatgpt_oauth.register_callbacks` | 0 | 12 | 198 |
| `plugins.chatgpt_oauth.utils` | 0 | 2 | 724 |
| `plugins.claude_code_hooks` | 0 | 0 | 1 |
| `plugins.claude_code_hooks.config` | 0 | 2 | 158 |
| `plugins.claude_code_hooks.register_callbacks` | 0 | 5 | 170 |
| `plugins.claude_code_oauth` | 0 | 0 | 25 |
| `plugins.claude_code_oauth.config` | 0 | 2 | 55 |
| `plugins.claude_code_oauth.register_callbacks` | 0 | 24 | 472 |
| `plugins.claude_code_oauth.token_refresh_heartbeat` | 0 | 0 | 235 |
| `plugins.claude_code_oauth.utils` | 0 | 2 | 914 |
| `plugins.clean_command` | 0 | 0 | 1 |
| `plugins.clean_command.register_callbacks` | 0 | 13 | 412 |
| `plugins.code_explorer` | 0 | 11 | 31 |
| `plugins.code_explorer.register_callbacks` | 0 | 12 | 544 |
| `plugins.code_skeleton` | 0 | 0 | 0 |
| `plugins.code_skeleton.register_callbacks` | 0 | 4 | 155 |
| `plugins.code_skeleton.skeleton` | 0 | 0 | 220 |
| `plugins.completion_notifier` | 0 | 0 | 3 |
| `plugins.completion_notifier.register_callbacks` | 0 | 7 | 204 |
| `plugins.cost_estimator` | 0 | 0 | 0 |
| `plugins.cost_estimator.estimator` | 0 | 2 | 237 |
| `plugins.cost_estimator.register_callbacks` | 0 | 4 | 184 |
| `plugins.customizable_commands` | 0 | 0 | 0 |
| `plugins.customizable_commands.register_callbacks` | 0 | 5 | 152 |
| `plugins.dual_home.register_callbacks` | 0 | 7 | 116 |
| `plugins.elixir_bridge` | 0 | 0 | 725 |
| `plugins.elixir_bridge.bridge_controller` | 0 | 29 | 1,605 |
| `plugins.elixir_bridge.register_callbacks` | 0 | 6 | 358 |
| `plugins.elixir_bridge.wire_protocol` | 0 | 0 | 1,575 |
| `plugins.error_classifier` | 0 | 0 | 41 |
| `plugins.error_classifier.builtins` | 0 | 0 | 298 |
| `plugins.error_classifier.exinfo` | 0 | 0 | 58 |
| `plugins.error_classifier.register_callbacks` | 0 | 6 | 148 |
| `plugins.error_classifier.registry` | 0 | 0 | 166 |
| `plugins.error_logger` | 0 | 0 | 1 |
| `plugins.error_logger.register_callbacks` | 0 | 11 | 165 |
| `plugins.example_custom_command.register_callbacks` | 0 | 4 | 51 |
| `plugins.fast_puppy.register_callbacks` | 0 | 2 | 23 |
| `plugins.file_mentions` | 0 | 0 | 0 |
| `plugins.file_mentions.register_callbacks` | 0 | 2 | 317 |
| `plugins.file_permission_handler` | 0 | 0 | 4 |
| `plugins.file_permission_handler.register_callbacks` | 0 | 17 | 521 |
| `plugins.frontend_emitter` | 0 | 0 | 24 |
| `plugins.frontend_emitter.emitter` | 0 | 6 | 177 |
| `plugins.frontend_emitter.register_callbacks` | 0 | 4 | 267 |
| `plugins.git_auto_commit` | 0 | 22 | 98 |
| `plugins.git_auto_commit.cli` | 0 | 9 | 181 |
| `plugins.git_auto_commit.commit_flow` | 0 | 4 | 347 |
| `plugins.git_auto_commit.context_guard` | 0 | 4 | 255 |
| `plugins.git_auto_commit.policy_errors` | 0 | 0 | 120 |
| `plugins.git_auto_commit.register_callbacks` | 0 | 4 | 249 |
| `plugins.git_auto_commit.shell_bridge` | 0 | 2 | 241 |
| `plugins.hook_creator` | 0 | 0 | 1 |
| `plugins.hook_creator.register_callbacks` | 0 | 6 | 33 |
| `plugins.hook_manager` | 0 | 0 | 1 |
| `plugins.hook_manager.config` | 0 | 3 | 292 |
| `plugins.hook_manager.hooks_menu` | 0 | 4 | 559 |
| `plugins.hook_manager.register_callbacks` | 0 | 7 | 227 |
| `plugins.loop_detection` | 0 | 0 | 6 |
| `plugins.loop_detection.register_callbacks` | 0 | 10 | 510 |
| `plugins.oauth_puppy_html` | 0 | 0 | 224 |
| `plugins.ollama_setup` | 0 | 0 | 5 |
| `plugins.ollama_setup.completer` | 0 | 2 | 36 |
| `plugins.ollama_setup.register_callbacks` | 0 | 9 | 362 |
| `plugins.pack_parallelism` | 0 | 0 | 0 |
| `plugins.pack_parallelism.register_callbacks` | 0 | 10 | 479 |
| `plugins.pack_parallelism.run_limiter` | 0 | 5 | 838 |
| `plugins.pop_command` | 0 | 0 | 1 |
| `plugins.pop_command.register_callbacks` | 0 | 9 | 166 |
| `plugins.proactive_guidance` | 0 | 0 | 2 |
| `plugins.proactive_guidance._guidance` | 0 | 0 | 271 |
| `plugins.proactive_guidance.register_callbacks` | 0 | 11 | 356 |
| `plugins.prompt_store` | 0 | 0 | 20 |
| `plugins.prompt_store.commands` | 0 | 8 | 559 |
| `plugins.prompt_store.register_callbacks` | 0 | 2 | 47 |
| `plugins.prompt_store.store` | 0 | 6 | 393 |
| `plugins.remember_last_agent` | 0 | 0 | 9 |
| `plugins.remember_last_agent.register_callbacks` | 0 | 7 | 94 |
| `plugins.remember_last_agent.storage` | 0 | 4 | 66 |
| `plugins.render_check` | 0 | 0 | 3 |
| `plugins.render_check.register_callbacks` | 0 | 4 | 229 |
| `plugins.repo_compass` | 0 | 0 | 8 |
| `plugins.repo_compass.config` | 0 | 2 | 50 |
| `plugins.repo_compass.decision_markers` | 0 | 0 | 287 |
| `plugins.repo_compass.formatter` | 0 | 0 | 38 |
| `plugins.repo_compass.indexer` | 0 | 0 | 112 |
| `plugins.repo_compass.marker_merge` | 0 | 2 | 150 |
| `plugins.repo_compass.register_callbacks` | 0 | 2 | 160 |
| `plugins.repo_compass.tech_stack` | 0 | 0 | 606 |
| `plugins.repo_compass.turbo_indexer_bridge` | 0 | 3 | 48 |
| `plugins.scheduler` | 0 | 0 | 1 |
| `plugins.scheduler.register_callbacks` | 0 | 13 | 85 |
| `plugins.scheduler.scheduler_menu` | 0 | 26 | 542 |
| `plugins.scheduler.scheduler_wizard` | 0 | 9 | 344 |
| `plugins.session_logger` | 0 | 0 | 9 |
| `plugins.session_logger.config` | 0 | 3 | 36 |
| `plugins.session_logger.register_callbacks` | 0 | 10 | 432 |
| `plugins.session_logger.writer` | 0 | 0 | 337 |
| `plugins.shell_safety` | 0 | 0 | 6 |
| `plugins.shell_safety.agent_shell_safety` | 0 | 2 | 69 |
| `plugins.shell_safety.command_cache` | 0 | 0 | 146 |
| `plugins.shell_safety.regex_classifier` | 0 | 2 | 900 |
| `plugins.shell_safety.register_callbacks` | 0 | 25 | 465 |
| `plugins.supervisor_review` | 0 | 0 | 1 |
| `plugins.supervisor_review.models` | 0 | 0 | 156 |
| `plugins.supervisor_review.orchestrator` | 0 | 13 | 538 |
| `plugins.supervisor_review.register_callbacks` | 0 | 6 | 141 |
| `plugins.supervisor_review.satisfaction` | 0 | 6 | 412 |
| `plugins.synthetic_status` | 0 | 0 | 1 |
| `plugins.synthetic_status.register_callbacks` | 0 | 8 | 123 |
| `plugins.synthetic_status.status_api` | 0 | 2 | 140 |
| `plugins.theme_switcher` | 0 | 0 | 3 |
| `plugins.theme_switcher.register_callbacks` | 0 | 4 | 143 |
| `plugins.tool_allowlist` | 0 | 0 | 1 |
| `plugins.tool_allowlist.register_callbacks` | 0 | 6 | 242 |
| `plugins.tracing_langfuse` | 0 | 0 | 6 |
| `plugins.tracing_langfuse.register_callbacks` | 0 | 8 | 467 |
| `plugins.tracing_langsmith` | 0 | 0 | 5 |
| `plugins.tracing_langsmith.register_callbacks` | 0 | 8 | 464 |
| `plugins.ttsr` | 0 | 0 | 9 |
| `plugins.ttsr.register_callbacks` | 0 | 7 | 294 |
| `plugins.ttsr.rule_loader` | 0 | 0 | 226 |
| `plugins.ttsr.stream_watcher` | 0 | 2 | 275 |
| `plugins.turbo_executor` | 0 | 13 | 33 |
| `plugins.turbo_executor.models` | 0 | 0 | 151 |
| `plugins.turbo_executor.notifications` | 0 | 6 | 261 |
| `plugins.turbo_executor.orchestrator` | 0 | 14 | 471 |
| `plugins.turbo_executor.register_callbacks` | 0 | 15 | 397 |
| `plugins.turbo_executor.summarizer` | 0 | 5 | 407 |
| `plugins.turbo_executor.test_summarizer` | 0 | 14 | 316 |
| `plugins.universal_constructor` | 0 | 2 | 27 |
| `plugins.universal_constructor.models` | 0 | 0 | 136 |
| `plugins.universal_constructor.register_callbacks` | 0 | 4 | 47 |
| `plugins.universal_constructor.registry` | 0 | 0 | 302 |
| `plugins.universal_constructor.sandbox` | 0 | 0 | 600 |
| `policy_config` | 1 | 4 | 64 |
| `policy_engine` | 4 | 13 | 318 |
| `prompt_runner` | 3 | 22 | 154 |
| `provider_identity` | 1 | 0 | 83 |
| `pydantic_patches` | 1 | 12 | 539 |
| `reflection` | 2 | 0 | 138 |
| `reopenable_async_client` | 0 | 0 | 231 |
| `repl_session` | 3 | 18 | 398 |
| `request_cache` | 0 | 0 | 515 |
| `resilience` | 0 | 4 | 652 |
| `round_robin_model` | 1 | 5 | 165 |
| `run_context` | 8 | 0 | 264 |
| `runtime_state` | 2 | 6 | 311 |
| `scheduler` | 9 | 14 | 58 |
| `scheduler.__main__` | 0 | 2 | 14 |
| `scheduler.cli` | 0 | 13 | 123 |
| `scheduler.config` | 6 | 2 | 130 |
| `scheduler.daemon` | 0 | 7 | 335 |
| `scheduler.executor` | 0 | 5 | 155 |
| `scheduler.platform` | 0 | 6 | 18 |
| `scheduler.platform_unix` | 1 | 0 | 28 |
| `scheduler.platform_win` | 0 | 0 | 38 |
| `security` | 2 | 10 | 344 |
| `sensitive_paths` | 2 | 0 | 205 |
| `session_storage` | 7 | 14 | 876 |
| `session_storage_bridge` | 1 | 2 | 156 |
| `staged_changes` | 1 | 0 | 526 |
| `status_display` | 0 | 4 | 309 |
| `summarization_agent` | 1 | 7 | 177 |
| `terminal_utils` | 4 | 0 | 421 |
| `test_model_factory` | 0 | 2 | 84 |
| `text_ops` | 0 | 2 | 198 |
| `token_counting` | 2 | 0 | 121 |
| `token_ledger` | 2 | 0 | 259 |
| `token_utils` | 2 | 0 | 90 |
| `tool_schema` | 0 | 0 | 369 |
| `tools` | 45 | 107 | 502 |
| `tools.agent_tools` | 0 | 55 | 1,059 |
| `tools.ask_user_question` | 0 | 0 | 26 |
| `tools.ask_user_question.constants` | 0 | 0 | 73 |
| `tools.ask_user_question.demo_tui` | 0 | 0 | 55 |
| `tools.ask_user_question.handler` | 0 | 4 | 232 |
| `tools.ask_user_question.helpers` | 0 | 4 | 70 |
| `tools.ask_user_question.models` | 0 | 0 | 284 |
| `tools.ask_user_question.registration` | 0 | 0 | 37 |
| `tools.ask_user_question.renderers` | 0 | 0 | 313 |
| `tools.ask_user_question.terminal_ui` | 0 | 2 | 326 |
| `tools.ask_user_question.theme` | 0 | 2 | 152 |
| `tools.ask_user_question.tui_loop` | 0 | 0 | 427 |
| `tools.browser` | 0 | 2 | 37 |
| `tools.browser.browser_control` | 0 | 7 | 272 |
| `tools.browser.browser_interactions` | 0 | 6 | 492 |
| `tools.browser.browser_locators` | 0 | 5 | 593 |
| `tools.browser.browser_manager` | 0 | 10 | 377 |
| `tools.browser.browser_navigation` | 0 | 6 | 236 |
| `tools.browser.browser_screenshot` | 0 | 6 | 175 |
| `tools.browser.browser_scripts` | 0 | 6 | 425 |
| `tools.browser.browser_workflows` | 0 | 9 | 191 |
| `tools.browser.chromium_terminal_manager` | 0 | 5 | 257 |
| `tools.browser.terminal_command_tools` | 0 | 8 | 530 |
| `tools.browser.terminal_screenshot_tools` | 0 | 8 | 659 |
| `tools.browser.terminal_tools` | 0 | 10 | 506 |
| `tools.command_runner` | 27 | 24 | 1,812 |
| `tools.common` | 0 | 25 | 1,315 |
| `tools.display` | 0 | 8 | 71 |
| `tools.file_modifications` | 0 | 33 | 1,003 |
| `tools.file_operations` | 0 | 22 | 237 |
| `tools.process_runner_protocol` | 0 | 0 | 370 |
| `tools.scheduler_tools` | 0 | 19 | 412 |
| `tools.skills_tools` | 2 | 15 | 241 |
| `tools.subagent_context` | 0 | 0 | 158 |
| `tools.tools_content` | 0 | 0 | 50 |
| `tools.universal_constructor` | 0 | 20 | 855 |
| `tui` | 21 | 8 | 12 |
| `tui.app` | 0 | 62 | 867 |
| `tui.base_screen` | 18 | 0 | 25 |
| `tui.completion` | 2 | 11 | 363 |
| `tui.launcher` | 0 | 4 | 41 |
| `tui.message_bridge` | 0 | 7 | 374 |
| `tui.screens` | 0 | 0 | 5 |
| `tui.screens.add_model_screen` | 0 | 11 | 387 |
| `tui.screens.agent_screen` | 0 | 25 | 396 |
| `tui.screens.autosave_screen` | 0 | 21 | 283 |
| `tui.screens.colors_screen` | 0 | 12 | 381 |
| `tui.screens.diff_screen` | 0 | 16 | 429 |
| `tui.screens.hooks_screen` | 0 | 9 | 218 |
| `tui.screens.mcp_form_screen` | 0 | 8 | 379 |
| `tui.screens.mcp_screen` | 0 | 12 | 305 |
| `tui.screens.model_pin_screen` | 0 | 5 | 102 |
| `tui.screens.model_screen` | 0 | 11 | 162 |
| `tui.screens.model_settings_screen` | 0 | 16 | 360 |
| `tui.screens.onboarding_screen` | 0 | 7 | 167 |
| `tui.screens.question_screen` | 0 | 8 | 385 |
| `tui.screens.scheduler_screen` | 0 | 16 | 304 |
| `tui.screens.scheduler_wizard_screen` | 0 | 2 | 197 |
| `tui.screens.skills_install_screen` | 0 | 11 | 265 |
| `tui.screens.skills_screen` | 0 | 19 | 297 |
| `tui.screens.uc_screen` | 0 | 14 | 370 |
| `tui.stream_renderer` | 0 | 6 | 336 |
| `tui.theme` | 1 | 2 | 151 |
| `tui.widgets` | 0 | 8 | 8 |
| `tui.widgets.completion_overlay` | 0 | 2 | 108 |
| `tui.widgets.info_bar` | 0 | 4 | 130 |
| `tui.widgets.searchable_list` | 0 | 0 | 256 |
| `tui.widgets.split_panel` | 0 | 0 | 47 |
| `utils` | 21 | 0 | 171 |
| `utils.adaptive_render` | 1 | 0 | 352 |
| `utils.agent_helpers` | 0 | 0 | 227 |
| `utils.binary_token_estimation` | 0 | 0 | 47 |
| `utils.checkpoint` | 0 | 0 | 180 |
| `utils.clipboard` | 0 | 0 | 173 |
| `utils.config_resolve` | 0 | 0 | 324 |
| `utils.dag` | 0 | 0 | 117 |
| `utils.debouncer` | 1 | 0 | 67 |
| `utils.editor_detect` | 0 | 0 | 137 |
| `utils.emit` | 0 | 5 | 60 |
| `utils.eol` | 0 | 0 | 144 |
| `utils.file_display` | 0 | 0 | 389 |
| `utils.file_mutex` | 0 | 0 | 352 |
| `utils.fs_errors` | 0 | 0 | 208 |
| `utils.gitignore` | 0 | 0 | 121 |
| `utils.hashline` | 0 | 2 | 343 |
| `utils.install_hints` | 0 | 0 | 100 |
| `utils.llm_parsing` | 0 | 0 | 242 |
| `utils.macos_path` | 1 | 0 | 120 |
| `utils.min_duration` | 0 | 0 | 100 |
| `utils.overflow_detect` | 1 | 0 | 152 |
| `utils.parallel` | 0 | 0 | 370 |
| `utils.path_safety` | 0 | 0 | 216 |
| `utils.peek_file` | 0 | 0 | 216 |
| `utils.ring_buffer` | 0 | 0 | 263 |
| `utils.shell_split` | 0 | 0 | 88 |
| `utils.stream_parser` | 0 | 0 | 186 |
| `utils.subtask_parser` | 1 | 0 | 146 |
| `utils.symbol_hierarchy` | 0 | 0 | 110 |
| `utils.syntax_validate` | 0 | 0 | 98 |
| `utils.thread_safe_cache` | 0 | 0 | 43 |
| `utils.whitespace` | 0 | 0 | 53 |
| `uvx_detection` | 2 | 0 | 244 |
| `version_checker` | 1 | 9 | 200 |
| `workflow_state` | 5 | 4 | 388 |
