# Mana - Plugin System for Agent Orchestration

Mana is an Elixir/Phoenix plugin system that mirrors Code Puppy's callback architecture, providing a robust extension mechanism for agent-based applications.

## Overview

Mana provides extension points for:

- **Agent Lifecycle**: `:agent_run_start`, `:agent_run_end`, `:invoke_agent`, `:agent_exception`
- **Tool Execution**: `:pre_tool_call`, `:post_tool_call`
- **System Events**: `:startup`, `:shutdown`
- **Streaming**: `:stream_event` for real-time events
- **Registration**: `:register_tools`, `:register_agents`, `:register_model_type`
- **Operations**: `:file_permission`, `:run_shell_command`, `:edit_file`, `:create_file`, etc.
- **Configuration**: `:load_prompt`, `:load_model_config`, `:get_model_system_prompt`

## Architecture

- `Mana.Plugin.Behaviour` - Plugin behaviour definition
- `Mana.Plugin.Manager` - GenServer for plugin discovery and hook dispatch
- `Mana.Plugin.Hook` - Hook definitions and utilities
- `Mana.Plugins.*` - Built-in plugins (e.g., `Mana.Plugins.Logger`)

## Quick Start

### 1. Add to your supervision tree

```elixir
children = [
  Mana.Plugin.Manager
]
```

### 2. Create a plugin

```elixir
defmodule MyApp.Plugins.Analytics do
  @behaviour Mana.Plugin.Behaviour

  @impl true
  def name, do: "analytics"

  @impl true
  def init(config) do
    {:ok, %{api_key: config.api_key}}
  end

  @impl true
  def hooks do
    [
      {:agent_run_start, &__MODULE__.on_run_start/3},
      {:agent_run_end, &__MODULE__.on_run_end/7}
    ]
  end

  def on_run_start(agent_name, model_name, session_id) do
    # Track run start
    :ok
  end

  def on_run_end(agent_name, model_name, session_id, success, error, response, metadata) do
    # Track run completion
    :ok
  end
end
```

### 3. Trigger hooks from your application

```elixir
# Synchronous - waits for callbacks
Mana.Plugin.Manager.trigger(:agent_run_start, ["my_agent", "gpt-4", nil])

# Asynchronous - fire and forget
Mana.Plugin.Manager.trigger_async(:stream_event, ["token", %{token: "hello"}, session_id])
```

## Configuration

### Config Files

```elixir
# config/config.exs
config :mana, Mana.Plugin.Manager,
  plugins: [:discover, MyApp.Plugins.Analytics],
  backlog_ttl: 30_000,
  max_backlog_size: 100
```

### Environment Variables (Production)

```bash
# Set log level
MANA_LOG_LEVEL=info

# Comma-separated list of plugin modules to load
MANA_PLUGINS=MyApp.Plugins.Analytics,MyApp.Plugins.Monitoring

# Backlog configuration
MANA_BACKLOG_TTL=30000
MANA_MAX_BACKLOG=100
```

## Available Hooks

| Hook | Async | Description |
|------|-------|-------------|
| `:startup` | ✓ | Application startup |
| `:shutdown` | ✓ | Graceful shutdown |
| `:invoke_agent` | ✓ | Agent invocation |
| `:agent_exception` | ✓ | Agent error handling |
| `:agent_run_start` | ✓ | Agent run begins |
| `:agent_run_end` | ✓ | Agent run completes |
| `:pre_tool_call` | ✓ | Before tool execution |
| `:post_tool_call` | ✓ | After tool completion |
| `:stream_event` | ✓ | Real-time streaming |
| `:register_tools` | | Custom tool registration |
| `:register_agents` | | Custom agent registration |
| `:load_prompt` | | System prompt loading |
| `:file_permission` | | File operation checks |
| `:run_shell_command` | ✓ | Shell execution |
| `:custom_command` | | Slash command handling |
| `:get_motd` | | Message of the day |

## Built-in Plugins

### Logger Plugin

```elixir
config :mana, Mana.Plugin.Manager,
  plugins: [:discover, Mana.Plugins.Logger],
  plugin_configs: %{
    Mana.Plugins.Logger => %{
      level: :info,
      log_tool_calls: true,
      log_stream_events: false
    }
  }
```

## Plugin Discovery

Mana supports auto-discovery of plugins:

1. Modules in `Mana.Plugins` namespace are auto-discovered
2. Additional namespaces can be configured:

```elixir
config :mana,
  plugin_namespaces: [Mana.Plugins, MyApp.Plugins]
```

## Event Backlog

Events that fire before any listeners are registered are buffered. After
registering a plugin, call `drain_backlog/1` to replay missed events:

```elixir
Mana.Plugin.Manager.drain_backlog(:agent_run_start)
Mana.Plugin.Manager.drain_all_backlogs()
```

## API Reference

### Manager Functions

- `start_link/1` - Start the manager
- `child_spec/1` - Supervisor child spec
- `register_plugin/2` - Register a plugin at runtime
- `unregister_plugin/1` - Unregister a plugin
- `trigger/3` - Trigger hook synchronously
- `trigger_async/2` - Trigger hook asynchronously
- `drain_backlog/1` - Replay buffered events
- `drain_all_backlogs/0` - Replay all buffered events
- `list_plugins/0` - List loaded plugins
- `get_stats/0` - Get manager statistics

## Testing

Run tests:

```bash
mix test
```

Run with coverage:

```bash
mix test --cover
```

## License

MIT License - See LICENSE file for details.
