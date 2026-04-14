# Code Puppy Architecture

> 🐶 *A comprehensive technical overview of the Code Puppy application architecture*

---

## Table of Contents

1. [High-Level Overview](#1-high-level-overview)
2. [Detailed Component Diagram](#2-detailed-component-diagram)
3. [Data Flow Diagrams](#3-data-flow-diagrams)
4. [Protocol Details](#4-protocol-details)
5. [Deployment Modes](#5-deployment-modes)
6. [Technology Stack](#6-technology-stack)
7. [Plugin Architecture](#7-plugin-architecture)

---

## 1. High-Level Overview

Code Puppy is a **hybrid polyglot system** designed for maximum performance and flexibility. It combines three runtime environments that work together seamlessly:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           CODE PUPPY ARCHITECTURE                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌──────────────────────────────────────────────────────────────────────┐  │
│   │                        ELIXIR CONTROL PLANE                          │  │
│   │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                │  │
│   │  │   Phoenix    │  │   PubSub     │  │   Scheduler  │                │  │
│   │  │    API       │  │   (Events)   │  │   (Oban)     │                │  │
│   │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                │  │
│   │         │                 │                 │                         │  │
│   │  ┌──────▼─────────────────▼─────────────────▼───────┐                 │  │
│   │  │         OTP Supervision Tree (BEAM)              │                 │  │
│   │  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  │                 │  │
│   │  │  │PythonWorker│  │  Run       │  │  Request   │  │                 │  │
│   │  │  │   Port     │  │  Manager   │  │  Tracker   │  │                 │  │
│   │  │  └────────────┘  └────────────┘  └────────────┘  │                 │  │
│   │  └──────────────────────────────────────────────────┘                 │  │
│   └────────────────────────────────▲─────────────────────────────────────┘  │
│                                    │                                        │
│              JSON-RPC 2.0 + Content-Length Framing                        │
│                                    │                                        │
│   ┌────────────────────────────────▼─────────────────────────────────────┐  │
│   │                      PYTHON CLI RUNTIME                              │  │
│   │                                                                        │  │
│   │   ┌────────────┐   ┌────────────┐   ┌────────────┐   ┌────────────┐  │  │
│   │   │  AppRunner │   │   Agents   │   │   Tools    │   │Callbacks   │  │  │
│   │   │  (Entry)   │   │  (LLM)     │   │ (File/Sys) │   │(Hooks)     │  │  │
│   │   └─────┬──────┘   └─────┬──────┘   └─────┬──────┘   └─────┬──────┘  │  │
│   │         │                │                │                │         │  │
│   │   ┌─────▼────────────────▼────────────────▼────────────────▼─────┐    │  │
│   │   │              Message Bus / Event System                      │    │  │
│   │   └──────────────────────────────────────────────────────────┘    │  │
│   └────────────────────────────────▲─────────────────────────────────────┘  │
│                                    │                                        │
│              PyO3 / FFI Bridges    │                                        │
│                                    │                                        │
│   ┌────────────────────────────────▼─────────────────────────────────────┐  │
│   │                      RUST ACCELERATION LAYER                           │  │
│   │                                                                        │  │
│   │   ┌────────────────┐  ┌────────────────┐  ┌────────────────┐         │  │
│   │   │ code_puppy_core│  │   turbo_ops    │  │  turbo_parse   │         │  │
│   │   │  (Messages)    │  │  (File Ops)    │  │  (Parsing)     │         │  │
│   │   ├────────────────┤  ├────────────────┤  ├────────────────┤         │  │
│   │   │ • Pruning      │  │ • list_files   │  │ • Symbols      │         │  │
│   │   │ • Hashing      │  │ • grep         │  │ • Highlights   │         │  │
│   │   │ • Serialize    │  │ • read_files   │  │ • Folds        │         │  │
│   │   │ • Token Est    │  │ • Batch Exec   │  │ • Batch Parse  │         │  │
│   │   └────────────────┘  └────────────────┘  └────────────────┘         │  │
│   └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Runtime Responsibilities

| Runtime | Primary Role | Language | Process Model |
|---------|-------------|----------|---------------|
| **Python CLI** | Agent execution, tool orchestration, LLM interaction | Python 3.12+ | Asyncio + ThreadPool |
| **Elixir Control Plane** | Web API, real-time events, distributed supervision | Elixir/OTP | BEAM VM (Processes) |
| **Rust Acceleration** | CPU-intensive operations, parsing, file I/O | Rust | Native threads (Rayon) |

---

## 2. Detailed Component Diagram

### Python Runtime Components

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            PYTHON RUNTIME                                        │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │                         ENTRY LAYER                                         │ │
│  │                                                                             │ │
│  │   ┌───────────────┐      ┌───────────────┐      ┌───────────────┐        │ │
│  │   │   __main__.py │─────▶│   AppRunner   │─────▶│     main()    │        │ │
│  │   └───────────────┘      └───────────────┘      └───────┬───────┘        │ │
│  │                            • CLI args                   │                 │ │
│  │                            • Config load                ▼                 │ │
│  │                            • Signal handling    ┌───────────────┐        │ │
│  │                            • Renderer setup     │  interactive  │        │ │
│  │                                                   │     loop      │        │ │
│  └───────────────────────────────────────────────────└───────────────┘────────┘ │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │                        AGENT ECOSYSTEM                                      │ │
│  │                                                                             │ │
│  │   ┌─────────────────────────────────────────────────────────────────┐      │ │
│  │   │                    BaseAgent (ABC)                               │      │ │
│  │   │  • PydanticAI integration    • Message streaming      • Tools    │      │ │
│  │   │  • Tool execution          • History management         • MCP    │      │ │
│  │   └────────┬────────────────────────────────────────────┬───────────┘      │ │
│  │            │                                            │                   │ │
│  │   ┌────────▼──────────┐                    ┌──────────▼──────────┐        │ │
│  │   │   CodePuppyAgent  │                    │   PackLeaderAgent   │        │ │
│  │   │   (Default)       │                    │   (Orchestrator)    │        │ │
│  │   └────────┬──────────┘                    └──────────┬──────────┘        │ │
│  │            │                                            │                 │ │
│  │   ┌────────▼──────────┬────────────────┬───────────────▼──────────┐      │ │
│  │   │ Specialized Reviewers              │ Pack Agents               │      │ │
│  │   │ • CodeReviewer    • QAExpert       │ • Bloodhound  • Retriever│      │ │
│  │   │ • PythonReviewer  • SecurityAuditor│ • Shepherd    • Watchdog  │      │ │
│  │   │ • JS/TS Reviewers • GolangReviewer │ • Terrier                 │      │ │
│  │   └───────────────────┬────────────────┴──────────────────────────┘      │ │
│  │                       │                                                   │ │
│  │   ┌───────────────────▼──────────────────┐                               │ │
│  │   │        TurboExecutorAgent            │                               │ │
│  │   │   (Batch file operations)            │                               │ │
│  │   └──────────────────────────────────────┘                               │ │
│  │                                                                             │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │                         TOOL LAYER                                          │ │
│  │                                                                             │ │
│  │   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │ │
│  │   │   File Ops   │  │   Shell Cmd  │  │   Browser    │  │   Agents     │  │ │
│  │   │  (read/grep) │  │  (run_shell) │  │  (Puppeteer) │  │  (invoke)    │  │ │
│  │   ├──────────────┤  ├──────────────┤  ├──────────────┤  ├──────────────┤  │ │
│  │   │ • read_file  │  │ • cmd exec   │  │ • navigate   │  │ • subagent   │  │ │
│  │   │ • list_files │  │ • env vars   │  │ • interact   │  │ • parallel   │  │ │
│  │   │ • grep       │  │ • timeout    │  │ • screenshot │  │ • sessions   │  │ │
│  │   │ • edit_file  │  │ • PTY        │  │ • terminal   │  │ • streaming  │  │ │
│  │   └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘  │ │
│  │                                                                             │ │
│  │   ┌─────────────────────────────────────────────────────────────────┐    │ │
│  │   │                        MCP Manager                               │    │ │
│  │   │  • Server lifecycle    • Health monitoring    • Circuit breakers   │    │ │
│  │   │  • Tool registry       • Async stdio bridge  • Error isolation    │    │ │
│  │   └─────────────────────────────────────────────────────────────────┘    │ │
│  │                                                                             │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │                     TURBO ORCHESTRATOR                                      │ │
│  │                                                                             │ │
│  │      ┌───────────────┐     ┌───────────────┐     ┌───────────────┐       │ │
│  │      │     Plan      │────▶│  Validate     │────▶│  Execute      │       │ │
│  │      │   (Operations)│     │  (Security)   │     │  (Priority)   │       │ │
│  │      └───────────────┘     └───────────────┘     └───────┬───────┘       │ │
│  │                                                            │               │ │
│  │              ┌─────────────────────────────────────────────┼──────────┐    │ │
│  │              ▼                                             ▼          │    │ │
│  │      ┌───────────────┐     ┌───────────────┐     ┌───────────────┐  │    │ │
│  │      │   turbo_ops   │     │   turbo_parse │     │    Native     │  │    │ │
│  │      │   (Rust FFI)  │     │   (Rust FFI)  │     │   (Python)    │──┘    │ │
│  │      └───────────────┘     └───────────────┘     └───────────────┘       │ │
│  │                                                                             │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Elixir Control Plane Components

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           ELIXIR CONTROL PLANE                                   │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │                     PHOENIX / WEB LAYER                                       │ │
│  │                                                                             │ │
│  │   ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐│ │
│  │   │   HTTP Endpoint  │     │  WebSocket       │     │   REST API       ││ │
│  │   │   (Cowboy)       │     │  (Phoenix Ch.)   │     │   (Controllers)  ││ │
│  │   │                  │     │                  │     │                  ││ │
│  │   │ • /api/agents    │     │ • run:* topics   │     │ • /api/sessions  ││ │
│  │   │ • /api/sessions  │     │ • session:*      │     │ • /api/commands  ││ │
│  │   │ • /api/commands  │     │ • pubsub events  │     │ • /api/config    ││ │
│  │   └────────┬─────────┘     └────────┬─────────┘     └────────┬─────────┘│ │
│  │            │                        │                        │          │ │
│  └────────────┼────────────────────────┼────────────────────────┼──────────┘ │
│               │                        │                        │            │
│  ┌────────────▼────────────────────────▼────────────────────────▼────────────┐ │
│  │                         ROUTER / CHANNELS                                   │ │
│  │                                                                             │ │
│  │       ┌──────────────┐          ┌──────────────┐                        │ │
│  │       │  RunChannel  │          │ SessionChannel│                        │ │
│  │       │              │          │               │                        │ │
│  │       │• join/leave  │          │• auth handling│                        │ │
│  │       │• command     │          │• history      │                        │ │
│  │       │• streaming   │          │• presence     │                        │ │
│  │       └──────┬───────┘          └───────┬───────┘                        │ │
│  │              │                          │                                │ │
│  └──────────────┼──────────────────────────┼────────────────────────────────┘ │
│                 │                          │                                  │
│  ┌──────────────▼──────────────────────────▼────────────────────────────────┐ │
│  │                         OTP SUPERVISION TREE                              │ │
│  │                                                                             │ │
│  │  ┌─────────────────────────────────────────────────────────────────────┐   │ │
│  │  │                    Application Supervisor                             │   │ │
│  │  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────┐ │   │ │
│  │  │  │  PubSub     │  │ EventStore  │  │ RequestTrkr │  │ Run.Reg   │ │   │ │
│  │  │  │  (Phoenix)  │  │  (ETS)      │  │  (GenServer)│  │ (Registry)│ │   │ │
│  │  │  └─────────────┘  └─────────────┘  └─────────────┘  └───────────┘ │   │ │
│  │  │                                                                       │   │ │
│  │  │  ┌─────────────────────────────────────────────────────────────────┐   │   │ │
│  │  │  │              PythonWorker Supervisor (Dynamic)                │   │ │
│  │  │  │                                                                 │   │ │
│  │  │  │   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │   │ │
│  │  │  │   │ PythonWorker │    │ PythonWorker │    │ PythonWorker │      │   │ │
│  │  │  │   │   Port #1    │    │   Port #2    │    │   Port #3    │  ... │   │ │
│  │  │  │   │  (run: abc)  │    │  (run: xyz)  │    │  (run: 123)  │      │   │ │
│  │  │  │   └──────────────┘    └──────────────┘    └──────────────┘      │   │ │
│  │  │  └─────────────────────────────────────────────────────────────────┘   │   │ │
│  │  │                                                                       │   │ │
│  │  │  ┌─────────────────────────────────────────────────────────────────┐   │   │ │
│  │  │  │              MCP Server Supervisor (Dynamic)                    │   │ │
│  │  │  │                                                                 │   │ │
│  │  │  │   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │   │ │
│  │  │  │   │ MCP Server   │    │ MCP Server   │    │ MCP Server   │      │   │ │
│  │  │  │   │ Process      │    │ Process      │    │ Process      │ ...  │   │ │
│  │  │  │   └──────────────┘    └──────────────┘    └──────────────┘      │   │ │
│  │  │  └─────────────────────────────────────────────────────────────────┘   │   │ │
│  │  │                                                                       │   │ │
│  │  │  ┌─────────────────────────────────────────────────────────────────┐   │   │ │
│  │  │  │              Scheduler (Oban)                                   │   │ │
│  │  │  │                                                                 │   │ │
│  │  │  │   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │   │ │
│  │  │  │   │ ScheduledTask│    │ CronTrigger  │    │ Queue Worker │      │   │ │
│  │  │  │   │ (PostgreSQL) │    │ (Cron expr)  │    │ (Executor)   │      │   │ │
│  │  │  │   └──────────────┘    └──────────────┘    └──────────────┘      │   │ │
│  │  │  └─────────────────────────────────────────────────────────────────┘   │   │ │
│  │  └───────────────────────────────────────────────────────────────────────┘   │ │
│  └──────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                    │
└────────────────────────────────────────────────────────────────────────────────────┘
```

### Rust Acceleration Stack

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              RUST ACCELERATION LAYER                                   │
│                                                                                       │
│  ┌────────────────────────────────────────────────────────────────────────────────┐ │
│  │                         code_puppy_core (PyO3)                                    │ │
│  │  Message processing, token management, hashing, serialization                   │ │
│  │                                                                                   │ │
│  │  ┌────────────────────────────────────────────────────────────────────────────┐ │ │
│  │  │                           MessageBatchHandle                                │ │ │
│  │  │  Zero-copy wrapper for batched message operations                           │ │ │
│  │  │                                                                             │ │ │
│  │  │  process() ─────────▶ ProcessResult (token counts, hashes)                   │ │ │
│  │  │  prune_and_filter() ─▶ PruneResult (interrupted tool removal)                 │ │ │
│  │  │  truncation_indices() ▶ Vec<usize> (protected token calc)                    │ │ │
│  │  │  split_for_summarization() ▶ SplitResult (binary partition)                  │ │ │
│  │  └────────────────────────────────────────────────────────────────────────────┘ │ │
│  │                                                                                   │ │
│  │  Features:                                                                        │ │
│  │   • Message serialization for pydantic-ai objects                                 │ │
│  │   • Incremental session serialization                                             │ │
│  │   • Token estimation (GPT-4, Claude, Gemini)                                    │ │
│  │   • Hashline computation (line-level integrity)                                 │ │
│  │   • SHA-based message hashing                                                     │ │ │
│  └──────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                       │
│  ┌────────────────────────────────────────────────────────────────────────────────┐ │
│  │                            turbo_ops (PyO3)                                       │ │
│  │  Batch file operations with Rayon parallelization                                 │ │
│  │                                                                                   │ │
│  │   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐                 │ │
│  │   │   list_files     │  │      grep        │  │   read_files     │                 │ │
│  │   │                  │  │                  │  │                  │                 │ │
│  │   │ • Recursive dir  │  │ • Regex search   │  │ • Multi-file     │                 │ │
│  │   │ • Metadata       │  │ • ripgrep-style  │  │ • Token count    │                 │ │
│  │   │ • Filtering      │  │ • Cross-file     │  │ • Range support  │                 │ │
│  │   └──────────────────┘  └──────────────────┘  └──────────────────┘                 │ │
│  │                                                                                   │ │
│  │   Batch Execution API:                                                            │ │
│  │   turbo_ops.batch(operations)          → Parallel with dependencies               │ │
│  │   turbo_ops.batch_grouped(operations)  → Priority-based grouping                  │ │
│  │                                                                                   │ │
│  │   Features:                                                                       │ │
│  │    • Rayon-based parallelism (CPU cores)                                         │ │
│  │    • Safety filtering (respects .gitignore)                                      │ │
│  │    • Result aggregation with timing                                                │ │
│  └──────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                       │
│  ┌────────────────────────────────────────────────────────────────────────────────┐ │
│  │                           turbo_parse (PyO3)                                      │ │
│  │  High-performance parsing with tree-sitter                                       │ │
│  │                                                                                   │ │
│  │   Language Support:                                                               │ │
│  │   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ │ │
│  │   │ Python   │ │ Rust     │ │ JavaScript│ │ TypeScript│ │ TSX      │ │ Elixir   │ │ │
│  │   │   ⭐ T1   │ │   ⭐ T1   │ │   ⭐ T1    │ │   ⭐ T1    │ │   🟡 T2   │ │ 🟠 T3    │ │ │
│  │   └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └─────────┘ │ │
│  │                                                                                   │ │
│  │   Capabilities:                                                                   │ │
│  │   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐                 │ │
│  │   │ Symbol Extraction│  │ Syntax Highlight │  │ Code Folding     │                 │ │
│  │   │                  │  │                  │  │                  │                 │ │
│  │   │ • Functions      │  │ • Tree-sitter    │  │ • Function       │                 │ │
│  │   │ • Classes        │  │   queries          │  │ • Class          │                 │ │
│  │   │ • Methods        │  │ • Helix Editor     │  │ • Conditional    │                 │ │
│  │   │ • Imports        │  │   capture names    │  │ • Loop           │                 │ │
│  │   │ • Variables      │  │ • Byte-accurate  │  │ • Block          │                 │ │
│  │   └──────────────────┘  └──────────────────┘  └──────────────────┘                 │ │
│  │                                                                                   │ │
│  │   Additional:                                                                     │ │
│  │   • Diagnostics (syntax errors with positions)                                   │ │
│  │   • Incremental parsing (fast re-parse for edits)                                  │ │
│  │   • LRU cache for parsed trees                                                    │ │
│  │   • Batch parallel parsing                                                        │ │
│  └──────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                       │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Flow Diagrams

### CLI Mode Flow (Standalone)

```
┌──────────┐     ┌──────────────┐     ┌─────────────────┐     ┌──────────────┐
│   User   │     │  code-puppy  │     │  Agent Runtime  │     │   LLM API    │
│          │     │   (Python)   │     │   (asyncio)     │     │  (OpenAI/    │
│          │     │              │     │                 │     │  Anthropic)  │
└────┬─────┘     └──────┬───────┘     └────────┬────────┘     └──────┬───────┘
     │                  │                      │                     │
     │  Type prompt     │                      │                     │
     │─────────────────▶│                      │                     │
     │                  │                      │                     │
     │                  │  Parse & route       │                     │
     │                  │─────────────────────▶│                     │
     │                  │                      │                     │
     │                  │                      │  Build messages     │
     │                  │                      │  + tool schemas       │
     │                  │                      │─────────────────────▶│
     │                  │                      │                     │
     │                  │                      │◀────────────────────│
     │                  │                      │   Streaming response│
     │                  │                      │                     │
     │                  │◀────────────────────│   Events (text/     │
     │                  │   Render events      │   tool_calls)       │
     │                  │                      │                     │
     │◀─────────────────│   Display output     │                     │
     │   See response   │   (Rich console)     │                     │
     │                  │                      │                     │
     │  [Tool needed]   │                      │                     │
     │  ─ ─ ─ ─ ─ ─ ─ ─ │                      │                     │
     │                  │  ┌──────────────┐    │                     │
     │                  │  │ Tool Executor│    │                     │
     │                  │  │              │    │                     │
     │                  │  │• read_file   │◀───│                     │
     │                  │  │• list_files  │    │                     │
     │                  │  │• grep        │────▶│                     │
     │                  │  │• run_shell   │    │  Return results     │
     │                  │  └──────────────┘    │─────────────────────▶
     │                  │                      │
     │◀─────────────────│   Tool output shown  │
     │   View results   │   in conversation    │
     │                  │                      │
```

### Bridge Mode Flow (Elixir Orchestration)

```
┌─────────────┐    ┌───────────────┐    ┌───────────────────┐    ┌───────────────┐
│   Client    │    │   Phoenix     │    │ PythonWorker.Port │    │   Python      │
│  (Web/WS)   │    │   (Elixir)    │    │   (OTP Process)   │    │   Worker      │
└──────┬──────┘    └───────┬───────┘    └─────────┬─────────┘    └───────┬───────┘
       │                   │                      │                      │
       │  POST /api/runs   │                      │                      │
       │  {agent, prompt}  │                      │                      │
       │──────────────────▶│                      │                      │
       │                   │                      │                      │
       │                   │  Spawn Port         │                      │
       │                   │  with run_id        │                      │
       │                   │─────────────────────▶│                      │
       │                   │                      │                      │
       │                   │                      │  Launch python      │
       │                   │                      │  code_puppy_main.py   │
       │                   │                      │  --bridge-mode       │
       │                   │                      │─────────────────────▶
       │                   │                      │                      │
       │                   │◀─────────────────────│  Port initialized     │
       │                   │  Port ready          │  send: initialize     │
       │                   │                      │                      │
       │                   │─────────────────────▶│                      │
       │                   │  JSON-RPC: run.start │                      │
       │                   │  Content-Length      │                      │
       │                   │  framing             │                      │
       │                   │                      │  Relay to agent     │
       │                   │                      │  runtime            │
       │                   │                      │─────────────────────▶
       │                   │                      │                      │
       │◀──────────────────│  WebSocket upgrade   │                      │
       │  WS: /socket    │  (optional)          │                      │
       │  join: run:*    │                      │                      │
       │                   │                      │◀─────────────────────│
       │                   │                      │  run.status         │
       │                   │                      │  run.event          │
       │                   │                      │  run.completed      │
       │                   │                      │  run.failed         │
       │                   │                      │  (notifications)    │
       │                   │                      │                      │
       │                   │◀─────────────────────│                      │
       │                   │  PubSub.broadcast    │                      │
       │                   │  run:run_id          │                      │
       │                   │                      │                      │
       │◀──────────────────│  WS events           │                      │
       │  {type, data}   │  {type, data}        │                      │
       │  streamed        │                      │                      │
       │                   │                      │                      │
       │  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  │
       │                   │                      │     ERROR PATH        │
       │                   │                      │                      │
       │                   │  ◀─── Port crash ────│                      │
       │                   │                      │                      │
       │                   │  Registry.lookup    │                      │
       │                   │  Run.State.set_status│  (failed)            │
       │                   │  PubSub: run_failed   │                      │
       │◀──────────────────│                      │                      │
       │  Error event     │                      │                      │
```

### WebSocket Event Flow

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                         WEBSOCKET EVENT FLOW                                   │
│                                                                                │
│   ┌─────────────┐        ┌─────────────┐        ┌─────────────┐              │
│   │   Browser   │◀──────▶│   Phoenix   │◀──────▶│   PubSub    │              │
│   │    Client   │   WS   │   Channel   │   IPC   │   (ETS)     │              │
│   └─────────────┘        └──────┬──────┘        └──────┬──────┘              │
│                                 │                      │                      │
│                                 ▼                      ▼                      │
│                          ┌─────────────┐        ┌─────────────┐             │
│                          │ RunChannel  │◀──────▶│ EventStore  │             │
│                          │             │        │   (ETS)     │             │
│                          └─────────────┘        └─────────────┘             │
│                                                                                │
│   Event Types:                                                                 │
│   ═══════════                                                                  │
│                                                                                │
│   ┌────────────────┬─────────────────────────────────────────────────────────┐ │
│   │ Type           │ Payload Example                                         │ │
│   ├────────────────┼─────────────────────────────────────────────────────────┤ │
│   │ text           │ {content: "Hello...", chunk: false, run_id}             │ │
│   │ tool_result    │ {tool_name, result, tool_call_id, run_id}              │ │
│   │ status         │ {status: "running|paused|completed", run_id}            │ │
│   │ prompt         │ {prompt_id, question, options, run_id}                  │ │
│   │ completed      │ {result, token_usage, duration_ms, run_id}             │ │
│   │ failed         │ {error, stack_trace, run_id}                           │ │
│   └────────────────┴─────────────────────────────────────────────────────────┘ │
│                                                                                │
│   Subscription Pattern:                                                          │
│   ═══════════════════                                                          │
│                                                                                │
│   Client connects:                                                             │
│   → join("run:" <> run_id)                                                    │
│   → Phoenix.Tracker marks presence                                              │
│   → Client receives all events for that run                                     │
│                                                                                │
│   Server publishes:                                                            │
│   → Phoenix.PubSub.broadcast("run:" <> run_id, {:run_event, event})           │
│   → All subscribed clients receive event                                        │
│   → EventStore persists for replay                                              │
│                                                                                │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Protocol Details

### JSON-RPC 2.0 with Content-Length Framing

Code Puppy uses **JSON-RPC 2.0** over stdio with **Content-Length** HTTP-style framing for robust communication between Elixir and Python.

#### Framing Format

```
Content-Length: <bytes>\r\n
\r\n
<json_rpc_message>
```

#### Example Message Exchange

**Elixir → Python: Initialize**
```http
Content-Length: 87\r\n\r\n
{"jsonrpc":"2.0","method":"initialize","params":{"run_id":"run-abc123"}}
```

**Python → Elixir: Notification (Event)**
```http
Content-Length: 156\r\n\r\n
{
  "jsonrpc": "2.0",
  "method": "run.event",
  "params": {
    "type": "text",
    "run_id": "run-abc123",
    "session_id": "session-xyz789",
    "content": "Analyzing code structure...",
    "timestamp": 1713123456789
  }
}
```

**Elixir → Python: Request/Response**
```http
# Request:
Content-Length: 134\r\n\r\n
{"jsonrpc":"2.0","id":"req-1","method":"worker.ping","params":{"timestamp":1713123456789}}

# Response:
Content-Length: 56\r\n\r\n
{"jsonrpc":"2.0","id":"req-1","result":{"status":"ok","pong":true}}
```

### Message Types

| Type | Direction | Purpose |
|------|-----------|---------|
| **Request** | Elixir → Python | Execute command, expect response |
| **Response** | Python → Elixir | Return result for a request |
| **Notification** | Bidirectional | Fire-and-forget event |

### Protocol Methods

#### Elixir → Python (Control)

| Method | Params | Description |
|--------|--------|-------------|
| `initialize` | `{run_id, elixir_pid}` | Worker setup |
| `run.start` | `{agent_name, prompt, session_id}` | Start execution |
| `run.cancel` | `{run_id}` | Soft cancel request |
| `run.provide_response` | `{prompt_id, response}` | User input delivery |
| `worker.ping` | `{}` | Health check |
| `worker.shutdown` | `{code}` | Graceful exit |

#### Python → Elixir (Events)

| Method | Params | Description |
|--------|--------|-------------|
| `run.status` | `{status, run_id, session_id}` | State transition |
| `run.event` | `{type, payload, timestamp, ...}` | Streaming event |
| `run.text` | `{content, chunk, run_id}` | Text output |
| `run.tool_result` | `{tool_name, result, ...}` | Tool execution |
| `run.prompt` | `{prompt_id, question, ...}` | User input request |
| `run.completed` | `{result, token_usage, ...}` | Success completion |
| `run.failed` | `{error, stack_trace, ...}` | Error completion |

### JSON-RPC Error Codes

| Code | Meaning | When Used |
|------|---------|-----------|
| `-32700` | Parse Error | Invalid JSON received |
| `-32600` | Invalid Request | Not a valid JSON-RPC message |
| `-32601` | Method Not Found | Unknown method called |
| `-32602` | Invalid Params | Wrong parameters for method |
| `-32603` | Internal Error | Python exception |
| `-32000` to `-32099` | Server Error | Application-specific errors |

---

## 5. Deployment Modes

| Mode | Entry Point | When to Use |
|------|-------------|-------------|
| **CLI Interactive** | `code-puppy` or `python -m code_puppy` | Local development, day-to-day coding |
| **CLI Prompt-only** | `code-puppy -p "create a React component"` | CI/CD, automation, scripting |
| **Bridge Mode** | `--bridge-mode` or `CODE_PUPPY_BRIDGE=1` | Elixir orchestration, distributed runs |
| **HTTP API** | `elixir/CodePuppyControlWeb` | External integrations, web dashboards |
| **WebSocket** | `ws://host/socket` | Real-time UIs, streaming responses |
| **TUI Mode** | `CODE_PUPPY_TUI=1` | Rich terminal interface (Textual) |

### Mode Selection Logic

```
Entry Point:
┌─────────────────────────────────────────────────────────┐
│                    AppRunner.run()                      │
└──────────────────┬──────────────────────────────────────┘
                   │
         ┌─────────┴─────────┐
         │
    args.prompt?  ◀── yes ──▶  prompt_runner.execute_single()
         │ no
         ▼
    is_tui_enabled()?  ◀── yes ──▶  textual_interactive_mode()
         │ no
         ▼
    CODE_PUPPY_BRIDGE?  ◀── yes ──▶  elixir_bridge.run()
         │ no
         ▼
         interactive_mode()  ◀── default CLI loop
```

---

## 6. Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Core** | Python 3.12+ | Main runtime (asyncio) |
| **LLM Framework** | PydanticAI | Type-safe agent/model integration |
| **HTTP Client** | httpx | Async HTTP for LLM APIs |
| **CLI Parsing** | argparse | Command-line interface |
| **TUI** | Textual | Rich terminal interface |
| **Console** | Rich | Pretty printing, progress bars |
| **Config** | TOML + configparser | Settings persistence |
| **Web (Elixir)** | Phoenix + Cowboy | HTTP/WebSocket server |
| **PubSub (Elixir)** | Phoenix.PubSub | Event broadcasting |
| **Database (Elixir)** | PostgreSQL + Ecto | Scheduled tasks |
| **Jobs (Elixir)** | Oban | Background job processing |
| **Rust Core** | PyO3 | Python bindings |
| **Rust Parsing** | tree-sitter | Syntax analysis |
| **Rust Parallelism** | Rayon | Data parallelism |
| **Process Runner** | Zig | MCP server management |

### Python Dependencies

```toml
[project.dependencies]
# Core
pydantic = ">=2.10"
pydantic-ai = ">=0.0.24"
httpx = ">=0.27"
rich = ">=13.9"
textual = ">=0.85"

# File operations
gitignore-parser = ">=0.1"
pathspec = ">=0.12"

# Utilities
platformdirs = ">=4.3"
psutil = ">=6.1"
pyfiglet = ">=1.0"

# Optional
browser-use = {optional = true}
```

---

## 7. Plugin Architecture

Code Puppy uses a **callback-based plugin system** for extensibility.

```
┌─────────────────────────────────────────────────────────────────┐
│                    PLUGIN ARCHITECTURE                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │                   callbacks.py                          │  │
│   │                                                         │  │
│   │   register_callback("startup", my_startup_func)         │  │
│   │   register_callback("shutdown", my_shutdown_func)       │  │
│   │   register_callback("load_prompt", my_prompt_addon)     │  │
│   │   ...                                                   │  │
│   └─────────────────────────────────────────────────────────┘  │
│                              │                                  │
│          ┌───────────────────┼───────────────────┐              │
│          ▼                   ▼                   ▼              │
│   ┌────────────┐     ┌────────────┐     ┌────────────┐        │
│   │ Builtin    │     │  Built-in  │     │   User     │        │
│   │ Plugins    │     │  Plugins    │     │  Plugins   │        │
│   │            │     │            │     │            │        │
│   │• fast_puppy│     │• file_ments│     │~/.code_puppy│        │
│   │• turbo_exec│     │• agent_skills│    │  /plugins/  │        │
│   │• adv_plan │     │• cost_est  │     │            │        │
│   │• pack_par │     │• git_auto  │     │• register_  │        │
│   │• turbo_par│     │• shell_safe│     │  callbacks │        │
│   │• elixir_br│     │• ...       │     │  .py       │        │
│   └────────────┘     └────────────┘     └────────────┘        │
│                                                                 │
│   Discovery:                                                    │
│   ──────────                                                    │
│   1. Scan code_puppy/plugins/*/register_callbacks.py            │
│   2. Scan ~/.code_puppy/plugins/*/register_callbacks.py         │
│   3. Import and execute registration functions                  │
│   4. Store callbacks in phase-indexed registry                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Common Hook Points

| Hook | When | Use Case |
|------|------|----------|
| `startup` | App boot | Initialize resources |
| `shutdown` | Graceful exit | Cleanup, save state |
| `load_prompt` | Prompt assembly | Add custom instructions |
| `agent_run_start` | Before agent executes | Setup tracing |
| `agent_run_end` | After agent completes | Log results |
| `run_shell_command` | Before shell exec | Safety validation |
| `file_permission` | Before file op | Access control |
| `stream_event` | Response streaming | UI updates |

---

## Architecture Principles

1. **Fail Graceful**: Rust operations fall back to Python; Python falls back to safe defaults
2. **Zero-Copy Where Possible**: MessageBatchHandle avoids repeated serialization
3. **Event-Driven**: PubSub pattern enables loose coupling between components
4. **Type Safety**: Pydantic models at boundaries; Rust for performance-critical paths
5. **Plugin-First**: New features should prefer plugin architecture over core modification

---

*Document generated for Code Puppy - woof! 🐕*
