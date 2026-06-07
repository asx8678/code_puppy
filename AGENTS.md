# Contributing to Code Puppy

> **Golden rule:** nearly all new functionality should be a **plugin** under `code_puppy/plugins/`
> that hooks into core via `code_puppy/callbacks.py`. Don't edit `code_puppy/command_line/`.

## How Plugins Work

Create `code_puppy/plugins/my_feature/register_callbacks.py` (builtin) or `~/.code_puppy/plugins/my_feature/register_callbacks.py` (user):

```python
from code_puppy.callbacks import register_callback

def _on_startup():
    print("my_feature loaded!")

register_callback("startup", _on_startup)
```

That's it. The plugin loader auto-discovers `register_callbacks.py` in subdirs.

## Available Hooks

`register_callback("<hook>", func)` — deduplicated, async hooks accept sync or async functions.

| Hook | When | Signature |
|------|------|-----------|
| `startup` | App boot | `() -> None` |
| `shutdown` | Graceful exit | `() -> None` |
| `invoke_agent` | Sub-agent invoked | `(*args, **kwargs) -> None` |
| `agent_exception` | Unhandled agent error | `(exception, *args, **kwargs) -> None` |
| `agent_run_start` | Before agent task | `(agent_name, model_name, session_id=None) -> None` |
| `agent_run_end` | After agent run | `(agent_name, model_name, session_id=None, success=True, error=None, response_text=None, metadata=None) -> None` |
| `load_prompt` | System prompt assembly | `() -> str \| None` |
| `run_shell_command` | Before shell exec | `(context, command, cwd=None, timeout=60) -> dict \| None` (return `{"blocked": True}` to block) |
| `file_permission` | Before file op | `(context, file_path, operation, ...) -> bool` |
| `pre_tool_call` | Before tool executes | `(tool_name, tool_args, context=None) -> Any` |
| `post_tool_call` | After tool finishes | `(tool_name, tool_args, result, duration_ms, context=None) -> Any` |
| `custom_command` | Unknown `/slash` cmd | `(command, name) -> True \| str \| None` |
| `custom_command_help` | `/help` menu | `() -> list[tuple[str, str]]` |
| `register_tools` | Tool registration | `() -> list[dict]` with `{"name": str, "register_func": callable}` |
| `register_agent_tools` | Advertise tools to an agent's available list | `(agent_name: str \| None) -> list[str]` — tool names from `TOOL_REGISTRY` to merge into the agent's hardcoded `get_available_tools()` |
| `register_agents` | Agent catalogue | `() -> list[dict]` with `{"name": str, "class": type}` |
| `register_model_type` | Custom model type | `() -> list[dict]` with `{"type": str, "handler": callable}` |
| `register_skills` | Skill catalogue | `() -> list[dict]` with `{"name": str, "skill_md" \| "skill_md_path" \| "frontmatter"+"body"}` |
| `load_model_config` | Patch model config | `(*args, **kwargs) -> Any` |
| `load_models_config` | Inject models | `() -> dict` |
| `load_model_descriptions` | Inject description overlays | `() -> dict[str, str]` |
| `get_model_system_prompt` | Per-model prompt | `(model_name, default_prompt, user_prompt) -> dict \| None` |
| `stream_event` | Response streaming | `(event_type, event_data, agent_session_id=None) -> None` |
| `pre_mcp_autostart` | Before bound MCP servers auto-start | `(agent_name, server_names) -> None` (refresh tokens / mint creds here) |

Full list + rarely-used hooks: see `code_puppy/callbacks.py` source.

## Rules

1. **Plugins over core** — if a hook exists for it, use it
2. **One `register_callbacks.py` per plugin** — register at module scope
3. **600-line hard cap** — split into submodules
4. **Fail gracefully** — never crash the app
5. **Return `None` from commands you don't own**
6. **Always run linters - `ruff check --fix`, `ruff format .`
7. **NEVER ALLOW A CLAUDE CO-AUTHOR COMMIT**

## Multi-Agent Architecture

Code Puppy supports a multi-agent delegation system where specialized agents collaborate on complex tasks.

### Agents

| Agent | Name | Display | Mode | Tools |
|-------|------|---------|------|-------|
| **Orchestrator** 🎯 | `orchestrator` | Orchestrator 🎯 | Opt-in (`/agent orchestrator`) | Read-only (list_files, read_file, grep) — **no write tools** |
| **Planning Agent** 🧠 | `planning-agent` | Planning Agent 🧠 | Opt-in (`/agent planning-agent`) | Dual-mode: Plan Mode (read-only) + Fix/Execute Mode (shell + create_file + replace_in_file + delete_snippet with guardrails) |
| **Explore** 🔍 | `explore` | Explore 🔍 | Opt-in (`/agent explore`) | Read-only (list_files, read_file, grep, agent_run_shell_command, list_or_search_skills) — **no write tools, no invoke_agent** |
| **Code Puppy** 🐶 | `code-puppy` | Code Puppy 🐶 | Default | Full tool access |
| **Fast Puppy** ⚡ | `fast-puppy` | Fast Puppy ⚡ | Opt-in | Full tool access |

### Orchestrator (Conductor)

The orchestrator is a **pure read-only conductor**. It:
- Reads the `bd` ready queue to identify the next task
- Routes already-planned work to the right agent — it never plans or reasons through complex problems itself
- Delegates ALL planning, decomposition, and complex analysis to `planning-agent` (the instant a task stops being mechanical, it hands off)
- Delegates code changes to `planning-agent` (for hard fixes / investigations) or `fast-puppy` / `code-puppy` (for routine execution)
- **Never writes code itself** — it has no write tools
- **Never plans complex work itself** — planning, decomposition, and hard thinking all live with `planning-agent`

### Planning Agent (Dual-Mode)

The planning agent operates in two modes:

- **Plan Mode** (default): Investigates codebases, produces roadmaps, answers architecture questions — read-only exploration
- **Fix/Execute Mode**: For small, well-understood changes, can directly run shell commands and use `create_file`, `replace_in_file`, and `delete_snippet` — with guardrails:
  - Scope limits on what files can be touched
  - Confirmation required for destructive or risky operations
  - Escalation to the user for decisions that require human judgment

### Delegation Flow

```
User
 └─→ Orchestrator 🎯 (read-only conductor)
      └─→ Planning Agent 🧠 (investigation / hard fixes)
           ├─→ Explore 🔍 (cheap read-only exploration — file discovery, repo walking, context gathering)
           └─→ fast-puppy / code-puppy (routine execution)
                └─→ Reviewers / QA agents
```

### Session Continuity

Delegation uses `session_id` to maintain conversation context across multi-turn agent handoffs. When an orchestrator delegates to a planning-agent, the `session_id` ensures the receiving agent has full context from prior turns — no information is lost between hops.

### Model-Pinning

Pin models per-agent for cost optimization:

| Config Key | Agent | Recommendation |
|------------|-------|----------------|
| `agent_model_orchestrator` | Orchestrator 🎯 | **Cheap/fast** model — it only reads and delegates |
| `agent_model_planning-agent` | Planning Agent 🧠 | **Expensive/capable** model — it does deep analysis and targeted fixes |
| `agent_model_explore` | Explore 🔍 | **Cheap/fast** model (Haiku, Cerebras GLM) — read-only exploration |

Set these in your models config (e.g., `~/.code_puppy/extra_models.json`).
