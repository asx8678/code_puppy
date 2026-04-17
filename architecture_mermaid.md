# Code Puppy Architecture (Mermaid)

> **Updated:** 2026-04-18 — Phase 4: Elixir-first native acceleration
> **Stack:** Python 3.14 (TUI/CLI/agent loop) + Elixir/OTP (ALL backend operations)
> **Architecture:** Fast Puppy runtime backend selector with Elixir-first routing

---

## 1. System Architecture Overview

```mermaid
flowchart TB
    subgraph UI["User Interface Layer"]
        CLI["CLI (TTY/PTY)"]
        API["FastAPI HTTP/WS"]
        TUI["Textual TUI"]
        Slash["/slash Commands"]
    end

    subgraph Core["Core Engine"]
        App["AppRunner"]
        Config["Config System"]
        Callbacks["Callback Engine (30+ hooks)"]
        PluginLoader["Plugin Loader (auto-discovery)"]
        MsgBus["MessageBus (bidirectional)"]
    end

    subgraph Agents["Agent Layer (28 agents)"]
        AgMgr["AgentManager"]
        Base["BaseAgent (ABC)"]
        State["AgentRuntimeState"]

        subgraph Pack["Pack Leader (MAX=8)"]
            PL["PackLeader"]
            BH["Bloodhound - issue tracking"]
            TR["Terrier - worktree mgmt"]
            SH["Shepherd - code review"]
            WD["Watchdog - QA/testing"]
            RT["Retriever - merge specialist"]
        end

        subgraph Specialists["Specialist Agents"]
            CP["CodePuppy"]
            CS["CodeScout"]
            CR["CodeReviewer"]
            SA["SecurityAuditor"]
            PP["PythonProgrammer"]
            ED["ElixirDev"]
            TQA["TerminalQA"]
            TE["TurboExecutor"]
            HE["Helios"]
            PA["PlanningAgent"]
        end
    end

    subgraph AI["AI Integration"]
        PydanticAI["PydanticAI"]
        ModelFact["Model Factory"]
        RateLimiter["AdaptiveRateLimiter"]
        TokenLedger["TokenLedger"]
        Providers["Claude / OpenAI / Gemini / Ollama"]
    end

    subgraph Tools["Tool Layer (18+ tools)"]
        FileOps["File Operations"]
        ShellCmd["Shell Command Runner"]
        InvokeAgent["invoke_agent"]
        AskUser["Ask User (TUI)"]
        Browser["Browser Automation"]
        MCPTools["MCP Tool Proxy"]
    end

    subgraph Native["Elixir Runtime Backend"]
        NativeBE["NativeBackend (Elixir-first router)"]
        subgraph ElixirLayer["Elixir Control Plane"]
            ElixirCP["OTP Application"]
            FileSvc["File Service (list/grep/read)"]
            ParseSvc["Parse Service (Tree-sitter NIFs)"]
            SchedSvc["Scheduler (Oban jobs)"]
        end
    end

    subgraph MCP["MCP Layer"]
        MCPMgr["MCP Manager"]
        MCPServer["MCP Server (GenServer)"]
        Circuit["Circuit Breaker"]
    end

    subgraph Storage["Storage"]
        Sessions["Session Storage"]
        History["Message History"]
        Oban["Oban (Job Queue)"]
    end

    UI --> App
    App --> Config & Callbacks & PluginLoader & MsgBus
    PluginLoader --> Callbacks
    App --> AgMgr
    AgMgr --> Base
    Base --> State & PydanticAI & MsgBus
    PL --> BH & TR & SH & WD & RT
    PydanticAI --> ModelFact & RateLimiter
    Base --> TokenLedger
    ModelFact --> Providers
    Base --> FileOps & ShellCmd & InvokeAgent & AskUser & Browser
    FileOps --> MCPTools & NativeBE
    NativeBE --> ElixirCP
    ElixirCP --> FileSvc & ParseSvc & SchedSvc
    InvokeAgent --> MCPMgr
    MCPMgr --> MCPServer & Circuit
    State --> Sessions & History
    ElixirCP --> Oban
```


---

## 2. Class Hierarchy — Agent System

```mermaid
classDiagram
    class AgentIdentityMixin {
        <<mixin>>
        +name: str
        +description: str
    }
    class AgentPromptMixin {
        <<mixin>>
        +get_system_prompt() str
        +get_full_system_prompt() str
    }
    class BaseAgent {
        <<abstract>>
        +model: str
        +message_history: list
        +run(task, history)
    }
    class AgentRuntimeState {
        +message_history: list
        +token_counts: dict
        +session_id: str
    }
    class AgentManager {
        +agent_registry: dict
        +get_agent(name)
        +discover_agents()
    }
    class PackLeaderAgent { +max_parallel: 8 }
    class BloodhoundAgent { +track_issues() }
    class TerrierAgent { +create_worktree() }
    class ShepherdAgent { +review_code() }
    class WatchdogAgent { +run_qa() }
    class RetrieverAgent { +merge_branch() }

    AgentIdentityMixin <.. BaseAgent
    AgentPromptMixin <.. BaseAgent
    BaseAgent *-- AgentRuntimeState
    AgentManager --> BaseAgent
    BaseAgent <|-- PackLeaderAgent
    PackLeaderAgent --> BloodhoundAgent
    PackLeaderAgent --> TerrierAgent
    PackLeaderAgent --> ShepherdAgent
    PackLeaderAgent --> WatchdogAgent
    PackLeaderAgent --> RetrieverAgent
    BloodhoundAgent --|> BaseAgent
    TerrierAgent --|> BaseAgent
    ShepherdAgent --|> BaseAgent
    WatchdogAgent --|> BaseAgent
    RetrieverAgent --|> BaseAgent
```

