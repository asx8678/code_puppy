# Mana Architecture

Mana is designed as a modular, plugin-based system for orchestrating AI agents.

## Core Concepts

### Agents

Agents are the fundamental unit of work in Mana. Each agent:
- Has a unique identifier
- Can process messages and return responses
- May use tools to extend its capabilities
- Can be composed with other agents

### Plugins

Plugins extend Mana's functionality without modifying core code:
- Register hooks at various lifecycle points
- Add new tool types
- Provide agent behaviors
- Integrate with external services

See [Plugins Guide](./plugins.md) for details.

### Hooks

The hook system allows plugins to intercept and modify behavior:

| Hook | When | Use Case |
|------|------|----------|
| `startup` | App boot | Initialize resources |
| `shutdown` | App exit | Cleanup resources |
| `pre_tool_call` | Before tool execution | Logging, validation |
| `post_tool_call` | After tool execution | Result transformation |
| `agent_run_start` | Agent execution start | Setup, metrics |
| `agent_run_end` | Agent execution end | Teardown, logging |

### Registry Pattern

Mana uses registries for dynamic component management:
- `Mana.AgentsRegistry` - Agent definitions
- `Mana.ToolsRegistry` - Available tools
- `Mana.CommandsRegistry` - CLI commands

## Component Diagram

```
┌─────────────────────────────────────────┐
│              Web Interface              │
│         (Phoenix LiveView)              │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│           Agent Runner                  │
│    (Orchestration & Execution)          │
└──────┬────────────────────┬─────────────┘
       │                    │
┌──────▼─────┐      ┌──────▼──────┐
│   Tools    │      │   Models    │
│  Registry  │      │  Providers  │
└────────────┘      └─────────────┘
       │                    │
┌──────▼────────────────────▼─────────────┐
│            Plugin System                │
│    (Hooks, Callbacks, Extensions)       │
└─────────────────────────────────────────┘
```

## Data Flow

1. **Input** → Message received via Web or API
2. **Routing** → Agent selected from registry
3. **Processing** → Runner executes agent logic
4. **Tools** → Agent may invoke registered tools
5. **Model** → LLM calls made via provider
6. **Output** → Response returned to caller

## Design Principles

1. **Plugin-First**: All functionality should be achievable via plugins
2. **Fail Graceful**: Components degrade gracefully, never crash the system
3. **Type Safety**: Leverage Elixir's type system with Dialyzer
4. **Observability**: Hooks provide insight at every stage
5. **Testability**: Components are designed for easy testing
