# Migration Map: Python to Elixir (bd-144, Phase 0.2 of bd-132)

> **Generated:** 2026-04-18 | **Total Python Files:** 518 | **Total LOC:** ~145K

---

## Section 1 — Summary Counts

| Metric | Count | LOC |
|--------|-------|-----|
| **Total Python files** | 518 | ~145,157 |
| **Already PORTED** | 87 | ~28,400 |
| **IN-PROGRESS** | 24 | ~8,200 |
| **TODO (Phase 1-7)** | 156 | ~52,800 |
| **DROP-V1** | 98 | ~26,500 |
| **DEFER (post-v1)** | 67 | ~18,200 |
| **TBD (needs decision)** | 86 | ~11,057 |

### Phase Distribution

| Phase | bd-ID | Focus | Files | LOC |
|-------|-------|-------|-------|-----|
| Phase 1 | bd-134 | Agent Runtime | 32 | ~24,500 |
| Phase 2 | bd-135 | Plugins A/B | 28 | ~12,300 |
| Phase 3 | bd-136 | TUI (Owl + IO.ANSI) | 45 | ~18,200 |
| Phase 4 | bd-137 | Config/Session/Auth | 18 | ~15,800 |
| Phase 5 | bd-138 | API/Browser | 15 | ~8,400 |
| Phase 6 | bd-139 | DBOS → Oban | 4 | ~2,100 |
| Phase 7 | bd-140 | Distribution | 14 | ~6,500 |

---

## Section 2 — Master Table (Per-File Migration Spec)

### Root Modules

| Python Path | LOC | Elixir Target | Phase | Status | Notes |
|-------------|-----|---------------|-------|--------|-------|
| `__init__.py` | 118 | N/A | — | DROP | Package marker only |
| `__main__.py` | 7 | N/A | — | DROP | Entry point, use CLI |
| `_backlog.py` | 115 | CodePuppyControl.EventBus | bd-134 | PORTED | Event backlog buffering |
| `adaptive_rate_limiter.py` | 1,380 | CodePuppyControl.Concurrency.Limiter | bd-134 | TODO | Rate limiting per model |
| `agent_model_pinning.py` | 180 | CodePuppyControl.Agent.ModelPinning | bd-134 | TODO | Per-agent model pinning |
| `agent_pinning_transport.py` | 160 | CodePuppyControl.Agent.ModelPinning | bd-134 | TODO | Transport for pinning |
| `app_runner.py` | 560 | CodePuppyControl.Application | bd-134 | TODO | Main app runner |
| `async_utils.py` | 295 | CodePuppyControl.Utils.Async | bd-134 | DEFER | Python-specific async |
| `callbacks.py` | 1,400 | CodePuppyControl.EventBus | bd-134 | PORTED | Hook/callback system |
| `chatgpt_codex_client.py` | 530 | CodePuppyControl.LLM.Providers.OpenAI | bd-134 | TODO | ChatGPT Codex integration |
| `claude_cache_client.py` | 1,380 | CodePuppyControl.LLM.Providers.Anthropic | bd-134 | TODO | Claude prompt caching |
| `cli_runner.py` | 205 | CodePuppyControl.CLI | bd-134 | TODO | CLI entry point |
| `circuit_state.py` | 23 | CodePuppyControl.Utils | bd-134 | PORTED | Circuit state enum |
| `config.py` | 2,800 | CodePuppyControl.Config | bd-137 | TODO | Main config (split needed) |
| `config_presets.py` | 260 | CodePuppyControl.Config.Presets | bd-137 | TODO | Config presets |
| `console.py` | 110 | CodePuppyControl.TUI.Console | bd-136 | DEFER | Rich console builder |
| `constants.py` | 135 | CodePuppyControl.Constants | bd-134 | PORTED | App constants |
| `dbos_utils.py` | 145 | N/A | bd-139 | DROP-V1 | DBOS removed, use Oban |
| `elixir_transport.py` | 870 | CodePuppyControl.PythonWorker | bd-134 | PORTED | Python↔Elixir bridge |
| `elixir_transport_helpers.py` | 180 | CodePuppyControl.PythonWorker.Helpers | bd-134 | PORTED | Transport helpers |
| `error_logging.py` | 340 | CodePuppyControl.ErrorLogging | bd-134 | TODO | Error logging |
| `errors.py` | 110 | CodePuppyControl.Errors | bd-134 | PORTED | Exception hierarchy |
| `http_utils.py` | 450 | CodePuppyControl.HTTP | bd-134 | TODO | HTTP client utilities |
| `interactive_loop.py` | 880 | CodePuppyControl.Agent.Loop | bd-134 | PORTED | Main REPL loop |
| `keymap.py` | 115 | CodePuppyControl.TUI.Keymap | bd-136 | DEFER | Key bindings |
| `main.py` | 9 | N/A | — | DROP | Trivial entry |
| `message_transport.py` | 330 | CodePuppyControl.MessageCore | bd-134 | TODO | Message serialization |
| `model_availability.py` | 190 | CodePuppyControl.ModelAvailability | bd-134 | TODO | Model availability check |
| `model_config.py` | 180 | CodePuppyControl.ModelFactory | bd-134 | TODO | Model config loading |
| `model_factory.py` | 1,410 | CodePuppyControl.ModelFactory | bd-134 | IN-PROGRESS | Model creation |
| `model_packs.py` | 310 | CodePuppyControl.ModelPacks | bd-134 | TODO | Model pack definitions |
| `model_switching.py` | 63 | CodePuppyControl.ModelFactory | bd-134 | TODO | Model switching logic |
| `model_utils.py` | 140 | CodePuppyControl.ModelUtils | bd-134 | PORTED | Model utilities |
| `models_dev_parser.py` | 790 | CodePuppyControl.ModelsDevParser | bd-134 | TODO | models.dev JSON parser |
| `permission_decision.py` | 67 | CodePuppyControl.PolicyEngine | bd-134 | PORTED | Permission enum |
| `persistence.py` | 300 | CodePuppyControl.Persistence | bd-137 | TODO | State persistence |
| `policy_config.py` | 60 | CodePuppyControl.PolicyEngine | bd-134 | PORTED | Policy config |
| `policy_engine.py` | 395 | CodePuppyControl.PolicyEngine | bd-134 | PORTED | Policy evaluation |
| `prompt_runner.py` | 190 | CodePuppyControl.Agent | bd-134 | TODO | Prompt execution |
| `provider_identity.py` | 90 | CodePuppyControl.LLM | bd-134 | TODO | Provider identity |
| `pydantic_patches.py` | 740 | N/A | — | DROP-V1 | pydantic-ai specific |
| `reflection.py` | 180 | CodePuppyControl.Reflection | bd-134 | TODO | Agent reflection |
| `reopenable_async_client.py` | 280 | CodePuppyControl.HTTP | bd-134 | TODO | Reopenable HTTP client |
| `repl_session.py` | 390 | CodePuppyControl.Sessions | bd-137 | TODO | REPL session state |
| `request_cache.py` | 595 | CodePuppyControl.HTTP.Cache | bd-134 | TODO | Request caching |
| `resilience.py` | 760 | CodePuppyControl.Resilience | bd-134 | TODO | Retry/circuit breaker |
| `round_robin_model.py` | 195 | CodePuppyControl.RoundRobinModel | bd-134 | TODO | Round-robin model selection |
| `run_context.py` | 280 | CodePuppyControl.Agent.RunContext | bd-134 | TODO | Run context |
| `runtime_state.py` | 185 | CodePuppyControl.RuntimeState | bd-134 | TODO | Runtime state |
| `security.py` | 410 | CodePuppyControl.Security | bd-137 | TODO | Security utilities |
| `sensitive_paths.py` | 250 | CodePuppyControl.Security | bd-137 | TODO | Sensitive path detection |
| `session_storage.py` | 1,060 | CodePuppyControl.Sessions | bd-137 | PORTED | Session persistence |
| `session_storage_bridge.py` | 145 | CodePuppyControl.Sessions | bd-137 | TODO | Session bridge |
| `staged_changes.py` | 580 | CodePuppyControl.Tools | bd-134 | TODO | Staged file changes |
| `status_display.py` | 390 | CodePuppyControl.TUI.Status | bd-136 | DEFER | Status display |
| `summarization_agent.py` | 210 | CodePuppyControl.Agent.Summarization | bd-134 | TODO | Summarization agent |
| `terminal_utils.py` | 425 | CodePuppyControl.TUI | bd-136 | DEFER | Terminal utilities |
| `text_ops.py` | 200 | CodePuppyControl.Text | bd-134 | TODO | Text operations |
| `token_counting.py` | 120 | CodePuppyControl.Tokens | bd-134 | PORTED | Token counting |
| `token_ledger.py` | 310 | CodePuppyControl.Tokens | bd-134 | TODO | Token tracking |
| `token_utils.py` | 100 | CodePuppyControl.Tokens | bd-134 | PORTED | Token utilities |
| `tool_schema.py` | 340 | CodePuppyControl.Tool.Schema | bd-134 | TODO | Tool schema |
| `uvx_detection.py` | 240 | CodePuppyControl.MCP | bd-134 | TODO | uvx detection |
| `version_checker.py` | 240 | CodePuppyControl.Version | bd-134 | TODO | Version checking |
| `workflow_state.py` | 390 | CodePuppyControl.Workflow | bd-134 | TODO | Workflow state |

