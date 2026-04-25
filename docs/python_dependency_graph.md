# Python Module Dependency Graph

> Generated for Python-to-Elixir migration planning. See [ADR-004](adr/ADR-004-python-to-elixir-migration-strategy.md).

**Generated**: 2026-01-01T00:00:00+00:00
**Total modules analyzed**: 521

## Summary Statistics

| Metric | Value |
|--------|-------|
| Total modules | 521 |
| Total lines of code | 145,692 |
| Leaf modules (no internal deps) | 145 |
| Hub modules (≥10 importers) | 22 |
| Import cycles detected | 79 |

## High-Fan-In Hub Modules (Port LAST)

> These modules are imported by many others. Porting them early breaks dependents.

| Module | Fan-In | Fan-Out | LOC | Description |
|--------|--------|---------|-----|-------------|
| `messaging` | 131 | 95 | 268 | |
| `config` | 109 | 29 | 2,694 | |
| `callbacks` | 72 | 13 | 1,228 | |
| `code_puppy` | 38 | 0 | 93 | |
| `config_paths` | 31 | 2 | 427 | |
| `tools.command_runner` | 27 | 24 | 1,812 | |
| `agents` | 26 | 12 | 31 | |
| `agents.base_agent` | 26 | 75 | 2,901 | |
| `tools.common` | 25 | 25 | 1,315 | |
| `agents.agent_manager` | 18 | 29 | 1,038 | |
| `tui.base_screen` | 18 | 0 | 25 | |
| `command_line.mcp.base` | 15 | 2 | 32 | |
| `command_line.command_registry` | 14 | 0 | 150 | |
| `model_factory` | 14 | 35 | 1,143 | |
| `tui.widgets.searchable_list` | 14 | 0 | 256 | |
| `tui.widgets.split_panel` | 14 | 0 | 47 | |
| `mcp_.managed_server` | 13 | 12 | 442 | |
| `command_line.mcp.utils` | 12 | 4 | 127 | |
| `config_package` | 12 | 18 | 63 | |
| `plugins` | 12 | 6 | 600 | |

## Low-Dependency Leaf Candidates (Port FIRST)

> These modules have few or no internal dependencies. Safe to port early.

| Module | Fan-In | LOC | Notes |
|--------|--------|-----|-------|
| `mcp_.error_isolation` | 0 | 436 | Pure leaf |
| `tools.process_runner_protocol` | 0 | 370 | Pure leaf |
| `utils.parallel` | 0 | 370 | Pure leaf |
| `tool_schema` | 0 | 369 | Pure leaf |
| `utils.ring_buffer` | 0 | 263 | Pure leaf |
| `utils.agent_helpers` | 0 | 227 | Pure leaf |
| `utils.peek_file` | 0 | 216 | Pure leaf |
| `utils.fs_errors` | 0 | 208 | Pure leaf |
| `mcp_.system_tools` | 0 | 207 | Pure leaf |
| `utils.stream_parser` | 0 | 186 | Pure leaf |
| `utils.checkpoint` | 0 | 180 | Pure leaf |
| `utils.clipboard` | 0 | 173 | Pure leaf |
| `utils.editor_detect` | 0 | 137 | Pure leaf |
| `utils.gitignore` | 0 | 121 | Pure leaf |
| `utils.dag` | 0 | 117 | Pure leaf |
| `utils.symbol_hierarchy` | 0 | 110 | Pure leaf |
| `utils.install_hints` | 0 | 100 | Pure leaf |
| `messaging.markdown_patches` | 0 | 53 | Pure leaf |
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

## Import Cycles Detected

> Cycles must be broken before porting (refactor to remove circular deps).

1. `adaptive_rate_limiter → plugins.elixir_bridge → plugins → config → model_factory → http_utils → adaptive_rate_limiter`
2. `agents.agent_manager → agents.base_agent → agents.agent_prompt_mixin → callbacks → plugins → config → agents.agent_manager`
3. `agents.agent_manager → agents.base_agent → agents.agent_prompt_mixin → callbacks → plugins → config → session_storage → agents.agent_manager`
4. `agents.agent_manager → agents.base_agent → agents.agent_prompt_mixin → callbacks → plugins → config → session_storage → command_line.prompt_toolkit_completion → agents.agent_manager`
5. `agents.agent_manager → agents.base_agent → agents.agent_prompt_mixin → callbacks → plugins → config → session_storage → command_line.prompt_toolkit_completion → command_line.pin_command_completion → agents.agent_manager`
6. `agents.agent_manager → agents.base_agent → agents.agent_prompt_mixin → callbacks → plugins → config → session_storage → command_line.prompt_toolkit_completion → command_line.pin_command_completion → agents.json_agent → tools → tools.agent_tools → agents.agent_manager`
7. `agents.agent_prompt_mixin → callbacks → plugins → config → session_storage → command_line.prompt_toolkit_completion → command_line.pin_command_completion → agents.json_agent → agents.base_agent → agents.agent_prompt_mixin`
8. `agents.agent_turbo_executor → plugins.turbo_executor.register_callbacks → agents.agent_turbo_executor`
9. `agents.event_stream_handler → callbacks → plugins → config → session_storage → command_line.prompt_toolkit_completion → command_line.pin_command_completion → agents.json_agent → tools → tools.agent_tools → agents.event_stream_handler`
10. `agents.event_stream_handler → config → session_storage → command_line.prompt_toolkit_completion → command_line.pin_command_completion → agents.json_agent → tools → tools.agent_tools → agents.event_stream_handler`

