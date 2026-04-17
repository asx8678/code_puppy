# Thin Shell Contract: Python → Elixir Migration

> **Issue:** bd-76  
> **Status:** Draft - Defines the minimal Python surface for Phase 6 end state  
> **Last Updated:** 2026-04-17

---

## Purpose

This document defines the **"thin shell"** — the minimal Python surface that remains after the Elixir migration is complete. It answers:

1. **Why does Python remain?** — TUI rendering, CLI entry point, pydantic-ai agent orchestration
2. **What exactly stays in Python?** — Specific modules with justification
3. **What gets deleted?** — Everything ported to Elixir or redundant
4. **How do they communicate?** — The bridge contract
5. **Decision criteria** — How to determine if a module stays or goes

---

## End State Vision

```
┌─────────────────────────────────────────────────────────────────────┐
│                        PYTHON (Thin Shell)                           │
│  ┌────────────┐  ┌────────────┐  ┌─────────────────────────────┐  │
│  │    CLI     │  │    TUI     │  │   pydantic-ai Agent Loop    │  │
│  │  (typer/   │  │ (Textual/  │  │  (BaseAgent + tool binding)  │  │
│  │  argparse) │  │   Rich)    │  │                             │  │
│  └──────┬─────┘  └──────┬─────┘  └──────────────┬──────────────┘  │
│         │               │                        │                  │
│         └───────────────┴────────────────────────┘                  │
│                              │                                       │
│                    ┌─────────┴──────────┐                          │
│                    │   Bridge Layer       │  ← JSON-RPC over stdio  │
│                    │   (elixir_bridge/)   │                          │
│                    └─────────┬──────────┘                          │
└──────────────────────────────┼──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     ELIXIR (All Runtime)                           │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────┐    │
│  │  Scheduler │  │  FileOps   │  │  Text Ops  │  │  Parse   │    │
│  │   (Oban)   │  │ (list/grep/│  │(diff/fuzzy/│  │ (Tree-   │    │
│  │            │  │  read)     │  │ replace)   │  │ sitter)  │    │
│  └────────────┘  └────────────┘  └────────────┘  └──────────┘    │
│                                                                    │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐                   │
│  │  Message   │  │  Token     │  │  Registry  │                  │
│  │   Core     │  │  Estimate  │  │   (Phx)    │                  │
│  └────────────┘  └────────────┘  └────────────┘                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Retained Modules (The Thin Shell)

### Tier 1: Entry Points (Must Stay)

| Module | Lines | Justification |
|--------|-------|---------------|
| `code_puppy/__main__.py` | ~10 | Python package entry point. Unconditionally required. |
| `code_puppy/main.py` | ~20 | Re-export for `python -m code_puppy`. No logic. |
| `code_puppy/cli_runner.py` | ~200 | CLI argument parsing with **lazy imports** for fast `--help`. Argparse/typer require Python. |

### Tier 2: Application Bootstrap (Must Stay)

| Module | Lines | Justification |
|--------|-------|---------------|
| `code_puppy/app_runner.py` | ~400 | `AppRunner` class orchestrates startup: renderer selection, signal handling, plugin loading, DBOS init. Coordinates the thin shell. |
| `code_puppy/interactive_loop.py` | ~550 | REPL implementation with prompt_toolkit integration. User input handling is inherently Python-side. |
| `code_puppy/repl_session.py` | ~350 | Session persistence across restarts. Manages conversation history metadata and project context. |
| `code_puppy/prompt_runner.py` | ~200 | Executes prompts with attachment handling. Bridges TUI to agent layer. |

### Tier 3: TUI Layer (Must Stay - Rich/Textual)

| Module | Lines | Justification |
|--------|-------|---------------|
| `code_puppy/tui/app.py` | ~800 | Textual TUI main application. Terminal UI framework is Python-native. |
| `code_puppy/tui/screens/*.py` | ~200/ea | 20+ screen modules for settings, agents, MCP, etc. Rich UI components. |
| `code_puppy/tui/widgets/*.py` | ~300 total | Custom widgets (completion overlay, searchable lists). |
| `code_puppy/tui/message_bridge.py` | ~400 | Bridges MessageBus to Textual rendering. |
| `code_puppy/tui/theme.py` | ~150 | Theme configuration for Rich/Textual. |

### Tier 4: Agent Orchestration (Must Stay - pydantic-ai)

| Module | Lines | Justification |
|--------|-------|---------------|
| `code_puppy/agents/base_agent.py` | ~1300 | Core pydantic-ai agent loop. Tool binding, message history, streaming. The **heart** of the thin shell. |
| `code_puppy/agents/agent_prompt_mixin.py` | ~200 | System prompt assembly with plugin hooks. |
| `code_puppy/agents/agent_state.py` | ~250 | AgentRuntimeState for conversation persistence. |
| `code_puppy/agents/event_stream_handler.py` | ~600 | Streaming response handling. |
| `code_puppy/agents/agent_manager.py` | ~800 | Agent registry and discovery. |
| `code_puppy/agents/agent_code_puppy.py` | ~150 | Default agent implementation. |
| `code_puppy/agents/pack/*.py` | ~400 total | Pack sub-agents (Bloodhound, Retriever, etc.). |

### Tier 5: Bridge Layer (Must Stay - Communication)

| Module | Lines | Justification |
|--------|-------|---------------|
| `code_puppy/plugins/elixir_bridge/__init__.py` | ~500 | Client mode for Python → Elixir calls. `call_method()`, `is_connected()`. |
| `code_puppy/plugins/elixir_bridge/bridge_controller.py` | ~1200 | Bridge mode: dispatches JSON-RPC from Elixir to Python tools. |
| `code_puppy/plugins/elixir_bridge/wire_protocol.py` | ~1300 | JSON-RPC serialization, Content-Length framing, event emit. |
| `code_puppy/elixir_transport.py` | ~450 | Standalone Elixir transport for file operations (non-bridge mode). |
| `code_puppy/elixir_transport_helpers.py` | ~200 | Convenience functions for standalone transport. |

### Tier 6: Plugin System (Must Stay - Extension Point)

| Module | Lines | Justification |
|--------|-------|---------------|
| `code_puppy/callbacks.py` | ~800 | Hook registry: `register_callback()`, `on_startup()`, `on_shutdown()`, `pre_tool_call`, `post_tool_call`. |
| `code_puppy/plugins/__init__.py` | ~600 | Plugin loader with auto-discovery. |
| `code_puppy/plugins/*/register_callbacks.py` | ~50-300/ea | Individual plugin hooks. ~50 plugins, ~8KB total. |

### Tier 7: Config & Tool Schema (Must Stay)

| Module | Lines | Justification |
|--------|-------|---------------|
| `code_puppy/config.py` | ~2500 | Configuration system, puppy.cfg parsing, API key management. |
| `code_puppy/config_package/*.py` | ~800 | Pydantic-based config models and loaders. |
| `code_puppy/tool_schema.py` | ~350 | Tool definition schemas for pydantic-ai. |

### Tier 8: Tool Binding (Must Stay - Interface Only)

| Module | Lines | Justification |
|--------|-------|---------------|
| `code_puppy/tools/agent_tools.py` | ~1000 | `invoke_agent_headless()`, agent execution orchestration. |
| `code_puppy/tools/common.py` | ~1300 | Tool utilities, context management, result formatting. |
| `code_puppy/tools/ask_user_question/*.py` | ~800 | TUI forms for user input. Inherently Python-side. |
| `code_puppy/tools/display.py` | ~100 | Display helpers for tool results. |

---

## Deletable Modules (Ported to Elixir)

### Already Migrated ✅

| Category | Python Module | Elixir Replacement | Issue |
|----------|---------------|-------------------|-------|
| **File Operations** | `tools/file_operations.py` | `FileOps` (Elixir) | bd-7, bd-8 |
| **File List** | `utils/file_display.py` (partial) | `FileOps.Lister` | bd-9 |
| **Grep** | `utils/` grep functions | `FileOps.Grep` | — |
| **Scheduler** | `scheduler/*.py` | `Scheduler` (Oban) | — |
| **Repo Indexer** | `plugins/repo_compass/` | `Indexer.RepoCompass` | bd-9 |
| **Text Processing** | | | |
| ├─ Content Prep | Rust `content_prep.rs` | `Text.ContentPrep` | bd-34 |
| ├─ Path Classify | Rust `path_classify.rs` | `FileOps.PathClassifier` | bd-35 |
| ├─ Line Numbers | Rust `line_numbers.rs` | `Text.LineNumbers` | bd-36 |
| ├─ Unified Diff | Rust `unified_diff.rs` | `Text.Diff` | bd-37 |
| ├─ Fuzzy Match | Rust `fuzzy_match.rs` | `Text.FuzzyMatch` | bd-38 |
| ├─ Replace Engine | Rust `replace_engine.rs` | `Text.ReplaceEngine` | bd-39 |
| └─ Hashline | Rust `hashline.rs` | `HashlineNif` (Elixir NIF) | bd-88 |

### Scheduled for Migration 📋

| Category | Python Module | Elixir Destination | Issue |
|----------|---------------|-------------------|-------|
| **Message Core** | `code_puppy_core/` (Rust) | Pure Elixir | bd-43 |
| ├─ Token Estimation | `token_estimation.rs` | Elixir + ETS memoization | bd-44 |
| ├─ Message Pruning | `pruning.rs` | Elixir | bd-45 |
| ├─ Serialization | `serialization.rs` | Elixir (msgpack) | bd-47 |
| └─ Message Hashing | `message_hashing.rs` | Elixir (FxHash equiv) | bd-48 |
| **Parsing** | `turbo_parse/` + `turbo_parse_core/` | Decision pending | bd-51 |
| | (~13,100 lines) | | |

### Candidate for Deletion (Post-Elixir Migration)

| Category | Python Module | Rationale |
|----------|---------------|-----------|
| **API Layer** | `api/*.py` | May be replaced by Elixir Phoenix controllers |
| **MCP Python** | `mcp_/*.py` | Elixir has native MCP implementation |
| **Scheduler CLI** | `scheduler/cli.py` | Elixir provides CLI |
| **Legacy Tools** | `tools/file_modifications.py` | Functionality moved to Elixir Text ops |
| **Turbo Executor** | `plugins/turbo_executor/` | Orchestration moved to Elixir |
| **Rate Limiter** | `adaptive_rate_limiter.py` | Can migrate to Elixir |
| **Message Bus** | `messaging/bus.py` | Can use Elixir EventBus |
| **Concurrency** | `concurrency_limits.py` | Elixir has native supervision |

---

## Bridge Contract: Python ↔ Elixir

### Transport Layer

```python
# Python side (elixir_bridge/__init__.py)
call_method(method: str, params: dict, timeout: float = 30.0) -> dict
is_connected() -> bool
notify_elixir_event(event_type: str, payload: dict, run_id: str | None) -> None
```

### Communication Protocol

- **Format:** JSON-RPC 2.0
- **Framing:** Content-Length headers for stdio
- **Transport:** Stdio Port (bridge mode) or Unix socket (standalone)
- **Bidirectional:** Python can call Elixir; Elixir can call Python

### RPC Methods (Python → Elixir)

| Method | Purpose | Params | Returns |
|--------|---------|--------|---------|
| `file_list` | List directory | `directory`, `recursive`, `ignore_patterns` | `files[]` |
| `file_read` | Read file | `path`, `start_line`, `num_lines` | `content`, `truncated` |
| `file_read_batch` | Read multiple files | `paths[]` | `files[]` |
| `grep_search` | Search files | `pattern`, `directory`, `max_matches` | `matches[]` |
| `text_diff` | Unified diff | `old_content`, `new_content` | `diff` |
| `text_fuzzy_match` | Fuzzy search | `pattern`, `choices[]` | `matches[]` |
| `text_replace` | Replace in content | `content`, `old_str`, `new_str` | `content`, `replaced` |
| `parse_extract_symbols` | Symbol extraction | `code`, `language` | `symbols[]` |
| `parse_diagnostics` | Syntax errors | `code`, `language` | `diagnostics[]` |
| `scheduler.schedule` | Schedule job | `task_id`, `cron`, `command` | `job_id` |
| `concurrency.acquire` | Acquire slot | `type` | `status` |
| `concurrency.release` | Release slot | `type` | `status` |

### RPC Methods (Elixir → Python - Bridge Controller)

| Method | Purpose | Handler |
|--------|---------|---------|
| `run.start` | Start agent run | `_handle_run_start()` |
| `run.cancel` | Cancel active run | `_handle_run_cancel()` |
| `invoke_agent` | Run agent directly | `_handle_invoke_agent()` |
| `run_shell` | Execute shell command | `_handle_run_shell()` |
| `mcp.*` | MCP server management | `_handle_mcp_*()` |

### Error Handling

```python
# Bridge errors map to Python exceptions
ElixirTransportError        # Connection/transport issues
WireMethodError            # JSON-RPC protocol errors
TimeoutError               # Elixir timeout (fallback to Python)
RuntimeError               # Elixir returned error response
```

---

## Decision Criteria: Stay vs. Go

### Module Stays in Python If:

| Criterion | Examples |
|-----------|----------|
| **User interface** | TUI screens, REPL input, clipboard handling |
| **pydantic-ai integration** | Agent loop, tool binding, streaming |
| **CLI entry point** | Argument parsing, `--help`, `--version` |
| **Plugin callbacks** | Hook registration, custom commands |
| **Python-specific libs** | prompt_toolkit, Textual, Rich |
| **Bridge coordination** | Message marshaling, protocol handling |

### Module Migrates to Elixir If:

| Criterion | Examples |
|-----------|----------|
| **Performance-critical I/O** | File operations, directory traversal |
| **Background scheduling** | Cron jobs, task queue, Oban |
| **Text processing** | Diff, fuzzy match, EOL normalization |
| **State management** | Session registry, run tracking |
| **Parse operations** | Tree-sitter routing (via NIF) |
| **Concurrency control** | Rate limiting, semaphore coordination |

### Special Cases:

| Module | Decision | Rationale |
|--------|----------|-----------|
| `turbo_parse` (13K lines) | **Decision Pending** | Tree-sitter requires C bindings. Options: (1) Keep minimal Rust NIF, (2) Port to pure Elixir (major effort), (3) Alternative native bindings. Decision target: 2026-Q3 (bd-51). |
| `messaging/bus.py` | **Conditional** | MessageBus may stay as local event router even with Elixir EventBus for intra-Python events. Hybrid approach likely. |
| `plugins/*/register_callbacks.py` | **Stay** | Plugin contract is Python-first by design. Elixir plugins would need separate discovery mechanism. |

---

## Phase 6 End State: File Count Target

### Current State (2026-04-17)

- **Python files:** ~540
- **Total Python LOC:** ~150,000
- **Rust files:** ~50 (14,400 lines)
- **Elixir files:** ~121

### Phase 6 Target (2026-Q3)

| Layer | Files | LOC (est.) | Notes |
|-------|-------|-----------|-------|
| Python Thin Shell | ~80-100 | ~25,000 | CLI, TUI, agent loop, bridge |
| Elixir Runtime | ~150+ | ~40,000 | All services, NIFs |
| Rust (if kept) | 0 or minimal | 0 or ~2,000 | Tree-sitter NIF only if decision is "keep minimal" |

**Deletion Target:** ~400 Python files, ~14,000 Rust lines

---

## Migration Verification Checklist

Before declaring a module "migrated to Elixir":

- [ ] Elixir implementation passes all Python test cases
- [ ] Bridge RPC contract documented
- [ ] Python fallback removed (or disabled by default)
- [ ] Performance parity or improvement demonstrated
- [ ] Error handling matches or exceeds Python behavior
- [ ] Metrics/logging integration verified

---

## Appendix: Directory Structure (End State)

```
code_puppy/
├── __init__.py              # Package exports
├── __main__.py              # Entry point
├── main.py                  # Re-export
├── cli_runner.py            # CLI args with lazy imports
├── app_runner.py            # Application bootstrap
├── interactive_loop.py      # REPL implementation
├── prompt_runner.py         # Prompt execution
├── repl_session.py          # Session persistence
├── config.py                # Configuration system
├── tool_schema.py           # Tool definitions
├── callbacks.py             # Hook registry
│
├── agents/                  # pydantic-ai orchestration
│   ├── __init__.py
│   ├── base_agent.py        # Core agent loop (~1300 lines)
│   ├── agent_manager.py
│   ├── agent_state.py
│   ├── agent_prompt_mixin.py
│   ├── agent_code_puppy.py  # Default agent
│   └── pack/                # Sub-agents
│
├── command_line/            # CLI components
│   ├── command_handler.py   # Slash command routing
│   ├── prompt_toolkit_completion.py
│   ├── attachments.py
│   └── ...
│
├── tools/                   # Tool interface layer
│   ├── agent_tools.py       # Agent invocation
│   ├── common.py            # Tool utilities
│   ├── ask_user_question/   # TUI forms
│   └── display.py
│
├── tui/                     # Textual interface
│   ├── app.py               # Main TUI app
│   ├── screens/             # 20+ screen modules
│   ├── widgets/             # Custom components
│   └── theme.py
│
├── plugins/                 # Plugin system
│   ├── __init__.py          # Loader
│   ├── elixir_bridge/       # Bridge layer
│   │   ├── __init__.py
│   │   ├── bridge_controller.py
│   │   └── wire_protocol.py
│   └── */register_callbacks.py  # ~50 plugin hooks
│
├── elixir_transport.py      # Standalone transport
└── config_package/          # Pydantic config models
```

---

## Related Documents

| Document | Purpose |
|----------|---------|
| `MIGRATION_STATUS.md` | Current migration status and issues |
| `ARCHITECTURE.md` | Overall system architecture |
| `docs/protocol/BRIDGE_PROTOCOL_V1.md` | RPC contract specification |
| `docs/protocol/ELIXIR_STANDALONE_TRANSPORT.md` | Transport details |
| `docs/adr/ADR-001-elixir-python-worker-protocol.md` | Design rationale |

---

*Generated by Code Puppy 🐕 — bd-76*