### agents/ Directory

| Python Path | LOC | Elixir Target | Phase | Status | Notes |
|-------------|-----|---------------|-------|--------|-------|
| `agents/__init__.py` | 25 | N/A | — | DROP | Package marker |
| `agents/agent_code_puppy.py` | 115 | CodePuppyControl.Agent.Catalogue | bd-134 | TODO | CodePuppy agent |
| `agents/agent_code_reviewer.py` | 155 | CodePuppyControl.Agent.Catalogue | bd-134 | TODO | Code reviewer |
| `agents/agent_code_scout.py` | 195 | CodePuppyControl.Agent.Catalogue | bd-134 | TODO | Code scout |
| `agents/agent_creator_agent.py` | 825 | CodePuppyControl.Agent.Catalogue | bd-134 | TODO | Agent creator |
| `agents/agent_golang_reviewer.py` | 305 | CodePuppyControl.Agent.Catalogue | bd-134 | TODO | Golang reviewer |
| `agents/agent_helios.py` | 170 | CodePuppyControl.Agent.Catalogue | bd-134 | TODO | Helios agent |
| `agents/agent_javascript_reviewer.py` | 310 | CodePuppyControl.Agent.Catalogue | bd-134 | TODO | JS reviewer |
| `agents/agent_manager.py` | 1,255 | CodePuppyControl.Agent.Manager | bd-134 | IN-PROGRESS | Agent lifecycle |
| `agents/agent_pack_leader.py` | 565 | CodePuppyControl.Agent.Pack | bd-134 | TODO | Pack leader |
| `agents/agent_planning.py` | 220 | CodePuppyControl.Agent.Catalogue | bd-134 | TODO | Planning agent |
| `agents/agent_prompt_mixin.py` | 145 | CodePuppyControl.Agent.PromptMixin | bd-134 | TODO | Prompt mixin |
| `agents/agent_python_programmer.py` | 230 | CodePuppyControl.Agent.Catalogue | bd-134 | TODO | Python programmer |
| `agents/agent_python_reviewer.py` | 190 | CodePuppyControl.Agent.Catalogue | bd-134 | TODO | Python reviewer |
| `agents/agent_qa_expert.py` | 330 | CodePuppyControl.Agent.Catalogue | bd-134 | TODO | QA expert |
| `agents/agent_qa_kitten.py` | 310 | CodePuppyControl.Agent.Catalogue | bd-134 | TODO | QA kitten |
| `agents/agent_scheduler.py` | 145 | CodePuppyControl.Agent.Catalogue | bd-134 | TODO | Scheduler agent |
| `agents/agent_security_auditor.py` | 395 | CodePuppyControl.Agent.Catalogue | bd-134 | TODO | Security auditor |
| `agents/agent_state.py` | 210 | CodePuppyControl.Agent.State | bd-134 | TODO | Agent state |
| `agents/agent_terminal_qa.py` | 340 | CodePuppyControl.Agent.Catalogue | bd-134 | TODO | Terminal QA |
| `agents/agent_turbo_executor.py` | 170 | CodePuppyControl.Agent.Catalogue | bd-134 | TODO | Turbo executor agent |
| `agents/agent_typescript_reviewer.py` | 340 | CodePuppyControl.Agent.Catalogue | bd-134 | TODO | TS reviewer |
| `agents/base_agent.py` | 4,040 | CodePuppyControl.Agent.Behaviour | bd-134 | IN-PROGRESS | Base agent class |
| `agents/event_stream_handler.py` | 690 | CodePuppyControl.Agent.Stream | bd-134 | TODO | Event streaming |
| `agents/json_agent.py` | 225 | CodePuppyControl.Agent.JSON | bd-134 | TODO | JSON agent |
| `agents/prompt_reviewer.py` | 175 | CodePuppyControl.Agent.Catalogue | bd-134 | TODO | Prompt reviewer |
| `agents/stream_event_normalizer.py` | 180 | CodePuppyControl.Agent.Stream | bd-134 | TODO | Event normalization |
| `agents/subagent_stream_handler.py` | 370 | CodePuppyControl.Agent.SubAgent | bd-134 | TODO | Subagent streaming |
| `agents/pack/__init__.py` | 40 | N/A | — | DROP | Package marker |
| `agents/pack/bloodhound.py` | 305 | CodePuppyControl.Agent.Pack | bd-134 | TODO | Bloodhound agent |
| `agents/pack/retriever.py` | 330 | CodePuppyControl.Agent.Pack | bd-134 | TODO | Retriever agent |
| `agents/pack/shepherd.py` | 315 | CodePuppyControl.Agent.Pack | bd-134 | TODO | Shepherd agent |
| `agents/pack/terrier.py` | 260 | CodePuppyControl.Agent.Pack | bd-134 | TODO | Terrier agent |
| `agents/pack/watchdog.py` | 325 | CodePuppyControl.Agent.Pack | bd-134 | TODO | Watchdog agent |

### api/ Directory

| Python Path | LOC | Elixir Target | Phase | Status | Notes |
|-------------|-----|---------------|-------|--------|-------|
| `api/__init__.py` | 12 | N/A | — | DROP | Package marker |
| `api/app.py` | 195 | CodePuppyControl.API.App | bd-138 | TODO | FastAPI app |
| `api/main.py` | 15 | N/A | — | DROP | Trivial entry |
| `api/pty_manager.py` | 495 | CodePuppyControl.API.PTY | bd-138 | TODO | PTY management |
| `api/routers/__init__.py` | 14 | N/A | — | DROP | Package marker |
| `api/routers/agents.py` | 30 | CodePuppyControl.API.Routers | bd-138 | TODO | Agents router |
| `api/routers/commands.py` | 420 | CodePuppyControl.API.Routers | bd-138 | TODO | Commands router |
| `api/routers/config.py` | 110 | CodePuppyControl.API.Routers | bd-138 | TODO | Config router |
| `api/routers/sessions.py` | 410 | CodePuppyControl.API.Routers | bd-138 | TODO | Sessions router |
| `api/schemas.py` | 27 | N/A | — | DROP | Pydantic schemas |
| `api/security.py` | 315 | CodePuppyControl.API.Security | bd-138 | TODO | API security |
| `api/websocket.py` | 460 | CodePuppyControl.API.WebSocket | bd-138 | TODO | WebSocket handling |