---

## 3. Elixir Supervision Tree

```mermaid
flowchart TB
    App["CodePuppyControl.Application"]
    App --> Repo["Repo (Ecto SQLite)"]
    App --> PubSub["Phoenix.PubSub"]
    App --> EventStore["EventStore (ETS)"]
    App --> RunReg["Run.Registry"]
    App --> RunSup["Run.Supervisor"]
    App --> PWSup["PythonWorker.Supervisor"]
    App --> MCPReg["Registry (MCP)"]
    App --> MCPSup["MCP.Supervisor"]
    App --> ConcSup["Concurrency.Supervisor"]
    App --> ReqTracker["RequestTracker"]
    App --> Oban["Oban (SQLite Lite)"]
    App --> Cron["CronScheduler"]
    App --> Endpoint["Web.Endpoint (Phoenix)"]
```


---

## 4. Communication: Python to Elixir (JSON-RPC 2.0)

```mermaid
sequenceDiagram
    participant E as Elixir Port
    participant W as wire_protocol.py
    participant BC as BridgeController
    participant T as Tools/Agent
    E->>W: Content-Length frame + JSON-RPC request
    W->>BC: dispatch(method, params)
    BC->>T: execute tool or agent
    T-->>BC: result
    BC-->>W: response
    W-->>E: Content-Length frame + JSON-RPC response
    Note over E,W: Batch mode: N requests in single frame (bd-106)
```

---

## 5. Callback Hook Lifecycle

```mermaid
flowchart LR
    Start([startup]) --> RS[agent_run_start]
    RS --> LoadP[load_prompt]
    LoadP --> PreTool[pre_tool_call]
    PreTool --> Exec{Tool}
    Exec --> FO[file_operations]
    Exec --> SH[run_shell_command]
    Exec --> IA[invoke_agent]
    FO --> PostTool[post_tool_call]
    SH --> PostTool
    IA --> PostTool
    PostTool --> RE[agent_run_end]
    RE --> Shutdown([shutdown])
```

---

## 6. Native Backend Routing

```mermaid
flowchart TD
    Req[Request] --> NB{NativeBackend}
    NB --> ECP[Elixir Control Plane]
    ECP -->|file ops| FileSvc[File Service]
    ECP -->|parsing| ParseSvc[Parse Service]
    ECP -->|scheduling| SchedSvc[Scheduler]
    
    FileSvc --> Result[Result]
    ParseSvc --> Result
    SchedSvc --> Result
    
    style ECP fill:#4CAF50,stroke:#2E7D32
    style FileSvc fill:#81C784,stroke:#4CAF50
    style ParseSvc fill:#81C784,stroke:#4CAF50
    style SchedSvc fill:#81C784,stroke:#4CAF50
```

---

## 7. Technology Stack

```mermaid
flowchart LR
    subgraph Py["Python 3.14 (Thin Shell)"]
        P1["PydanticAI (Agent Loop)"]
        P2["FastAPI (API)"]
        P3["Textual (TUI)"]
        P4["CLI Interface"]
    end
    subgraph Ex["Elixir/OTP (Full Backend)"]
        E1["Phoenix (Web/WS)"]
        E2["Oban (Job Queue)"]
        E3["Ecto SQLite (Persistence)"]
        E4["File Service"]
        E5["Parse Service"]
        E6["Rustler NIFs (tree-sitter)"]
    end
    Py <-->|JSON-RPC| Ex
    Ex <-->|Rustler NIF| E6
    
    style Py fill:#E3F2FD,stroke:#1976D2
    style Ex fill:#E8F5E9,stroke:#4CAF50
```

---

## 8. Repository Structure

```
code_puppy/
├── code_puppy/                 # Python thin shell (TUI + CLI + agent loop)
│   ├── agents/                 # 28 agent classes
│   │   ├── base_agent.py       # BaseAgent ABC
│   │   ├── agent_manager.py    # Discovery + registry
│   │   ├── agent_pack_leader.py
│   │   └── pack/               # Bloodhound, Terrier, etc.
│   ├── plugins/                # 40+ plugins
│   │   ├── elixir_bridge/      # Python-Elixir JSON-RPC bridge
│   │   ├── fast_puppy/         # Runtime backend selector (Python)
│   │   └── pack_parallelism/   # Run limiter
│   ├── tools/                  # 18+ tools (routed to Elixir)
│   ├── messaging/              # MessageBus + renderers
│   ├── native_backend.py       # Elixir-first backend router
│   ├── callbacks.py            # Hook engine
│   └── config.py
├── elixir/code_puppy_control/  # Elixir OTP application (FULL BACKEND)
│   ├── lib/                    # OTP app, protocol, file_ops, scheduler
│   └── native/                 # Rust NIFs (tree-sitter bindings)
├── tests/                      # Python test suite
├── pyproject.toml              # Python build
└── lefthook.yml                # Git hooks
```
