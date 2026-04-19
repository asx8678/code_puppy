defmodule CodePuppyControlWeb.CommandsController do
  @moduledoc """
  REST API controller for slash command execution and autocomplete.

  Replaces `code_puppy/api/routers/commands.py` from the Python FastAPI server.

  ## Current status (bd-214 Wave 2)

  The `list` and `show` endpoints are functional stubs that return empty
  lists or 404s. The `execute` and `autocomplete` endpoints return 501
  Not Implemented because the Python `command_registry` and subprocess
  execution infrastructure have not yet been ported to Elixir.

  Full implementation is deferred to a future wave once
  `CodePuppyControl.CommandRegistry` lands.

  ## Endpoints

  - `GET /api/commands` — List all available slash commands
  - `GET /api/commands/:name` — Get info about a specific command
  - `POST /api/commands/execute` — Execute a slash command (stub)
  - `POST /api/commands/autocomplete` — Get autocomplete suggestions (stub)
  """

  use CodePuppyControlWeb, :controller

  alias CodePuppyControl.Tools.AgentCatalogue

  @doc """
  GET /api/commands

  Lists all available slash commands.

  Returns a sorted list of command info objects including name,
  description, usage, aliases, category, and detailed help.

  ## Stub note (bd-214)

  The Python `command_registry` and plugin callback system
  (`on_custom_command_help`) have not yet been ported to Elixir.
  As a stopgap, this endpoint queries `AgentCatalogue` for agent
  names and presents them as commands. Once
  `CodePuppyControl.CommandRegistry` is implemented, this will
  be replaced with a proper command lookup.
  """
  def index(conn, _params) do
    # TODO(bd-214): Replace with CodePuppyControl.CommandRegistry when available.
    # The Python version reads from command_registry.get_unique_commands()
    # and plugin callbacks (on_custom_command_help).
    commands =
      case try_list_agents() do
        {:ok, agents} ->
          Enum.map(agents, fn info ->
            %{
              name: info.name,
              description: info.description,
              usage: "/#{info.name}",
              aliases: [],
              category: "agent"
            }
          end)

        :error ->
          []
      end

    json(conn, commands)
  end

  @doc """
  GET /api/commands/:name

  Gets detailed info about a specific command by name or alias.

  Currently returns 404 for all names — the command registry has not been
  ported to Elixir yet.
  """
  def show(conn, %{"name" => name}) do
    # TODO(bd-214): Integrate with CodePuppyControl.CommandRegistry when available.
    conn
    |> put_status(:not_found)
    |> json(%{error: "Command '/#{name}' not found"})
  end

  @doc """
  POST /api/commands/execute

  Executes a slash command.

  Auth: Protected (Wave 5 will add auth plug; currently open for loopback-only deployment).

  Request body:
      { "command": "/set model=gpt-4o" }

  Currently returns 501 Not Implemented — subprocess command execution
  has not been ported to Elixir yet.
  """
  def execute(conn, _params) do
    # TODO(bd-214): Implement command execution via Task.Supervisor + Port
    # The Python version runs commands in a subprocess with timeout.
    conn
    |> put_status(:not_implemented)
    |> json(%{
      error: "Command execution is not yet implemented in the Elixir server",
      suggestion: "Use the Python FastAPI server for command execution"
    })
  end

  @doc """
  POST /api/commands/autocomplete

  Gets autocomplete suggestions for a partial command.

  Auth: Protected (Wave 5 will add auth plug; currently open for loopback-only deployment).

  Request body:
      { "partial": "/se" }

  Currently returns an empty suggestions list — the command registry has
  not been ported to Elixir yet.
  """
  def autocomplete(conn, _params) do
    # TODO(bd-214): Integrate with CodePuppyControl.CommandRegistry when available.
    json(conn, %{suggestions: []})
  end

  # ── Private helpers ──────────────────────────────────────────────────────

  # Attempt to read from AgentCatalogue; gracefully handle the case where
  # the GenServer hasn't started (e.g. in test or before supervision tree
  # is fully booted).
  defp try_list_agents do
    try do
      {:ok, AgentCatalogue.list_agents()}
    catch
      :exit, _ -> :error
    end
  end
end