### command_line/ Directory

| Python Path | LOC | Elixir Target | Phase | Status | Notes |
|-------------|-----|---------------|-------|--------|-------|
| `command_line/__init__.py` | 2 | N/A | — | DROP | Package marker |
| `command_line/add_model_menu.py` | 1,485 | CodePuppyControl.TUI.Forms | bd-136 | DEFER | Add model form |
| `command_line/agent_menu.py` | 625 | CodePuppyControl.TUI.Forms | bd-136 | DEFER | Agent picker |
| `command_line/attachments.py` | 425 | CodePuppyControl.Attachments | bd-134 | TODO | Prompt attachments |
| `command_line/autosave_menu.py` | 1,650 | CodePuppyControl.TUI.Forms | bd-136 | DEFER | Autosave browser |
| `command_line/clipboard.py` | 1,720 | CodePuppyControl.TUI.Clipboard | bd-136 | DEFER | Clipboard handling |
| `command_line/colors_menu.py` | 1,770 | CodePuppyControl.TUI.Forms | bd-136 | DEFER | Color picker |
| `command_line/command_handler.py` | 405 | CodePuppyControl.CommandLine | bd-136 | DEFER | Command dispatch |
| `command_line/command_registry.py` | 145 | CodePuppyControl.CommandLine | bd-136 | DEFER | Command registry |
| `command_line/concurrency_commands.py` | 105 | CodePuppyControl.CommandLine | bd-136 | DEFER | Concurrency commands |
| `command_line/config_commands.py` | 820 | CodePuppyControl.CommandLine | bd-136 | DEFER | Config commands |
| `command_line/core_commands.py` | 2,690 | CodePuppyControl.CommandLine | bd-136 | DEFER | Core commands |
| `command_line/diff_menu.py` | 2,370 | CodePuppyControl.TUI.Forms | bd-136 | DEFER | Diff settings |
| `command_line/file_path_completion.py` | 95 | CodePuppyControl.TUI.Completion | bd-136 | DEFER | File path completer |
| `command_line/load_context_completion.py` | 75 | CodePuppyControl.TUI.Completion | bd-136 | DEFER | Context completer |
| `command_line/mcp_completion.py` | 225 | CodePuppyControl.TUI.Completion | bd-136 | DEFER | MCP completer |
| `command_line/model_picker_completion.py` | 1,410 | CodePuppyControl.TUI.Forms | bd-136 | DEFER | Model picker |
| `command_line/model_settings_menu.py` | 3,470 | CodePuppyControl.TUI.Forms | bd-136 | DEFER | Model settings |
| `command_line/motd.py` | 95 | CodePuppyControl.MOTD | bd-134 | TODO | MOTD display |
| `command_line/onboarding_slides.py` | 230 | CodePuppyControl.TUI.Onboarding | bd-136 | DEFER | Onboarding slides |
| `command_line/onboarding_wizard.py` | 340 | CodePuppyControl.TUI.Onboarding | bd-136 | DEFER | Onboarding wizard |
| `command_line/pack_commands.py` | 115 | CodePuppyControl.CommandLine | bd-136 | DEFER | Pack commands |
| `command_line/pagination.py` | 45 | CodePuppyControl.TUI.Pagination | bd-136 | DEFER | Pagination utils |
| `command_line/pin_command_completion.py` | 380 | CodePuppyControl.TUI.Completion | bd-136 | DEFER | Pin completer |
| `command_line/preset_commands.py` | 95 | CodePuppyControl.CommandLine | bd-136 | DEFER | Preset commands |
| `command_line/prompt_toolkit_completion.py` | 3,330 | CodePuppyControl.TUI.Completion | bd-136 | DEFER | Prompt toolkit |
| `command_line/repl_commands.py` | 190 | CodePuppyControl.CommandLine | bd-136 | DEFER | REPL commands |
| `command_line/session_commands.py` | 335 | CodePuppyControl.CommandLine | bd-136 | DEFER | Session commands |
| `command_line/shell_passthrough.py` | 270 | CodePuppyControl.CommandLine | bd-136 | DEFER | Shell passthrough |
| `command_line/skills_completion.py` | 185 | CodePuppyControl.TUI.Completion | bd-136 | DEFER | Skills completer |
| `command_line/staged_commands.py` | 320 | CodePuppyControl.CommandLine | bd-136 | DEFER | Staged commands |
| `command_line/uc_menu.py` | 2,590 | CodePuppyControl.TUI.Forms | bd-136 | DEFER | UC menu |
| `command_line/utils.py` | 95 | CodePuppyControl.CommandLine | bd-136 | DEFER | CLI utils |
| `command_line/wiggum_state.py` | 65 | CodePuppyControl.CommandLine | bd-136 | DEFER | Wiggum state |
| `command_line/workflow_commands.py` | 115 | CodePuppyControl.CommandLine | bd-136 | DEFER | Workflow commands |

### command_line/mcp/ Directory

| Python Path | LOC | Elixir Target | Phase | Status | Notes |
|-------------|-----|---------------|-------|--------|-------|
| `command_line/mcp/__init__.py` | 10 | N/A | — | DROP | Package marker |
| `command_line/mcp/base.py` | 27 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | MCP command base |
| `command_line/mcp/catalog_server_installer.py` | 200 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | Catalog installer |
| `command_line/mcp/custom_server_form.py` | 2,300 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | Custom server form |
| `command_line/mcp/custom_server_installer.py` | 185 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | Custom installer |
| `command_line/mcp/edit_command.py` | 140 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | Edit command |
| `command_line/mcp/handler.py` | 145 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | Command handler |
| `command_line/mcp/help_command.py` | 170 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | Help command |
| `command_line/mcp/install_command.py` | 270 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | Install command |
| `command_line/mcp/install_menu.py` | 2,460 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | Install menu |
| `command_line/mcp/list_command.py` | 105 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | List command |
| `command_line/mcp/logs_command.py` | 250 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | Logs command |
| `command_line/mcp/remove_command.py` | 90 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | Remove command |
| `command_line/mcp/restart_command.py` | 115 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | Restart command |
| `command_line/mcp/search_command.py` | 135 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | Search command |
| `command_line/mcp/start_all_command.py` | 150 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | Start all |
| `command_line/mcp/start_command.py` | 135 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | Start command |
| `command_line/mcp/status_command.py` | 220 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | Status command |
| `command_line/mcp/stop_all_command.py` | 125 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | Stop all |
| `command_line/mcp/stop_command.py` | 85 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | Stop command |
| `command_line/mcp/test_command.py` | 120 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | Test command |
| `command_line/mcp/utils.py` | 115 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | MCP utils |
| `command_line/mcp/wizard_utils.py` | 360 | CodePuppyControl.TUI.MCP | bd-136 | DEFER | Wizard utils |

### compaction/ Directory

| Python Path | LOC | Elixir Target | Phase | Status | Notes |
|-------------|-----|---------------|-------|--------|-------|
| `compaction/__init__.py` | 47 | N/A | — | DROP | Package marker |
| `compaction/file_ops_tracker.py` | 185 | CodePuppyControl.Compaction | bd-134 | TODO | File ops tracking |
| `compaction/history_offload.py` | 305 | CodePuppyControl.Compaction | bd-134 | TODO | History offloading |
| `compaction/shadow_mode.py` | 170 | CodePuppyControl.Compaction | bd-134 | TODO | Shadow mode |
| `compaction/thresholds.py` | 155 | CodePuppyControl.Compaction | bd-134 | TODO | Summarization thresholds |
| `compaction/tool_arg_truncation.py` | 315 | CodePuppyControl.Compaction | bd-134 | TODO | Tool arg truncation |

