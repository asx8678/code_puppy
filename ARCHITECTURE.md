# 🐕 Code Puppy Architecture

## High-Level System Architecture

> **Phase 6 Complete (2026-04-17)**: Code Puppy has achieved the **"no Rust, thin Python"** end state.
> 
> - **Python layer**: TUI (Textual), CLI interface, pydantic-ai agent loop
> - **Elixir layer**: ALL runtime operations (file ops, parsing, job scheduling, message processing)
> - **Rust layer**: **COMPLETELY ELIMINATED** (bd-167, bd-43 migration epic)
>
> Architecture: Thin Python shell → Elixir backend only (zero Rust)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              USER INTERFACE LAYER                                │
├─────────────┬─────────────┬─────────────────┬─────────────────────────────────┤
│   CLI       │   API       │   Web Terminal  │   Plugin Commands               │
│  (TTY)      │ (FastAPI)   │   (WebSocket)   │   (/slash)                      │
└──────┬──────┴──────┬──────┴────────┬────────┴───────────────┬─────────────────┘
       │             │               │                        │
       └─────────────┴───────────────┴────────────────────────┘
                              │
                    ┌─────────┴──────────┐
                    │   APP RUNNER       │
                    │  (Entry Point)     │
                    └─────────┬──────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
┌────────▼────────┐  ┌────────▼────────┐  ┌────────▼────────┐
│ CONFIG SYSTEM   │  │ CALLBACK SYSTEM │  │  PLUGIN LOADER  │
│ (puppy.cfg)     │  │  (Lifecycle)    │  │ (Auto-discover) │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                    │
         └────────────────────┴────────────────────┘
                              │
                    ┌─────────┴──────────┐
                    │   AGENT MANAGER      │
                    │  (Agent Registry)    │
                    └─────────┬──────────────┘
                              │
    ┌─────────────────────────┼─────────────────────────┐
    │                         │                         │
┌───▼────┐           ┌────────▼────────┐      ┌─────────▼────────┐
│ BASE   │           │ AGENT RUNTIME   │      │   PACK LEADER    │
│ AGENT  │◄─────────│     STATE       │      │(Parallelism Ctrl)│
│        │           │ (History/Ctx)   │      │   MAX=8 agents   │
└───┬────┘           └─────────────────┘      └──────────────────┘
    │
    │  ┌────────────────────────────────────────────────────────────┐
    │  │                    AGENT TYPES                              │
    │  ├─────────────┬─────────────┬─────────────┬───────────────────┤
    │  │ CodePuppy   │  CodeReviewer│ Security    │ PythonPro        │
    │  │  (Default)  │   (PR rev)   │  Auditor    │  (Code gen)      │
    │  ├─────────────┼─────────────┼─────────────┼───────────────────┤
    │  │  TerminalQA │  TurboExec   │  CodeScout  │   QA Kitten      │
    │  │  (Q&A)      │  (Batch ops) │ (Explorer)  │  (Test help)     │
    │  └─────────────┴─────────────┴─────────────┴───────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                           PYDANTIC AI LAYER                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │Model Factory│  │Rate Limiter │  │Token Ledger │  │  Model Switching    │  │
│  │ (create)    │  │(Adaptive)   │  │ (track)     │  │  (fallback chain)   │  │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └─────────────────────┘  │
│         │                │                │                                  │
│         └────────────────┴────────────────┘                                  │
│                          │                                                   │
│         ┌────────────────┴────────────────┐                                  │
│         ▼                                 ▼                                  │
│  ┌──────────────┐              ┌─────────────────┐                          │
│  │   Claude     │              │     OpenAI      │                          │
│  │  (Anthropic) │              │  (GPT/o series) │                          │
│  └──────────────┘              └─────────────────┘                          │
└──────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                            TOOL LAYER                                        │
├────────────────┬────────────────┬────────────────┬───────────────────────────┤
│  FILE OPS      │  EXECUTION     │  AGENT OPS     │   USER INTERACTION        │
├────────────────┼────────────────┼────────────────┼───────────────────────────┤
│ • list_files   │ • run_shell    │ • invoke_agent │  • ask_user_question      │
│ • read_file    │   _command     │ • list_agents  │    (TUI forms)            │
│ • grep         │ • command      │                │                           │
│ • replace_in_  │   _runner      │                │                           │
│   file         │                │                │                           │
│ • create_file  │                │                │                           │
│ • delete_*     │                │                │                           │
└────────┬───────┴────────┬───────┴────────┬───────┴───────────────┬───────────┘
         │              │                │                       │
         └──────────────┴────────────────┴───────────────────────┘
                              │
                    ┌─────────┴────────────────────────┐
                    │   ELIXIR RUNTIME BACKEND         │
                    │   (Primary - All Operations)     │
                    └─────────┬────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
