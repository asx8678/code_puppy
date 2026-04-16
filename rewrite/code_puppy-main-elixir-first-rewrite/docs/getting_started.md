# Getting Started with Mana

Mana is a plugin-based system for agent orchestration. This guide will help you get up and running quickly.

## Installation

Add Mana to your `mix.exs`:

```elixir
def deps do
  [
    {:mana, "~> 0.1.0"}
  ]
end
```

Then run:

```bash
mix deps.get
```

## Quick Start

### 1. Define an Agent

Create an agent module:

```elixir
defmodule MyApp.Agents.MyAgent do
  use Mana.Agent

  def run(message, _opts) do
    {:ok, "Processed: #{message}"}
  end
end
```

### 2. Register the Agent

Add to your application:

```elixir
defmodule MyApp.Application do
  use Application

  def start(_type, _args) do
    Mana.AgentsRegistry.register(MyApp.Agents.MyAgent)
    
    children = [
      # ... other workers
    ]
    
    Supervisor.start_link(children, strategy: :one_for_one)
  end
end
```

### 3. Run the Agent

```elixir
{:ok, result} = Mana.Agent.run("Hello, world!")
```

## Configuration

Create a `config/config.exs`:

```elixir
import Config

config :mana, Mana.Agents,
  default_timeout: 30_000,
  max_retries: 3
```

## Next Steps

- Read the [Architecture Overview](./architecture.md)
- Learn about [Plugins](./plugins.md)
- Explore the [Hook System](./HOOKS.md)