### config_package/ Directory

| Python Path | LOC | Elixir Target | Phase | Status | Notes |
|-------------|-----|---------------|-------|--------|-------|
| `config_package/__init__.py` | 55 | N/A | — | DROP | Package marker |
| `config_package/_resolvers.py` | 240 | CodePuppyControl.Config | bd-137 | TODO | Config resolvers |
| `config_package/env_helpers.py` | 175 | CodePuppyControl.Config | bd-137 | TODO | Env helpers |
| `config_package/loader.py` | 450 | CodePuppyControl.Config | bd-137 | TODO | Config loader |
| `config_package/models.py` | 340 | CodePuppyControl.Config | bd-137 | TODO | Config models |

### hook_engine/ Directory

| Python Path | LOC | Elixir Target | Phase | Status | Notes |
|-------------|-----|---------------|-------|--------|-------|
| `hook_engine/__init__.py` | 12 | N/A | — | DROP | Package marker |
| `hook_engine/aliases.py` | 195 | CodePuppyControl.HookEngine | bd-134 | TODO | Hook aliases |
| `hook_engine/engine.py` | 235 | CodePuppyControl.HookEngine | bd-134 | TODO | Hook engine |
| `hook_engine/executor.py` | 320 | CodePuppyControl.HookEngine | bd-134 | TODO | Hook executor |
| `hook_engine/matcher.py` | 205 | CodePuppyControl.HookEngine | bd-134 | TODO | Hook matcher |
| `hook_engine/models.py` | 235 | CodePuppyControl.HookEngine | bd-134 | TODO | Hook models |
| `hook_engine/registry.py` | 105 | CodePuppyControl.HookEngine | bd-134 | TODO | Hook registry |
| `hook_engine/validator.py` | 145 | CodePuppyControl.HookEngine | bd-134 | TODO | Hook validator |

### mcp_/ Directory

| Python Path | LOC | Elixir Target | Phase | Status | Notes |
|-------------|-----|---------------|-------|--------|-------|
| `mcp_/__init__.py` | 90 | N/A | — | DROP | Package marker |
| `mcp_/async_lifecycle.py` | 310 | CodePuppyControl.MCP | bd-134 | TODO | Async lifecycle |
| `mcp_/blocking_startup.py` | 525 | CodePuppyControl.MCP | bd-134 | TODO | Blocking startup |
| `mcp_/captured_stdio_server.py` | 290 | CodePuppyControl.MCP | bd-134 | TODO | Captured stdio |
| `mcp_/circuit_breaker.py` | 355 | CodePuppyControl.MCP | bd-134 | TODO | Circuit breaker |
| `mcp_/config_wizard.py` | 600 | CodePuppyControl.MCP | bd-134 | TODO | Config wizard |
| `mcp_/dashboard.py` | 305 | CodePuppyControl.MCP | bd-134 | TODO | MCP dashboard |
| `mcp_/error_isolation.py` | 435 | CodePuppyControl.MCP | bd-134 | TODO | Error isolation |
| `mcp_/health_monitor.py` | 705 | CodePuppyControl.MCP | bd-134 | TODO | Health monitoring |
| `mcp_/managed_server.py` | 535 | CodePuppyControl.MCP | bd-134 | TODO | Managed server |
| `mcp_/manager.py` | 1,240 | CodePuppyControl.MCP.Manager | bd-134 | PORTED | MCP manager |
| `mcp_/mcp_logs.py` | 205 | CodePuppyControl.MCP | bd-134 | TODO | MCP logging |
| `mcp_/mcp_security.py` | 455 | CodePuppyControl.MCP | bd-134 | TODO | MCP security |
| `mcp_/registry.py` | 515 | CodePuppyControl.MCP | bd-134 | TODO | Server registry |
| `mcp_/retry_manager.py` | 375 | CodePuppyControl.MCP | bd-134 | TODO | Retry manager |
| `mcp_/server_registry_catalog.py` | 1,315 | CodePuppyControl.MCP | bd-134 | TODO | Server catalog |
| `mcp_/status_tracker.py` | 395 | CodePuppyControl.MCP | bd-134 | TODO | Status tracking |
| `mcp_/system_tools.py` | 235 | CodePuppyControl.MCP | bd-134 | TODO | System tools |
| `mcp_/examples/retry_example.py` | 235 | N/A | — | DROP | Example only |

### messaging/ Directory

| Python Path | LOC | Elixir Target | Phase | Status | Notes |
|-------------|-----|---------------|-------|--------|-------|
| `messaging/__init__.py` | 240 | N/A | — | DROP | Package marker |
| `messaging/bus.py` | 1,135 | CodePuppyControl.EventBus | bd-134 | IN-PROGRESS | Message bus |
| `messaging/commands.py` | 175 | CodePuppyControl.Messaging | bd-134 | TODO | Command types |
| `messaging/history_buffer.py` | 350 | CodePuppyControl.Messaging | bd-134 | TODO | History buffer |
| `messaging/markdown_patches.py` | 50 | N/A | — | DROP-V1 | Rich-specific |
| `messaging/message_queue.py` | 505 | CodePuppyControl.Messaging | bd-134 | TODO | Message queue |
| `messaging/messages.py` | 700 | CodePuppyControl.Messaging | bd-134 | TODO | Message types |
| `messaging/queue_console.py` | 520 | CodePuppyControl.Messaging | bd-134 | TODO | Queue console |
| `messaging/renderers.py` | 370 | CodePuppyControl.TUI.Renderer | bd-136 | DEFER | Renderer base |
| `messaging/rich_renderer.py` | 1,960 | DEFER (Ratatouille) | bd-136 | DEFER | Rich renderer |
| `messaging/spinner/__init__.py` | 195 | CodePuppyControl.TUI.Spinner | bd-136 | DEFER | Spinner module |
| `messaging/spinner/console_spinner.py` | 290 | CodePuppyControl.TUI.Spinner | bd-136 | DEFER | Console spinner |
| `messaging/spinner/spinner_base.py` | 85 | CodePuppyControl.TUI.Spinner | bd-136 | DEFER | Spinner base |
| `messaging/subagent_console.py` | 520 | CodePuppyControl.Messaging | bd-134 | TODO | Subagent console |

### plugins/ Directory (See Section 3 for Plugin Map)

### scheduler/ Directory

| Python Path | LOC | Elixir Target | Phase | Status | Notes |
|-------------|-----|---------------|-------|--------|-------|
| `scheduler/__init__.py` | 55 | CodePuppyControl.Scheduler | bd-139 | PORTED | Scheduler init |
| `scheduler/__main__.py` | 15 | N/A | — | DROP | Entry point |
| `scheduler/cli.py` | 125 | CodePuppyControl.Scheduler | bd-139 | TODO | Scheduler CLI |
| `scheduler/config.py` | 135 | CodePuppyControl.Scheduler | bd-139 | TODO | Scheduler config |
| `scheduler/daemon.py` | 335 | CodePuppyControl.Scheduler | bd-139 | TODO | Scheduler daemon |
| `scheduler/executor.py` | 155 | CodePuppyControl.Scheduler | bd-139 | TODO | Task executor |
| `scheduler/platform.py` | 22 | N/A | — | DROP | Platform selector |
| `scheduler/platform_unix.py` | 25 | N/A | — | DROP | Unix platform |
| `scheduler/platform_win.py` | 35 | N/A | — | DROP | Windows platform |

### tools/ Directory