... and 69 more cycles

## Recommended Porting Order

> Ordered by dependency depth (leaves first). Within each depth, sorted by fan-in (lowest first).

| Phase | Modules | Criteria |
|-------|---------|----------|
| Foundation (depth=0) | `mcp_.error_isolation`, `mcp_.system_tools`, `mcp_prompts`, `messaging.markdown_patches`, `plugins.agent_shortcuts` (+140 more) | Leaves → Hubs |
| Utilities (depth=1) | `__main__`, `agent_pinning_transport`, `agents.agent_code_puppy`, `agents.agent_code_reviewer`, `agents.agent_code_scout` (+371 more) | Leaves → Hubs |

## Limitations of This Analysis

1. **Static analysis only**: Dynamic imports (importlib, __import__) are not detected.
2. **Conditional imports**: Imports inside try/except or if TYPE_CHECKING are treated equally.
3. **Star imports**: from x import * dependencies may be incomplete.
4. **External dependencies**: Third-party package internals are not analyzed.
5. **Runtime dependencies**: Plugin loading, config-driven imports are not captured.

For complete accuracy, supplement with runtime profiling and manual review.

## Appendix: All Modules

| Module | Fan-In | Fan-Out | LOC |
|--------|--------|---------|-----|
| `code_puppy` | 38 | 0 | 93 |
| `__main__` | 0 | 2 | 10 |
| `_backlog` | 1 | 0 | 109 |
| `adaptive_rate_limiter` | 3 | 5 | 1,164 |
| `agent_model_pinning` | 3 | 8 | 190 |
| `agent_pinning_transport` | 0 | 2 | 167 |
| `agents` | 26 | 12 | 31 |
| `agents.agent_code_puppy` | 0 | 5 | 115 |
| `agents.agent_code_reviewer` | 0 | 2 | 97 |
| `agents.agent_code_scout` | 0 | 2 | 152 |
| `agents.agent_creator_agent` | 0 | 11 | 609 |
| `agents.agent_golang_reviewer` | 0 | 2 | 157 |
| `agents.agent_helios` | 0 | 2 | 130 |
| `agents.agent_javascript_reviewer` | 0 | 2 | 167 |
| `agents.agent_manager` | 18 | 29 | 1,038 |
| `agents.agent_pack_leader` | 0 | 4 | 343 |
| `agents.agent_planning` | 0 | 4 | 171 |
| `agents.agent_prompt_mixin` | 1 | 2 | 127 |
| `agents.agent_python_programmer` | 0 | 2 | 188 |
| `agents.agent_python_reviewer` | 0 | 2 | 97 |
| `agents.agent_qa_expert` | 0 | 2 | 170 |
| `agents.agent_qa_kitten` | 0 | 2 | 215 |
| `agents.agent_scheduler` | 0 | 2 | 128 |
| `agents.agent_security_auditor` | 0 | 2 | 188 |
| `agents.agent_state` | 1 | 2 | 152 |
| `agents.agent_terminal_qa` | 0 | 2 | 330 |
| `agents.agent_turbo_executor` | 1 | 11 | 175 |
| `agents.agent_typescript_reviewer` | 0 | 2 | 173 |
| `agents.base_agent` | 26 | 75 | 2,901 |
| `agents.event_stream_handler` | 5 | 14 | 471 |
| `agents.json_agent` | 4 | 9 | 212 |
| `agents.pack` | 0 | 8 | 29 |
| `agents.pack.retriever` | 0 | 4 | 385 |
| `agents.pack.shepherd` | 0 | 4 | 346 |
| `agents.pack.terrier` | 0 | 4 | 287 |
| `agents.pack.watchdog` | 0 | 4 | 368 |
| `agents.prompt_reviewer` | 0 | 4 | 146 |
| `agents.stream_event_normalizer` | 2 | 0 | 155 |
| `agents.subagent_stream_handler` | 1 | 10 | 297 |
| `api` | 0 | 2 | 13 |
| `api.app` | 2 | 13 | 174 |
| `api.main` | 0 | 2 | 21 |
| `api.pty_manager` | 2 | 0 | 478 |
| `api.routers` | 2 | 5 | 12 |
| `api.routers.agents` | 2 | 3 | 36 |
| `api.routers.commands` | 2 | 10 | 382 |
| `api.routers.config` | 2 | 7 | 122 |
| `api.routers.sessions` | 2 | 12 | 406 |
| `api.schemas` | 1 | 0 | 29 |
| `api.security` | 5 | 0 | 282 |
| `api.websocket` | 1 | 9 | 341 |
| `app_runner` | 1 | 56 | 485 |
| `async_utils` | 8 | 2 | 284 |
| `callbacks` | 72 | 13 | 1,228 |
| `capability` | 0 | 16 | 76 |
| `capability.builtin_providers` | 0 | 8 | 187 |
| `capability.registry` | 1 | 6 | 372 |
| `capability.types` | 2 | 0 | 85 |
| `chatgpt_codex_client` | 1 | 2 | 406 |
| `circuit_state` | 3 | 0 | 24 |
| `claude_cache_client` | 3 | 6 | 1,068 |
| `cli_runner` | 1 | 12 | 179 |
| `code_context` | 2 | 8 | 225 |
| `code_context.explorer` | 1 | 9 | 449 |
| `code_context.models` | 2 | 0 | 185 |
| `command_line` | 1 | 0 | 1 |
| `command_line.add_model_menu` | 2 | 20 | 1,155 |
| `command_line.agent_menu` | 1 | 25 | 611 |
| `command_line.attachments` | 3 | 0 | 391 |
| `command_line.autosave_menu` | 4 | 15 | 707 |
| `command_line.clipboard` | 4 | 0 | 544 |
| `command_line.colors_menu` | 2 | 7 | 534 |
| `command_line.command_handler` | 6 | 23 | 314 |
| `command_line.command_registry` | 14 | 0 | 150 |
| `command_line.concurrency_commands` | 1 | 12 | 97 |
| `command_line.config_commands` | 1 | 57 | 673 |
| `command_line.core_commands` | 1 | 59 | 787 |
| `command_line.diff_menu` | 2 | 11 | 864 |
| `command_line.file_path_completion` | 1 | 0 | 71 |
| `command_line.load_context_completion` | 1 | 2 | 52 |
| `command_line.mcp` | 1 | 2 | 10 |
| `command_line.mcp.base` | 15 | 2 | 32 |
| `command_line.mcp.catalog_server_installer` | 2 | 12 | 174 |
| `command_line.mcp.custom_server_form` | 2 | 9 | 675 |
| `command_line.mcp.custom_server_installer` | 0 | 13 | 195 |
| `command_line.mcp.edit_command` | 1 | 12 | 130 |
| `command_line.mcp.handler` | 0 | 32 | 138 |
| `command_line.mcp.help_command` | 1 | 5 | 146 |
| `command_line.mcp.install_command` | 1 | 16 | 212 |
| `command_line.mcp.install_menu` | 1 | 15 | 703 |
| `command_line.mcp.list_command` | 2 | 10 | 93 |
| `command_line.mcp.logs_command` | 1 | 14 | 230 |
| `command_line.mcp.remove_command` | 1 | 10 | 81 |
| `command_line.mcp.restart_command` | 1 | 9 | 99 |
| `command_line.mcp.search_command` | 1 | 8 | 115 |
| `command_line.mcp.start_all_command` | 1 | 8 | 134 |
| `command_line.mcp.start_command` | 1 | 11 | 110 |
| `command_line.mcp.status_command` | 1 | 16 | 184 |
| `command_line.mcp.stop_all_command` | 1 | 8 | 111 |
| `command_line.mcp.stop_command` | 1 | 10 | 78 |
| `command_line.mcp.test_command` | 1 | 8 | 106 |
| `command_line.mcp.utils` | 12 | 4 | 127 |
| `command_line.mcp.wizard_utils` | 2 | 12 | 329 |
| `command_line.mcp_completion` | 1 | 2 | 173 |
| `command_line.model_picker_completion` | 10 | 15 | 423 |
| `command_line.model_settings_menu` | 2 | 22 | 952 |
| `command_line.motd` | 2 | 6 | 93 |
| `command_line.onboarding_slides` | 1 | 0 | 178 |
| `command_line.onboarding_wizard` | 3 | 13 | 346 |
| `command_line.pack_commands` | 1 | 10 | 107 |
| `command_line.pagination` | 9 | 0 | 42 |
| `command_line.pin_command_completion` | 1 | 9 | 329 |
| `command_line.preset_commands` | 1 | 13 | 88 |
| `command_line.prompt_toolkit_completion` | 2 | 39 | 843 |
| `command_line.repl_commands` | 1 | 13 | 181 |
| `command_line.session_commands` | 1 | 25 | 308 |
| `command_line.shell_passthrough` | 3 | 2 | 232 |
| `command_line.skills_completion` | 1 | 2 | 158 |
| `command_line.staged_commands` | 1 | 13 | 342 |
| `command_line.uc_menu` | 1 | 19 | 901 |
| `command_line.utils` | 9 | 0 | 92 |
| `command_line.wiggum_state` | 3 | 0 | 77 |
| `command_line.workflow_commands` | 1 | 10 | 113 |
| `compaction` | 1 | 18 | 48 |
| `compaction.file_ops_tracker` | 1 | 0 | 198 |
| `compaction.history_offload` | 1 | 9 | 281 |
| `compaction.shadow_mode` | 2 | 4 | 154 |
| `compaction.thresholds` | 1 | 9 | 136 |
| `compaction.tool_arg_truncation` | 1 | 0 | 305 |
| `concurrency_limits` | 4 | 6 | 462 |
| `config` | 109 | 29 | 2,694 |
| `config_package` | 12 | 18 | 63 |
| `config_package._resolvers` | 1 | 3 | 229 |
| `config_package.env_helpers` | 4 | 0 | 153 |
| `config_package.loader` | 1 | 16 | 450 |
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
| `hook_engine` | 1 | 10 | 21 |
| `hook_engine.aliases` | 1 | 0 | 154 |
| `hook_engine.engine` | 0 | 18 | 213 |
| `hook_engine.executor` | 1 | 6 | 299 |
| `hook_engine.matcher` | 2 | 2 | 201 |
| `hook_engine.models` | 3 | 0 | 227 |
| `hook_engine.registry` | 1 | 3 | 106 |
| `hook_engine.validator` | 1 | 0 | 144 |
| `http_utils` | 4 | 17 | 417 |
| `interactive_loop` | 1 | 79 | 679 |
| `keymap` | 4 | 4 | 128 |
| `main` | 1 | 2 | 10 |
| `mcp_` | 3 | 58 | 101 |
| `mcp_.async_lifecycle` | 2 | 0 | 286 |
| `mcp_.blocking_startup` | 1 | 6 | 474 |
| `mcp_.captured_stdio_server` | 0 | 2 | 274 |
| `mcp_.circuit_breaker` | 0 | 4 | 285 |
| `mcp_.config_wizard` | 0 | 19 | 555 |
| `mcp_.dashboard` | 0 | 4 | 307 |
| `mcp_.error_isolation` | 0 | 0 | 436 |
| `mcp_.examples.retry_example` | 0 | 3 | 226 |
| `mcp_.health_monitor` | 0 | 2 | 606 |
| `mcp_.managed_server` | 13 | 12 | 442 |
| `mcp_.manager` | 7 | 14 | 978 |
| `mcp_.mcp_logs` | 2 | 2 | 223 |
| `mcp_.mcp_security` | 4 | 0 | 513 |
| `mcp_.registry` | 1 | 4 | 450 |
| `mcp_.retry_manager` | 1 | 0 | 350 |
| `mcp_.server_registry_catalog` | 6 | 5 | 1,142 |
| `mcp_.status_tracker` | 2 | 2 | 355 |
| `mcp_.system_tools` | 0 | 0 | 207 |
| `mcp_prompts` | 0 | 0 | 1 |
| `mcp_prompts.hook_creator` | 1 | 0 | 103 |
| `message_transport` | 1 | 2 | 315 |
| `messaging` | 131 | 95 | 268 |
| `messaging.bus` | 1 | 19 | 891 |
| `messaging.commands` | 2 | 0 | 164 |
| `messaging.history_buffer` | 2 | 6 | 313 |
| `messaging.markdown_patches` | 0 | 0 | 53 |
| `messaging.message_queue` | 3 | 4 | 448 |
| `messaging.messages` | 9 | 0 | 584 |
| `messaging.queue_console` | 1 | 6 | 269 |
| `messaging.renderers` | 0 | 5 | 291 |
| `messaging.rich_renderer` | 0 | 56 | 1,564 |
| `messaging.spinner` | 7 | 6 | 184 |
| `messaging.spinner.console_spinner` | 0 | 10 | 252 |
| `messaging.spinner.spinner_base` | 1 | 2 | 95 |
| `messaging.subagent_console` | 1 | 2 | 452 |
| `model_availability` | 1 | 0 | 153 |
| `model_config` | 1 | 2 | 171 |
| `model_factory` | 14 | 35 | 1,143 |
| `model_packs` | 5 | 7 | 237 |
| `model_switching` | 4 | 7 | 57 |
| `model_utils` | 5 | 2 | 124 |
| `models_dev_parser` | 2 | 4 | 685 |
| `permission_decision` | 8 | 0 | 67 |
| `persistence` | 4 | 6 | 368 |
| `plugins` | 12 | 6 | 600 |
| `plugins.agent_memory` | 0 | 35 | 100 |
| `plugins.agent_memory.agent_run_end` | 1 | 10 | 84 |
| `plugins.agent_memory.commands` | 1 | 12 | 303 |
| `plugins.agent_memory.config` | 3 | 2 | 205 |
| `plugins.agent_memory.core` | 6 | 15 | 152 |
| `plugins.agent_memory.extraction` | 1 | 0 | 276 |
| `plugins.agent_memory.messaging` | 3 | 8 | 128 |
| `plugins.agent_memory.processing` | 2 | 14 | 383 |
| `plugins.agent_memory.prompts` | 1 | 11 | 150 |
| `plugins.agent_memory.register_callbacks` | 0 | 10 | 54 |
| `plugins.agent_memory.signal_safeguards` | 1 | 4 | 361 |
| `plugins.agent_memory.signals` | 3 | 0 | 279 |
| `plugins.agent_memory.storage` | 4 | 5 | 387 |
| `plugins.agent_memory.updater` | 1 | 5 | 233 |
| `plugins.agent_shortcuts` | 0 | 0 | 1 |
| `plugins.agent_shortcuts.register_callbacks` | 0 | 12 | 122 |
| `plugins.agent_skills` | 0 | 6 | 22 |
| `plugins.agent_skills.config` | 5 | 5 | 204 |
| `plugins.agent_skills.discovery` | 5 | 4 | 141 |
| `plugins.agent_skills.downloader` | 1 | 9 | 419 |
| `plugins.agent_skills.installer` | 2 | 0 | 19 |
| `plugins.agent_skills.metadata` | 5 | 0 | 260 |
| `plugins.agent_skills.prompt_builder` | 1 | 2 | 134 |
| `plugins.agent_skills.register_callbacks` | 0 | 31 | 374 |
| `plugins.agent_skills.remote_catalog` | 1 | 3 | 335 |
| `plugins.agent_skills.skill_catalog` | 3 | 2 | 253 |
| `plugins.agent_skills.skills_install_menu` | 2 | 22 | 684 |
| `plugins.agent_skills.skills_menu` | 1 | 31 | 798 |
| `plugins.agent_trace` | 0 | 48 | 116 |
| `plugins.agent_trace.analytics` | 3 | 8 | 530 |
| `plugins.agent_trace.cli_analytics` | 2 | 8 | 408 |
| `plugins.agent_trace.cli_renderer` | 3 | 7 | 470 |
| `plugins.agent_trace.emitter` | 2 | 10 | 268 |
| `plugins.agent_trace.reducer` | 4 | 6 | 420 |
| `plugins.agent_trace.register_callbacks` | 0 | 37 | 706 |
| `plugins.agent_trace.schema` | 7 | 0 | 264 |
| `plugins.agent_trace.store` | 2 | 8 | 181 |
| `plugins.auto_test_control` | 0 | 0 | 1 |
| `plugins.auto_test_control.register_callbacks` | 0 | 12 | 340 |
| `plugins.chatgpt_oauth` | 0 | 4 | 6 |
| `plugins.chatgpt_oauth.config` | 3 | 2 | 55 |
| `plugins.chatgpt_oauth.oauth_flow` | 3 | 20 | 313 |
| `plugins.chatgpt_oauth.register_callbacks` | 0 | 22 | 198 |
| `plugins.chatgpt_oauth.utils` | 2 | 6 | 724 |
| `plugins.claude_code_hooks` | 0 | 0 | 1 |
| `plugins.claude_code_hooks.config` | 1 | 2 | 158 |
| `plugins.claude_code_hooks.register_callbacks` | 0 | 7 | 170 |
| `plugins.claude_code_oauth` | 0 | 6 | 25 |
| `plugins.claude_code_oauth.config` | 2 | 2 | 55 |
| `plugins.claude_code_oauth.register_callbacks` | 2 | 45 | 472 |
| `plugins.claude_code_oauth.token_refresh_heartbeat` | 1 | 4 | 235 |
| `plugins.claude_code_oauth.utils` | 4 | 6 | 914 |
| `plugins.clean_command` | 0 | 0 | 1 |
| `plugins.clean_command.register_callbacks` | 0 | 13 | 412 |
| `plugins.code_explorer` | 0 | 11 | 31 |
| `plugins.code_explorer.register_callbacks` | 0 | 12 | 544 |
| `plugins.code_skeleton` | 0 | 0 | 0 |
| `plugins.code_skeleton.register_callbacks` | 0 | 6 | 155 |
| `plugins.code_skeleton.skeleton` | 1 | 0 | 220 |
| `plugins.completion_notifier` | 0 | 0 | 3 |
| `plugins.completion_notifier.register_callbacks` | 0 | 7 | 204 |
| `plugins.cost_estimator` | 0 | 0 | 0 |
| `plugins.cost_estimator.estimator` | 1 | 2 | 237 |
| `plugins.cost_estimator.register_callbacks` | 0 | 9 | 184 |
| `plugins.customizable_commands` | 0 | 0 | 0 |
| `plugins.customizable_commands.register_callbacks` | 1 | 5 | 152 |
| `plugins.dual_home.register_callbacks` | 0 | 7 | 116 |
| `plugins.elixir_bridge` | 12 | 3 | 725 |
| `plugins.elixir_bridge.bridge_controller` | 1 | 32 | 1,605 |
| `plugins.elixir_bridge.register_callbacks` | 0 | 12 | 358 |
| `plugins.elixir_bridge.wire_protocol` | 2 | 0 | 1,575 |
| `plugins.error_classifier` | 0 | 8 | 41 |
| `plugins.error_classifier.builtins` | 0 | 5 | 298 |
| `plugins.error_classifier.exinfo` | 3 | 0 | 58 |
| `plugins.error_classifier.register_callbacks` | 0 | 11 | 148 |
| `plugins.error_classifier.registry` | 2 | 2 | 166 |
| `plugins.error_logger` | 0 | 0 | 1 |
| `plugins.error_logger.register_callbacks` | 0 | 11 | 165 |
| `plugins.example_custom_command.register_callbacks` | 0 | 4 | 51 |
| `plugins.fast_puppy.register_callbacks` | 0 | 2 | 23 |
| `plugins.file_mentions` | 0 | 0 | 0 |
| `plugins.file_mentions.register_callbacks` | 0 | 2 | 317 |
| `plugins.file_permission_handler` | 0 | 0 | 4 |
| `plugins.file_permission_handler.register_callbacks` | 2 | 17 | 521 |
| `plugins.frontend_emitter` | 0 | 0 | 24 |
| `plugins.frontend_emitter.emitter` | 2 | 6 | 177 |
| `plugins.frontend_emitter.register_callbacks` | 0 | 4 | 267 |
| `plugins.git_auto_commit` | 0 | 22 | 98 |
| `plugins.git_auto_commit.cli` | 0 | 9 | 181 |
| `plugins.git_auto_commit.commit_flow` | 3 | 4 | 347 |
| `plugins.git_auto_commit.context_guard` | 4 | 4 | 255 |
| `plugins.git_auto_commit.policy_errors` | 2 | 0 | 120 |
| `plugins.git_auto_commit.register_callbacks` | 0 | 14 | 249 |
| `plugins.git_auto_commit.shell_bridge` | 3 | 2 | 241 |
| `plugins.hook_creator` | 0 | 0 | 1 |
| `plugins.hook_creator.register_callbacks` | 0 | 6 | 33 |
| `plugins.hook_manager` | 0 | 0 | 1 |
| `plugins.hook_manager.config` | 3 | 3 | 292 |
| `plugins.hook_manager.hooks_menu` | 1 | 13 | 559 |
| `plugins.hook_manager.register_callbacks` | 0 | 15 | 227 |
| `plugins.loop_detection` | 0 | 0 | 6 |
| `plugins.loop_detection.register_callbacks` | 0 | 10 | 510 |
| `plugins.oauth_puppy_html` | 2 | 0 | 224 |
| `plugins.ollama_setup` | 0 | 0 | 5 |
| `plugins.ollama_setup.completer` | 1 | 2 | 36 |
| `plugins.ollama_setup.register_callbacks` | 1 | 9 | 362 |
| `plugins.pack_parallelism` | 0 | 0 | 0 |
| `plugins.pack_parallelism.register_callbacks` | 0 | 14 | 479 |
| `plugins.pack_parallelism.run_limiter` | 3 | 5 | 838 |
| `plugins.pop_command` | 0 | 0 | 1 |
| `plugins.pop_command.register_callbacks` | 0 | 9 | 166 |
| `plugins.proactive_guidance` | 0 | 0 | 2 |
| `plugins.proactive_guidance._guidance` | 1 | 0 | 271 |
| `plugins.proactive_guidance.register_callbacks` | 0 | 11 | 356 |
| `plugins.prompt_store` | 0 | 0 | 20 |
| `plugins.prompt_store.commands` | 1 | 10 | 559 |
| `plugins.prompt_store.register_callbacks` | 0 | 6 | 47 |
| `plugins.prompt_store.store` | 1 | 6 | 393 |
| `plugins.remember_last_agent` | 1 | 4 | 9 |
| `plugins.remember_last_agent.register_callbacks` | 0 | 11 | 94 |
| `plugins.remember_last_agent.storage` | 1 | 4 | 66 |
| `plugins.render_check` | 0 | 0 | 3 |
| `plugins.render_check.register_callbacks` | 0 | 4 | 229 |
| `plugins.repo_compass` | 0 | 0 | 8 |
| `plugins.repo_compass.config` | 1 | 2 | 50 |
| `plugins.repo_compass.decision_markers` | 1 | 0 | 287 |
| `plugins.repo_compass.formatter` | 1 | 2 | 38 |
| `plugins.repo_compass.indexer` | 1 | 0 | 112 |
| `plugins.repo_compass.marker_merge` | 0 | 2 | 150 |
| `plugins.repo_compass.register_callbacks` | 0 | 14 | 160 |
| `plugins.repo_compass.tech_stack` | 1 | 0 | 606 |
| `plugins.repo_compass.turbo_indexer_bridge` | 2 | 3 | 48 |
| `plugins.scheduler` | 0 | 0 | 1 |
| `plugins.scheduler.register_callbacks` | 0 | 13 | 85 |
| `plugins.scheduler.scheduler_menu` | 1 | 26 | 542 |
| `plugins.scheduler.scheduler_wizard` | 1 | 9 | 344 |
| `plugins.session_logger` | 0 | 0 | 9 |
| `plugins.session_logger.config` | 1 | 3 | 36 |
| `plugins.session_logger.register_callbacks` | 0 | 15 | 432 |
| `plugins.session_logger.writer` | 1 | 0 | 337 |
| `plugins.shell_safety` | 0 | 0 | 6 |
| `plugins.shell_safety.agent_shell_safety` | 1 | 2 | 69 |
| `plugins.shell_safety.command_cache` | 1 | 0 | 146 |
| `plugins.shell_safety.regex_classifier` | 1 | 2 | 900 |
| `plugins.shell_safety.register_callbacks` | 0 | 25 | 465 |
| `plugins.supervisor_review` | 0 | 0 | 1 |
| `plugins.supervisor_review.models` | 3 | 0 | 156 |
| `plugins.supervisor_review.orchestrator` | 1 | 13 | 538 |
| `plugins.supervisor_review.register_callbacks` | 0 | 6 | 141 |
| `plugins.supervisor_review.satisfaction` | 1 | 6 | 412 |
| `plugins.synthetic_status` | 0 | 0 | 1 |
| `plugins.synthetic_status.register_callbacks` | 0 | 11 | 123 |
| `plugins.synthetic_status.status_api` | 1 | 2 | 140 |
| `plugins.theme_switcher` | 0 | 0 | 3 |
| `plugins.theme_switcher.register_callbacks` | 0 | 4 | 143 |
| `plugins.tool_allowlist` | 0 | 0 | 1 |
| `plugins.tool_allowlist.register_callbacks` | 0 | 6 | 242 |
| `plugins.tracing_langfuse` | 0 | 0 | 6 |
| `plugins.tracing_langfuse.register_callbacks` | 0 | 8 | 467 |
| `plugins.tracing_langsmith` | 0 | 0 | 5 |
| `plugins.tracing_langsmith.register_callbacks` | 0 | 8 | 464 |
| `plugins.ttsr` | 0 | 0 | 9 |
| `plugins.ttsr.register_callbacks` | 0 | 12 | 294 |
| `plugins.ttsr.rule_loader` | 2 | 0 | 226 |
| `plugins.ttsr.stream_watcher` | 1 | 4 | 275 |
| `plugins.turbo_executor` | 2 | 13 | 33 |
| `plugins.turbo_executor.models` | 5 | 0 | 151 |
| `plugins.turbo_executor.notifications` | 2 | 6 | 261 |
| `plugins.turbo_executor.orchestrator` | 2 | 14 | 471 |
| `plugins.turbo_executor.register_callbacks` | 2 | 15 | 397 |
| `plugins.turbo_executor.summarizer` | 3 | 5 | 407 |
| `plugins.turbo_executor.test_summarizer` | 0 | 14 | 316 |
| `plugins.universal_constructor` | 6 | 2 | 27 |
| `plugins.universal_constructor.models` | 3 | 0 | 136 |
| `plugins.universal_constructor.register_callbacks` | 0 | 8 | 47 |
| `plugins.universal_constructor.registry` | 7 | 5 | 302 |
| `plugins.universal_constructor.sandbox` | 1 | 2 | 600 |
| `policy_config` | 1 | 4 | 64 |
| `policy_engine` | 4 | 13 | 318 |
| `prompt_runner` | 3 | 22 | 154 |
| `provider_identity` | 2 | 0 | 83 |
| `pydantic_patches` | 1 | 12 | 539 |
| `reflection` | 2 | 0 | 138 |
| `reopenable_async_client` | 1 | 0 | 231 |
| `repl_session` | 3 | 18 | 398 |
| `request_cache` | 3 | 0 | 515 |
| `resilience` | 0 | 4 | 652 |
| `round_robin_model` | 1 | 5 | 165 |
| `run_context` | 8 | 0 | 264 |
| `runtime_state` | 2 | 6 | 311 |
| `scheduler` | 1 | 14 | 58 |
| `scheduler.__main__` | 0 | 2 | 14 |
| `scheduler.cli` | 1 | 13 | 123 |
| `scheduler.config` | 6 | 2 | 130 |
| `scheduler.daemon` | 6 | 7 | 335 |
| `scheduler.executor` | 4 | 5 | 155 |
| `scheduler.platform` | 0 | 6 | 18 |
| `scheduler.platform_unix` | 1 | 0 | 28 |
| `scheduler.platform_win` | 1 | 0 | 38 |
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
| `tools` | 7 | 107 | 502 |
| `tools.agent_tools` | 5 | 55 | 1,059 |
| `tools.ask_user_question` | 2 | 10 | 26 |
| `tools.ask_user_question.constants` | 6 | 0 | 73 |
| `tools.ask_user_question.demo_tui` | 0 | 2 | 55 |
| `tools.ask_user_question.handler` | 2 | 16 | 232 |
| `tools.ask_user_question.helpers` | 0 | 4 | 70 |
| `tools.ask_user_question.models` | 5 | 9 | 284 |
| `tools.ask_user_question.registration` | 0 | 4 | 37 |
| `tools.ask_user_question.renderers` | 1 | 21 | 313 |
| `tools.ask_user_question.terminal_ui` | 4 | 15 | 326 |
| `tools.ask_user_question.theme` | 2 | 2 | 152 |
| `tools.ask_user_question.tui_loop` | 1 | 16 | 427 |
| `tools.browser` | 3 | 7 | 37 |
| `tools.browser.browser_control` | 1 | 9 | 272 |
| `tools.browser.browser_interactions` | 1 | 8 | 492 |
| `tools.browser.browser_locators` | 1 | 7 | 593 |
| `tools.browser.browser_manager` | 7 | 10 | 377 |
| `tools.browser.browser_navigation` | 1 | 8 | 236 |
| `tools.browser.browser_screenshot` | 1 | 8 | 175 |
| `tools.browser.browser_scripts` | 1 | 8 | 425 |
| `tools.browser.browser_workflows` | 1 | 9 | 191 |
| `tools.browser.chromium_terminal_manager` | 1 | 5 | 257 |
| `tools.browser.terminal_command_tools` | 1 | 13 | 530 |
| `tools.browser.terminal_screenshot_tools` | 3 | 11 | 659 |
| `tools.browser.terminal_tools` | 5 | 13 | 506 |
| `tools.command_runner` | 27 | 24 | 1,812 |
| `tools.common` | 25 | 25 | 1,315 |
| `tools.display` | 1 | 8 | 71 |
| `tools.file_modifications` | 1 | 33 | 1,003 |
| `tools.file_operations` | 6 | 22 | 237 |
| `tools.process_runner_protocol` | 0 | 0 | 370 |
| `tools.scheduler_tools` | 1 | 19 | 412 |
| `tools.skills_tools` | 2 | 15 | 241 |
| `tools.subagent_context` | 8 | 0 | 158 |
| `tools.tools_content` | 1 | 0 | 50 |
| `tools.universal_constructor` | 1 | 20 | 855 |
| `tui` | 0 | 8 | 12 |
| `tui.app` | 3 | 62 | 867 |
| `tui.base_screen` | 18 | 0 | 25 |
| `tui.completion` | 2 | 11 | 363 |
| `tui.launcher` | 1 | 4 | 41 |
| `tui.message_bridge` | 1 | 7 | 374 |
| `tui.screens` | 0 | 0 | 5 |
| `tui.screens.add_model_screen` | 1 | 11 | 387 |
| `tui.screens.agent_screen` | 1 | 25 | 396 |
| `tui.screens.autosave_screen` | 1 | 21 | 283 |
| `tui.screens.colors_screen` | 1 | 12 | 381 |
| `tui.screens.diff_screen` | 1 | 16 | 429 |
| `tui.screens.hooks_screen` | 1 | 9 | 218 |
| `tui.screens.mcp_form_screen` | 1 | 8 | 379 |
| `tui.screens.mcp_screen` | 1 | 12 | 305 |
| `tui.screens.model_pin_screen` | 1 | 5 | 102 |
| `tui.screens.model_screen` | 1 | 11 | 162 |
| `tui.screens.model_settings_screen` | 1 | 16 | 360 |
| `tui.screens.onboarding_screen` | 1 | 7 | 167 |
| `tui.screens.question_screen` | 0 | 8 | 385 |
| `tui.screens.scheduler_screen` | 1 | 16 | 304 |
| `tui.screens.scheduler_wizard_screen` | 1 | 2 | 197 |
| `tui.screens.skills_install_screen` | 1 | 11 | 265 |
| `tui.screens.skills_screen` | 1 | 19 | 297 |
| `tui.screens.uc_screen` | 1 | 14 | 370 |
| `tui.stream_renderer` | 0 | 6 | 336 |
| `tui.theme` | 1 | 2 | 151 |
| `tui.widgets` | 0 | 8 | 8 |
| `tui.widgets.completion_overlay` | 3 | 2 | 108 |
| `tui.widgets.info_bar` | 2 | 4 | 130 |
| `tui.widgets.searchable_list` | 14 | 0 | 256 |
| `tui.widgets.split_panel` | 14 | 0 | 47 |
| `utils` | 4 | 90 | 171 |
| `utils.adaptive_render` | 1 | 0 | 352 |
| `utils.agent_helpers` | 0 | 0 | 227 |
| `utils.binary_token_estimation` | 1 | 0 | 47 |
| `utils.checkpoint` | 0 | 0 | 180 |
| `utils.clipboard` | 0 | 0 | 173 |
| `utils.config_resolve` | 1 | 0 | 324 |
| `utils.dag` | 0 | 0 | 117 |
| `utils.debouncer` | 1 | 0 | 67 |
| `utils.editor_detect` | 0 | 0 | 137 |
| `utils.emit` | 0 | 5 | 60 |
| `utils.eol` | 2 | 0 | 144 |
| `utils.file_display` | 4 | 0 | 389 |
| `utils.file_mutex` | 1 | 0 | 352 |
| `utils.fs_errors` | 0 | 0 | 208 |
| `utils.gitignore` | 0 | 0 | 121 |
| `utils.hashline` | 0 | 2 | 343 |
| `utils.install_hints` | 0 | 0 | 100 |
| `utils.llm_parsing` | 1 | 0 | 242 |
| `utils.macos_path` | 1 | 0 | 120 |
| `utils.min_duration` | 1 | 0 | 100 |
| `utils.overflow_detect` | 1 | 0 | 152 |
| `utils.parallel` | 0 | 0 | 370 |
| `utils.path_safety` | 3 | 0 | 216 |
| `utils.peek_file` | 0 | 0 | 216 |
| `utils.ring_buffer` | 0 | 0 | 263 |
| `utils.shell_split` | 2 | 0 | 88 |
| `utils.stream_parser` | 0 | 0 | 186 |
| `utils.subtask_parser` | 1 | 0 | 146 |
| `utils.symbol_hierarchy` | 0 | 0 | 110 |
| `utils.syntax_validate` | 1 | 0 | 98 |
| `utils.thread_safe_cache` | 6 | 0 | 43 |
| `utils.whitespace` | 1 | 0 | 53 |
| `uvx_detection` | 2 | 0 | 244 |
| `version_checker` | 1 | 9 | 200 |
| `workflow_state` | 5 | 4 | 388 |
