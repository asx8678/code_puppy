# Mana Plugins

Plugins are the primary way to extend Mana's functionality.

## Creating a Plugin

### Basic Structure

```elixir
defmodule MyPlugin do
  @moduledoc """
  My custom Mana plugin.
  """
  
  use Mana.Plugin
  
  @impl true
  def name, do: :my_plugin
  
  @impl true
  def version, do: "1.0.0"
  
  @impl true
  def init(opts) do
    # Plugin initialization
    register_hook(:startup, &on_startup/0)
    register_hook(:agent_run_end, &on_agent_complete/3)
    
    {:ok, opts}
  end
  
  defp on_startup do
    IO.puts("MyPlugin initialized!")
  end
  
  defp on_agent_complete(agent, result, _opts) do
    # Log or process agent results
    :ok
  end
end
```

### Registering Hooks

```elixir
# Register at module scope
register_hook(:pre_tool_call, &validate_tool_call/3)

# Or during init
register_hook(:post_tool_call, &log_tool_result/4)
```

## Built-in Plugins

Mana ships with several built-in plugins:

### Logger Plugin

Logs agent execution and tool calls:

```elixir
config :mana, Mana.Plugins.Logger,
  level: :info,
  format: :json
```

### Metrics Plugin

Collects execution metrics:

```elixir
config :mana, Mana.Plugins.Metrics,
  backend: :prometheus
```

## Publishing Plugins

### Hex Package

1. Create a new Mix project:
```bash
mix new mana_plugin_my_feature
```

2. Add dependency:
```elixir
def deps do
  [
    {:mana, "~> 0.1.0"}
  ]
end
```

3. Implement `Mana.Plugin.Behaviour`

4. Publish:
```bash
mix hex.publish
```

### Local Plugins

For internal plugins, add to your `lib/`:

```elixir
# lib/mana_plugins/my_plugin.ex
defmodule ManaPlugins.MyPlugin do
  use Mana.Plugin
  
  def init(_opts) do
    Mana.Plugins.register(__MODULE__)
    :ok
  end
end
```

Register in your application:

```elixir
ManaPlugins.MyPlugin.init([])
```

## Best Practices

1. **Keep hooks focused** - Each hook should do one thing
2. **Handle errors gracefully** - Never let a plugin crash the system
3. **Document dependencies** - List required services/config
4. **Test thoroughly** - Use `Mana.Plugin.Test` helpers
5. **Follow naming** - Use `mana_plugin_*` prefix for packages

## Hook Reference

See [HOOKS.md](./HOOKS.md) for the complete list of available hooks.