| Python Path | LOC | Elixir Target | Phase | Status | Notes |
|-------------|-----|---------------|-------|--------|-------|
| `tools/__init__.py` | 615 | N/A | — | DROP | Package marker |
| `tools/agent_tools.py` | 1,325 | CodePuppyControl.Tools | bd-134 | TODO | Agent tools |
| `tools/command_runner.py` | 2,170 | CodePuppyControl.Tools.CommandRunner | bd-134 | PORTED | Command runner |
| `tools/common.py` | 1,335 | CodePuppyControl.Tools | bd-134 | TODO | Common tools |
| `tools/display.py` | 75 | N/A | — | DROP | Trivial |
| `tools/file_modifications.py` | 1,195 | CodePuppyControl.Tools | bd-134 | TODO | File modifications |
| `tools/file_operations.py` | 320 | CodePuppyControl.FileOps | bd-134 | PORTED | File operations |
| `tools/process_runner_protocol.py` | 375 | CodePuppyControl.Tools | bd-134 | TODO | Process protocol |
| `tools/scheduler_tools.py` | 475 | CodePuppyControl.Tools | bd-134 | TODO | Scheduler tools |
| `tools/skills_tools.py` | 255 | CodePuppyControl.Tools | bd-134 | TODO | Skills tools |
| `tools/subagent_context.py` | 155 | CodePuppyControl.Tools | bd-134 | TODO | Subagent context |
| `tools/tools_content.py` | 75 | N/A | — | DROP | Trivial |
| `tools/universal_constructor.py` | 985 | CodePuppyControl.Tools.UniversalConstructor | bd-134 | TODO | Universal constructor |

### tools/browser/ Directory (DROP-V1)

| Python Path | LOC | Elixir Target | Phase | Status | Notes |
|-------------|-----|---------------|-------|--------|-------|
| `tools/browser/__init__.py` | 30 | N/A | — | DROP-V1 | Browser tools dropped |
| `tools/browser/browser_control.py` | 270 | N/A | — | DROP-V1 | Playwright control |
| `tools/browser/browser_interactions.py` | 535 | N/A | — | DROP-V1 | Browser interactions |
| `tools/browser/browser_locators.py` | 610 | N/A | — | DROP-V1 | Locator strategies |
| `tools/browser/browser_manager.py` | 420 | N/A | — | DROP-V1 | Browser manager |
| `tools/browser/browser_navigation.py` | 235 | N/A | — | DROP-V1 | Navigation |
| `tools/browser/browser_screenshot.py` | 200 | N/A | — | DROP-V1 | Screenshots |
| `tools/browser/browser_scripts.py` | 475 | N/A | — | DROP-V1 | Browser scripts |
| `tools/browser/browser_workflows.py` | 200 | N/A | — | DROP-V1 | Workflows |
| `tools/browser/chromium_terminal_manager.py` | 265 | N/A | — | DROP-V1 | Chromium manager |
| `tools/browser/terminal_command_tools.py` | 635 | N/A | — | DROP-V1 | Terminal browser |
| `tools/browser/terminal_screenshot_tools.py` | 755 | N/A | — | DROP-V1 | Terminal screenshots |
| `tools/browser/terminal_tools.py` | 575 | N/A | — | DROP-V1 | Terminal tools |

### tools/ask_user_question/ Directory

| Python Path | LOC | Elixir Target | Phase | Status | Notes |
|-------------|-----|---------------|-------|--------|-------|
| `tools/ask_user_question/__init__.py` | 22 | N/A | — | DROP | Package marker |
| `tools/ask_user_question/constants.py` | 75 | CodePuppyControl.Tools | bd-134 | TODO | Constants |
| `tools/ask_user_question/handler.py` | 265 | CodePuppyControl.Tools | bd-134 | TODO | Question handler |
| `tools/ask_user_question/helpers.py` | 70 | CodePuppyControl.Tools | bd-134 | TODO | Helpers |
| `tools/ask_user_question/models.py` | 275 | CodePuppyControl.Tools | bd-134 | TODO | Question models |
| `tools/ask_user_question/registration.py` | 45 | CodePuppyControl.Tools | bd-134 | TODO | Registration |
| `tools/ask_user_question/renderers.py` | 325 | CodePuppyControl.TUI | bd-136 | DEFER | Renderers |
| `tools/ask_user_question/terminal_ui.py` | 405 | CodePuppyControl.TUI | bd-136 | DEFER | Terminal UI |
| `tools/ask_user_question/theme.py` | 135 | CodePuppyControl.TUI | bd-136 | DEFER | Theme |
| `tools/ask_user_question/tui_loop.py` | 480 | CodePuppyControl.TUI | bd-136 | DEFER | TUI loop |

### tui/ Directory

| Python Path | LOC | Elixir Target | Phase | Status | Notes |
|-------------|-----|---------------|-------|--------|-------|
| `tui/__init__.py` | 17 | N/A | — | DROP | Package marker |
| `tui/app.py` | 1,060 | CodePuppyControl.TUI | bd-136 | DEFER | Main TUI app |
| `tui/base_screen.py` | 25 | N/A | — | DROP | Base screen |
| `tui/completion.py` | 385 | CodePuppyControl.TUI | bd-136 | DEFER | Completion |
| `tui/launcher.py` | 40 | N/A | — | DROP | Launcher |
| `tui/message_bridge.py` | 455 | CodePuppyControl.TUI | bd-136 | DEFER | Message bridge |
| `tui/stream_renderer.py` | 405 | CodePuppyControl.TUI | bd-136 | DEFER | Stream renderer |
| `tui/theme.py` | 115 | CodePuppyControl.TUI | bd-136 | DEFER | Theme |
| `tui/screens/__init__.py` | 6 | N/A | — | DROP | Package marker |
| `tui/screens/add_model_screen.py` | 425 | CodePuppyControl.TUI.Screens | bd-136 | DEFER | Add model |
| `tui/screens/agent_screen.py` | 440 | CodePuppyControl.TUI.Screens | bd-136 | DEFER | Agent screen |
| `tui/screens/autosave_screen.py` | 305 | CodePuppyControl.TUI.Screens | bd-136 | DEFER | Autosave |
| `tui/screens/colors_screen.py` | 435 | CodePuppyControl.TUI.Screens | bd-136 | DEFER | Colors |
| `tui/screens/diff_screen.py` | 480 | CodePuppyControl.TUI.Screens | bd-136 | DEFER | Diff |
| `tui/screens/hooks_screen.py` | 250 | CodePuppyControl.TUI.Screens | bd-136 | DEFER | Hooks |
| `tui/screens/mcp_form_screen.py` | 390 | CodePuppyControl.TUI.Screens | bd-136 | DEFER | MCP form |
| `tui/screens/mcp_screen.py` | 340 | CodePuppyControl.TUI.Screens | bd-136 | DEFER | MCP |
| `tui/screens/model_pin_screen.py` | 95 | CodePuppyControl.TUI.Screens | bd-136 | DEFER | Model pin |
| `tui/screens/model_screen.py` | 185 | CodePuppyControl.TUI.Screens | bd-136 | DEFER | Model |
| `tui/screens/model_settings_screen.py` | 410 | CodePuppyControl.TUI.Screens | bd-136 | DEFER | Model settings |
| `tui/screens/onboarding_screen.py` | 175 | CodePuppyControl.TUI.Screens | bd-136 | DEFER | Onboarding |
| `tui/screens/question_screen.py` | 430 | CodePuppyControl.TUI.Screens | bd-136 | DEFER | Question |
| `tui/screens/scheduler_screen.py` | 335 | CodePuppyControl.TUI.Screens | bd-136 | DEFER | Scheduler |
| `tui/screens/scheduler_wizard_screen.py` | 195 | CodePuppyControl.TUI.Screens | bd-136 | DEFER | Scheduler wizard |
| `tui/screens/skills_install_screen.py` | 295 | CodePuppyControl.TUI.Screens | bd-136 | DEFER | Skills install |
| `tui/screens/skills_screen.py` | 325 | CodePuppyControl.TUI.Screens | bd-136 | DEFER | Skills |
| `tui/screens/uc_screen.py` | 400 | CodePuppyControl.TUI.Screens | bd-136 | DEFER | UC screen |
| `tui/widgets/__init__.py` | 12 | N/A | — | DROP | Package marker |
| `tui/widgets/completion_overlay.py` | 110 | CodePuppyControl.TUI.Widgets | bd-136 | DEFER | Completion overlay |
| `tui/widgets/info_bar.py` | 125 | CodePuppyControl.TUI.Widgets | bd-136 | DEFER | Info bar |
| `tui/widgets/searchable_list.py` | 275 | CodePuppyControl.TUI.Widgets | bd-136 | DEFER | Searchable list |
| `tui/widgets/split_panel.py` | 45 | N/A | — | DROP | Trivial |