┌────────▼────────┐  ┌────────▼────────┐  ┌────────▼────────┐
│  FILE SERVICE   │  │  PARSE SERVICE  │  │  SCHEDULER      │
│ (list/read/grep)│  │ (Tree-sitter)   │  │ (Job Queue)     │
│                 │  │                 │  │                 │
└─────────────────┘  └─────────────────┘  └─────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                              MCP LAYER                                         │
│                    (Model Context Protocol)                                      │
├────────────────────────┬────────────────────────┬────────────────────────────┤
│    MCP MANAGER         │      CIRCUIT BREAKER   │      SECURITY LAYER        │
│  (Server lifecycle)    │    (Fault isolation)   │    (Command whitelist)     │
│                        │                        │    (Injection detect)      │
└────────────────────────┴────────────────────────┴────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                           PLUGIN ECOSYSTEM                                     │
├────────────────────┬────────────────────┬────────────────────────────────────┤
│   CORE PLUGINS     │   AUTH PLUGINS     │     FEATURE PLUGINS                  │
├────────────────────┼────────────────────┼────────────────────────────────────┤
│ • fast_puppy       │ • claude_code_oauth│ • agent_skills (Skill install)       │
│   (Elixir backend) │ • chatgpt_oauth    │ • turbo_executor (Batch ops)         │
│ • file_mentions    │                    │ • shell_safety (Cmd filter)          │
│   (@file support)  │                    │ • agent_trace (Analytics)            │
│ • repo_compass     │                    │ • agent_trace (Analytics)            │
│   (Repo mapping)   │                    │ • agent_memory (Persistence)         │
│ • pack_parallelism │                    │ • code_explorer (Nav)                │
│   (Limits)         │                    │ • loop_detection                     │
└────────────────────┴────────────────────┴────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                            STORAGE LAYER                                       │
├────────────────────┬────────────────────┬────────────────────────────────────┤
│   SESSION STORAGE  │   PERSISTENCE      │      STATE MANAGEMENT                │
│ (terminal_sessions)│  (checkpoints)   │    (DBOS / SQLite)                   │
└────────────────────┴────────────────────┴────────────────────────────────────┘
```

## Data Flow Example: Agent Execution

```
User Input
    │
    ▼
┌──────────────┐
│  AppRunner   │ ──► Parses args, loads config
└──────┬───────┘
       │
       ▼
┌──────────────┐
│AgentManager  │ ──► Discovers/selects agent
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  BaseAgent   │ ──► Loads system prompt
│  + State     │ ──► Loads message history
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ PydanticAI   │ ──► Makes model call
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ ModelOutput  │ ──► Text or tool calls
└──────┬───────┘
       │
       ├───────────────────────┐
       │ (if text)             │ (if tool call)
       ▼                       ▼
┌──────────┐           ┌──────────────┐
│ Response │           │ ToolRegistry │
│ to User  │           └──────┬───────┘
└──────────┘                  │
                              ├─────────────┬─────────────┐
                              │             │             │
                              ▼             ▼             ▼
                        ┌─────────┐   ┌──────────┐  ┌──────────┐
                        │File Ops │   │ Subagent │  │  Shell   │
                        │(Native) │   │(Pack Ldr)│  │(Safety)  │
                        └────┬────┘   └────┬─────┘  └────┬─────┘
                             │             │             │
                             └─────────────┴─────────────┘
                                           │
                                           ▼
                                    ┌──────────────┐
                                    │ Tool Results │
                                    └──────┬───────┘
                                           │
                                           ▼
                                    (Back to PydanticAI)
```

## Key Architectural Decisions

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| **Plugin System** | Hook-based callbacks | Hot-swappable, zero core modification |
| **Native Accel** | Pure Elixir runtime (bd-167 complete) | Thin Python shell + full Elixir backend (zero Rust) |
| **Agent Concurrency** | Pack Leader with MAX=8 | Prevents resource exhaustion |
| **Model Routing** | Adaptive rate limiting | Protects against rate limit storms |
| **MCP Security** | Circuit breaker + whitelist | Defense in depth for external tools |
| **State Mgmt** | AgentRuntimeState isolation | Thread-safe, testable, resettable |

## Class Hierarchy (Simplified)

```
BaseAgent (ABC)
├── AgentPromptMixin (mixin)
├── AgentRuntimeState (composition)
│
├── CodePuppyAgent
├── CodeReviewerAgent
├── SecurityAuditorAgent
├── PythonProgrammerAgent
├── TerminalQAAgent
├── TurboExecutorAgent
├── CodeScoutAgent
├── QAKittenAgent
├── HeliosAgent
├── CreatorAgent
│
└── Pack sub-agents
    ├── Bloodhound (search)
    ├── Retriever (file find)
    ├── Shepherd (delegation)
    ├── Terrier (grep)
    └── Watchdog (monitoring)
```

## Hook Phases (Callback System)

```
startup ──► agent_run_start ──► pre_tool_call ──► [TOOL EXEC] ──► post_tool_call
                                                            │
                        invoke_agent ◄────────────────────────┘
                            │
                            ▼
                    subagent_stream_handler
                            │
                    agent_run_end ──► shutdown
```

---

*Generated by Code Puppy 🐕 on a rainy weekend*