### utils/ Directory

| Python Path | LOC | Elixir Target | Phase | Status | Notes |
|-------------|-----|---------------|-------|--------|-------|
| `utils/__init__.py` | 165 | N/A | — | DROP | Package marker |
| `utils/adaptive_render.py` | 355 | CodePuppyControl.TUI | bd-136 | DEFER | Adaptive rendering |
| `utils/agent_helpers.py` | 265 | CodePuppyControl.Utils | bd-134 | TODO | Agent helpers |
| `utils/binary_token_estimation.py` | 55 | CodePuppyControl.Tokens | bd-134 | PORTED | Token estimation |
| `utils/checkpoint.py` | 185 | CodePuppyControl.Utils | bd-134 | TODO | Checkpointing |
| `utils/clipboard.py` | 185 | CodePuppyControl.Utils | bd-134 | TODO | Clipboard utils |
| `utils/config_resolve.py` | 325 | CodePuppyControl.Config | bd-137 | TODO | Config resolution |
| `utils/dag.py` | 120 | CodePuppyControl.Utils | bd-134 | TODO | DAG utilities |
| `utils/debouncer.py` | 75 | CodePuppyControl.Utils | bd-134 | TODO | Debouncer |
| `utils/editor_detect.py` | 170 | CodePuppyControl.Utils | bd-134 | TODO | Editor detection |
| `utils/emit.py` | 45 | N/A | — | DROP | Trivial |
| `utils/eol.py` | 155 | CodePuppyControl.Text.EOL | bd-134 | PORTED | EOL handling |
| `utils/file_display.py` | 440 | CodePuppyControl.FileOps | bd-134 | TODO | File display |
| `utils/file_mutex.py` | 335 | CodePuppyControl.Utils | bd-134 | TODO | File mutex |
| `utils/fs_errors.py` | 170 | CodePuppyControl.Utils | bd-134 | TODO | FS error handling |
| `utils/gitignore.py` | 130 | CodePuppyControl.Gitignore | bd-134 | PORTED | Gitignore parsing |
| `utils/hashline.py` | 380 | CodePuppyControl.HashLine | bd-134 | PORTED | Line hashing |
| `utils/install_hints.py` | 100 | N/A | — | DROP | Install hints |
| `utils/llm_parsing.py` | 265 | CodePuppyControl.Utils | bd-134 | TODO | LLM parsing |
| `utils/macos_path.py` | 140 | CodePuppyControl.Utils | bd-134 | TODO | macOS paths |
| `utils/min_duration.py` | 100 | CodePuppyControl.Utils | bd-134 | TODO | Min duration |
| `utils/overflow_detect.py` | 165 | CodePuppyControl.Utils | bd-134 | TODO | Overflow detection |
| `utils/parallel.py` | 410 | CodePuppyControl.Utils | bd-134 | TODO | Parallel utils |
| `utils/path_safety.py` | 255 | CodePuppyControl.Security | bd-137 | TODO | Path safety |
| `utils/peek_file.py` | 215 | CodePuppyControl.FileOps | bd-134 | TODO | File peeking |
| `utils/ring_buffer.py` | 280 | CodePuppyControl.Utils | bd-134 | TODO | Ring buffer |
| `utils/shell_split.py` | 85 | CodePuppyControl.Utils | bd-134 | PORTED | Shell splitting |
| `utils/stream_parser.py` | 185 | CodePuppyControl.Utils | bd-134 | TODO | Stream parsing |
| `utils/subtask_parser.py` | 135 | CodePuppyControl.Utils | bd-134 | TODO | Subtask parsing |
| `utils/symbol_hierarchy.py` | 105 | CodePuppyControl.Indexer | bd-134 | TODO | Symbol hierarchy |
| `utils/syntax_validate.py` | 165 | CodePuppyControl.Parsing | bd-134 | TODO | Syntax validation |
| `utils/thread_safe_cache.py` | 45 | CodePuppyControl.Utils | bd-134 | PORTED | Thread-safe cache |
| `utils/whitespace.py` | 60 | CodePuppyControl.Text | bd-134 | PORTED | Whitespace utils |

---

## Section 3 — Plugin Map

### Tier A (Critical — Must Port)

| Plugin Dir | LOC | Elixir Target | Phase | Status | Notes |
|------------|-----|---------------|-------|--------|-------|
| `plugins/elixir_bridge/` | 1,335 | CodePuppyControl.PythonWorker | bd-134 | IN-PROGRESS | Core bridge |
| `plugins/fast_puppy/` | 27 | CodePuppyControl.FastPuppy | bd-134 | TODO | Native backend selector |
| `plugins/repo_compass/` | 325 | CodePuppyControl.Indexer.RepoCompass | bd-134 | PORTED | Repo indexing |
| `plugins/file_mentions/` | 310 | CodePuppyControl.FileOps | bd-134 | TODO | @file mentions |
| `plugins/claude_code_oauth/` | 525 | CodePuppyControl.Auth | bd-137 | TODO | Claude OAuth |
| `plugins/chatgpt_oauth/` | 430 | CodePuppyControl.Auth | bd-137 | TODO | ChatGPT OAuth |
| `plugins/pack_parallelism/` | 525 | CodePuppyControl.Concurrency.Limiter | bd-134 | PORTED | Pack parallelism |
| `plugins/shell_safety/` | 645 | CodePuppyControl.Tools.CommandRunner.Validator | bd-134 | IN-PROGRESS | Shell safety |
| `plugins/turbo_executor/` | 525 | CodePuppyControl.TurboExecutor | bd-134 | TODO | Batch file ops |

### Tier B (Important — Should Port)

| Plugin Dir | LOC | Elixir Target | Phase | Status | Notes |
|------------|-----|---------------|-------|--------|-------|
| `plugins/agent_memory/` | 875 | CodePuppyControl.Agent.Memory | bd-135 | TODO | Agent memory |
| `plugins/agent_trace/` | 1,135 | CodePuppyControl.Agent.Trace | bd-135 | TODO | Agent tracing |
| `plugins/agent_skills/` | 1,235 | CodePuppyControl.Agent.Skills | bd-135 | TODO | Agent skills |
| `plugins/loop_detection/` | 560 | CodePuppyControl.Agent.LoopDetection | bd-135 | TODO | Loop detection |
| `plugins/error_classifier/` | 325 | CodePuppyControl.ErrorClassifier | bd-135 | TODO | Error classification |
| `plugins/scheduler/` | 725 | CodePuppyControl.Scheduler | bd-135 | TODO | Scheduler plugin |
| `plugins/cost_estimator/` | 270 | CodePuppyControl.CostEstimator | bd-135 | TODO | Cost estimation |
| `plugins/git_auto_commit/` | 535 | CodePuppyControl.GitAutoCommit | bd-135 | TODO | Auto commit |

### Tier C (Drop or Defer)

| Plugin Dir | LOC | Elixir Target | Phase | Status | Notes |
|------------|-----|---------------|-------|--------|-------|
| `plugins/agent_shortcuts/` | 130 | N/A | — | DROP | Trivial wrapper |
| `plugins/claude_code_hooks/` | 165 | N/A | — | DROP | Superseded |
| `plugins/clean_command/` | 435 | DEFER | bd-135 | DEFER | Nice to have |
| `plugins/code_explorer/` | 590 | DEFER | bd-135 | DEFER | Code exploration |
| `plugins/code_skeleton/` | 335 | N/A | — | DROP | Code generation |
| `plugins/completion_notifier/` | 205 | N/A | — | DROP | Notification only |
| `plugins/customizable_commands/` | 165 | DEFER | bd-135 | DEFER | Custom commands |
| `plugins/error_logger/` | 170 | N/A | — | DROP | Simple logging |
| `plugins/example_custom_command/` | 55 | N/A | — | DROP | Example only |
| `plugins/file_permission_handler/` | 605 | CodePuppyControl.PolicyEngine | bd-134 | TODO | File permissions |
| `plugins/frontend_emitter/` | 265 | DEFER | bd-135 | DEFER | Frontend events |
| `plugins/hook_creator/` | 32 | N/A | — | DROP | Trivial |
| `plugins/hook_manager/` | 660 | DEFER | bd-135 | DEFER | Hook management |
| `plugins/ollama_setup/` | 395 | N/A | — | DROP | Ollama specific |
| `plugins/pop_command/` | 155 | N/A | — | DROP | Trivial |
| `plugins/proactive_guidance/` | 435 | N/A | — | DROP | Experimental |
| `plugins/prompt_store/` | 660 | DEFER | bd-135 | DEFER | Prompt storage |
| `plugins/remember_last_agent/` | 95 | N/A | — | DROP | Trivial |
| `plugins/render_check/` | 240 | N/A | — | DROP | Debug only |
| `plugins/session_logger/` | 490 | DEFER | bd-135 | DEFER | Session logging |
| `plugins/supervisor_review/` | 525 | DEFER | bd-135 | DEFER | Review system |
| `plugins/synthetic_status/` | 145 | N/A | — | DROP | Status API |
| `plugins/theme_switcher/` | 135 | DEFER | bd-135 | DEFER | Theme switching |
| `plugins/tool_allowlist/` | 245 | N/A | — | DROP | Tool filtering |
| `plugins/tracing_langfuse/` | 485 | N/A | — | DROP | Langfuse specific |
| `plugins/tracing_langsmith/` | 475 | N/A | — | DROP | Langsmith specific |
| `plugins/ttsr/` | 375 | N/A | — | DROP | TTSR specific |
| `plugins/universal_constructor/` | 375 | CodePuppyControl.Tools.UniversalConstructor | bd-134 | TODO | UC plugin |

---

## Section 4 — Command Menus (TUI Form Specs)

### Menu → Ratatouille Form Mapping

| Menu File | Form Type | Fields | Notes |
|-----------|-----------|--------|-------|
| `add_model_menu.py` | `AddModelForm` | provider, model_id, api_key, settings | Multi-step wizard |
| `agent_menu.py` | `AgentPickerForm` | agent_list, preview_panel, pinned_model | Split panel |
| `autosave_menu.py` | `AutosaveBrowserForm` | session_list, message_preview, restore_btn | List + preview |
| `colors_menu.py` | `ColorsForm` | color_type, color_picker, preview | Live preview |
| `diff_menu.py` | `DiffForm` | style, addition_color, deletion_color, preview | Color picker |
| `model_picker_completion.py` | `ModelPickerForm` | model_list, search, active_model | Filterable list |
| `model_settings_menu.py` | `ModelSettingsForm` | model, setting, value, apply | Per-model settings |
| `uc_menu.py` | `UCMenuForm` | tool_list, source_preview, toggle, delete | List + code view |
| `mcp/install_menu.py` | `MCPInstallForm` | server_list, config_form, install_btn | Catalog browser |
| `mcp/custom_server_form.py` | `CustomServerForm` | name, command, args, env, validate | Multi-field form |

### Command Groups for TUI

| Command Group | Commands | Target Module |
|---------------|----------|---------------|
| Core | /help, /cd, /tools, /motd, /paste, /tutorial, /exit | `CommandLine.Core` |
| Agent | /agent, /model, /add-model, /model-settings | `CommandLine.Agent` |
| MCP | /mcp (subcommands: list, start, stop, status, logs, install) | `CommandLine.MCP` |
| Session | /session, /compact, /truncate, /autosave-load, /dump-context, /load-context | `CommandLine.Session` |
| Config | /show, /set, /reasoning, /verbosity, /pin, /unpin, /diff, /colors | `CommandLine.Config` |
| Staged | /staged (subcommands: summary, diff, preview, apply, reject) | `CommandLine.Staged` |
| Workflow | /flags | `CommandLine.Workflow` |
| Pack | /pack | `CommandLine.Pack` |
| REPL | /repl (subcommands: info, context, history) | `CommandLine.REPL` |

---

## Section 5 — Drop List (Not Porting to v1)

### Rationale Categories

| Category | Count | Rationale |
|----------|-------|-----------|
| Package markers | 18 | `__init__.py` files, no logic |
| Entry points | 6 | Trivial `__main__.py`, `main.py` |
| Browser tools | 13 | Playwright, not core for v1 |
| DBOS | 1 | Use Oban instead |
| pydantic-ai specific | 3 | Python-only dependencies |
| Rich/Terminal UI | 24 | Rewriting for Ratatouille |
| Platform-specific | 3 | Windows/Unix platform files |
| Examples/docs | 4 | Example code only |
| Trivial utilities | 8 | <50 LOC, trivial logic |
| Third-party integrations | 12 | Langfuse, Langsmith, Ollama, TTSR |
| Experimental | 6 | Proactive guidance, render check |
| Superseded | 4 | Claude code hooks, etc. |

### Full Drop List

| File | Rationale |
|------|-----------|
| `__init__.py` (all) | Package markers |
| `__main__.py` | Entry point |
| `main.py` | Trivial entry |
| `dbos_utils.py` | DBOS removed |
| `pydantic_patches.py` | pydantic-ai specific |
| `messaging/markdown_patches.py` | Rich-specific |
| `tools/browser/*` (13 files) | Playwright, not v1 |
| `scheduler/platform*.py` (3) | Platform files |
| `mcp_/examples/*` | Example only |
| `plugins/example_custom_command/*` | Example |
| `plugins/ollama_setup/*` | Ollama specific |
| `plugins/tracing_langfuse/*` | Langfuse specific |
| `plugins/tracing_langsmith/*` | Langsmith specific |
| `plugins/ttsr/*` | TTSR specific |
| `plugins/proactive_guidance/*` | Experimental |
| `plugins/render_check/*` | Debug only |
| `plugins/agent_shortcuts/*` | Trivial wrapper |
| `plugins/claude_code_hooks/*` | Superseded |
| `plugins/error_logger/*` | Simple logging |
| `plugins/hook_creator/*` | Trivial |
| `plugins/pop_command/*` | Trivial |
| `plugins/remember_last_agent/*` | Trivial |
| `plugins/synthetic_status/*` | Status API |
| `plugins/tool_allowlist/*` | Tool filtering |
| `plugins/code_skeleton/*` | Code generation |
| `plugins/completion_notifier/*` | Notification only |
| `plugins/clean_command/*` | Nice to have |
| `plugins/customizable_commands/*` | Custom commands |
| `plugins/frontend_emitter/*` | Frontend events |
| `plugins/hook_manager/*` | Hook management |
| `plugins/prompt_store/*` | Prompt storage |
| `plugins/session_logger/*` | Session logging |
| `plugins/supervisor_review/*` | Review system |
| `plugins/theme_switcher/*` | Theme switching |
| `utils/install_hints/*` | Install hints |
| `utils/emit.py` | Trivial |
| `tui/base_screen.py` | Base screen |
| `tui/launcher.py` | Launcher |
| `tui/widgets/split_panel.py` | Trivial |
| `tools/display.py` | Trivial |
| `tools/tools_content.py` | Trivial |

---

## Section 6 — Already Ported (Cross-Reference)

| Elixir Module | Python Source(s) | LOC |
|---------------|------------------|-----|
| `CodePuppyControl.EventBus` | `callbacks.py`, `_backlog.py`, `messaging/bus.py` | 2,650 |
| `CodePuppyControl.FileOps` | `tools/file_operations.py`, `utils/file_display.py` | 760 |
| `CodePuppyControl.Scheduler` | `scheduler/` (all files) | 1,075 |
| `CodePuppyControl.Sessions` | `session_storage.py` | 1,060 |
| `CodePuppyControl.Agent.Loop` | `interactive_loop.py` | 880 |
| `CodePuppyControl.Tools.CommandRunner` | `tools/command_runner.py` | 2,170 |
| `CodePuppyControl.PolicyEngine` | `policy_engine.py`, `policy_config.py` | 455 |
| `CodePuppyControl.MCP.Manager` | `mcp_/manager.py` | 1,240 |
| `CodePuppyControl.PythonWorker` | `elixir_transport.py`, `elixir_transport_helpers.py` | 1,050 |
| `CodePuppyControl.Concurrency.Limiter` | `plugins/pack_parallelism/` | 525 |
| `CodePuppyControl.Indexer.RepoCompass` | `plugins/repo_compass/` | 325 |
| `CodePuppyControl.HashLine` | `utils/hashline.py` | 380 |
| `CodePuppyControl.Gitignore` | `utils/gitignore.py` | 130 |
| `CodePuppyControl.Text.EOL` | `utils/eol.py` | 155 |
| `CodePuppyControl.Tokens` | `token_counting.py`, `token_utils.py`, `utils/binary_token_estimation.py` | 275 |
| `CodePuppyControl.Errors` | `errors.py` | 110 |
| `CodePuppyControl.Constants` | `constants.py` | 135 |
| `CodePuppyControl.ModelUtils` | `model_utils.py` | 140 |
| `CodePuppyControl.CircuitState` | `circuit_state.py` | 23 |
| `CodePuppyControl.PermissionDecision` | `permission_decision.py` | 67 |
| `CodePuppyControl.ShellSplit` | `utils/shell_split.py` | 85 |
| `CodePuppyControl.ThreadSafeCache` | `utils/thread_safe_cache.py` | 45 |
| `CodePuppyControl.Whitespace` | `utils/whitespace.py` | 60 |

---

## Section 7 — Orphans / TBDs

### Symbols Without Clear Target

| Symbol/Module | Owner Question | Priority |
|---------------|----------------|----------|
| `adaptive_rate_limiter.py` | @platform: Elixir GenServer or ETS? | High |
| `claude_cache_client.py` | @agent-team: Keep prompt caching in Python bridge? | Medium |
| `chatgpt_codex_client.py` | @agent-team: Codex-specific logic needed? | Medium |
| `model_factory.py` | @platform: Complex factory, needs design review | High |
| `base_agent.py` | @agent-team: 4K LOC, how much to Elixir vs keep in bridge? | Critical |
| `config.py` | @platform: 2.8K LOC, needs decomposition | High |
| `messaging/rich_renderer.py` | @tui-team: Any utilities for Ratatouille? | Medium |
| `tui/*` | @tui-team: Full Ratatouille rewrite, keep any patterns? | High |
| `command_line/*` | @tui-team: Convert to data-driven form specs? | High |
| `hook_engine/*` | @platform: Keep in Python bridge or port? | Medium |
| `mcp_/*` | @platform: 15 modules, port incrementally? | High |
| `compaction/*` | @platform: Summarization strategy TBD | Medium |
| `plugins/error_classifier/*` | @agent-team: Error taxonomy useful in Elixir? | Low |
| `plugins/agent_memory/*` | @agent-team: Memory extraction in Python or Elixir? | Medium |
| `plugins/agent_skills/*` | @agent-team: Skill catalog management | Medium |

### Phase 0.3 Decisions Needed

1. **base_agent.py decomposition** — What stays in Python bridge vs moves to Elixir?
2. **config.py split** — Which config sections are Elixir-native?
3. **TUI architecture** — Ratatouille form DSL vs direct code?
4. **MCP module split** — Port all at once or incrementally?
5. **Hook engine** — Keep in Python or rewrite in Elixir?

---

## Top 10 Biggest Files

| File | LOC | Target | Status |
|------|-----|--------|--------|
| `agents/base_agent.py` | 4,040 | CodePuppyControl.Agent.Behaviour | IN-PROGRESS |
| `config.py` | 2,800 | CodePuppyControl.Config | TODO |
| `command_line/model_settings_menu.py` | 3,470 | CodePuppyControl.TUI.Forms | DEFER |
| `command_line/prompt_toolkit_completion.py` | 3,330 | CodePuppyControl.TUI.Completion | DEFER |
| `command_line/diff_menu.py` | 2,370 | CodePuppyControl.TUI.Forms | DEFER |
| `command_line/mcp/custom_server_form.py` | 2,300 | CodePuppyControl.TUI.MCP | DEFER |
| `command_line/mcp/install_menu.py` | 2,460 | CodePuppyControl.TUI.MCP | DEFER |
| `tools/command_runner.py` | 2,170 | CodePuppyControl.Tools.CommandRunner | PORTED |
| `messaging/rich_renderer.py` | 1,960 | DEFER (Ratatouille) | DEFER |
| `command_line/autosave_menu.py` | 1,650 | CodePuppyControl.TUI.Forms | DEFER |

---

## Phase Timeline (Updated)

| Phase | bd-ID | Focus | Duration | Files | LOC |
|-------|-------|-------|----------|-------|-----|
| Phase 0 | bd-132 | Planning | 1 week | — | — |
| Phase 1 | bd-134 | Core Runtime | 3 weeks | 32 | ~24,500 |
| Phase 2 | bd-135 | Plugins A/B | 4 weeks | 28 | ~12,300 |
| Phase 3 | bd-136 | TUI (Owl + IO.ANSI) | 4 weeks | 45 | ~18,200 |
| Phase 4 | bd-137 | Config/Session/Auth | 3 weeks | 18 | ~15,800 |
| Phase 5 | bd-138 | API/Browser | 2 weeks | 15 | ~8,400 |
| Phase 6 | bd-139 | DBOS → Oban | 1 week | 4 | ~2,100 |
| Phase 7 | bd-140 | Distribution | 3 weeks | 14 | ~6,500 |
| **Total** | | | **20 weeks** | **156** | **~87,800** |

---

*Generated by Turbo Executor for bd-144 (Phase 0.2)*
*Last updated: 2026-04-18*

---

## Deferred to v1.1 (2026-04-20 — bd-230)

The following Python components are intentionally NOT ported in the v1 Elixir runtime. Users retain Python-runtime access during v1; these are tracked for v1.1:

| Python source | Reason | Tracking issue |
|---------------|--------|----------------|
| `code_puppy/agents/agent_planning.py` | Zero internal deps; overlaps with code-puppy/pack-leader; `/plan` shortcut works via Python fallback | bd-232 |
