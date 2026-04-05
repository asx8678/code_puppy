defmodule Mana.Commands.Core do
  @moduledoc """
  Built-in commands for the Mana system.

  Provides core functionality including:
  - /help - List all commands with descriptions
  - /exit - Graceful shutdown
  - /clear - Clear current session history
  - /set <key> <value> - Set a config value
  - /show <key> - Show a config value
  - /cd <path> - Change working directory

  Each command is a separate module implementing `Mana.Commands.Behaviour`.
  """

  alias Mana.Commands.Behaviour
  alias Mana.Commands.Registry
  alias Mana.Config.Store, as: ConfigStore
  alias Mana.Session.Store

  defmodule Help do
    @moduledoc "/help command - Show help information for all commands"
    @behaviour Behaviour

    @impl true
    def name, do: "/help"

    @impl true
    def description, do: "Show help information for all commands"

    @impl true
    def usage, do: "/help [command]"

    @impl true
    def execute([], _context) do
      # Use :ets directly to avoid calling back into GenServer (prevents deadlock)
      commands = get_commands_from_ets()

      help_text =
        [
          "Available commands:"
          | Enum.map(commands, fn {cmd, desc} ->
              "  #{cmd} - #{desc}"
            end)
        ]
        |> Enum.join("\n")

      {:ok, help_text}
    end

    def execute([command_name], _context) do
      full_name = if String.starts_with?(command_name, "/"), do: command_name, else: "/" <> command_name

      case get_command_from_ets(full_name) do
        {:ok, details} ->
          info = """
          Command: #{details.name}
          Description: #{details.description}
          Usage: #{details.usage}
          """

          {:ok, info}

        {:error, :not_found} ->
          {:error, "Unknown command: #{command_name}"}
      end
    end

    def execute(_args, _context) do
      {:error, "Usage: #{usage()}"}
    end

    # Read directly from ETS to avoid GenServer deadlock
    defp get_commands_from_ets do
      case :ets.whereis(:mana_commands) do
        :undefined ->
          []

        table ->
          :ets.tab2list(table)
          |> Enum.map(fn {name, %{description: desc}} -> {name, desc} end)
          |> Enum.sort()
      end
    end

    defp get_command_from_ets(name) do
      case :ets.whereis(:mana_commands) do
        :undefined ->
          {:error, :not_found}

        table ->
          case :ets.lookup(table, name) do
            [{^name, info}] ->
              {:ok, %{name: name, description: info.description, usage: info.usage}}

            [] ->
              {:error, :not_found}
          end
      end
    end
  end

  defmodule Exit do
    @moduledoc "/exit command - Graceful shutdown"
    @behaviour Behaviour

    @impl true
    def name, do: "/exit"

    @impl true
    def description, do: "Exit the application gracefully"

    @impl true
    def usage, do: "/exit [message]"

    @impl true
    def execute(args, _context) do
      message = if args == [], do: "Goodbye!", else: Enum.join(args, " ")

      # Trigger shutdown via callback system if available
      # For now, just return a special signal that the caller should handle
      {:ok, {:exit, message}}
    end
  end

  defmodule Clear do
    @moduledoc "/clear command - Clear current session history"
    @behaviour Behaviour

    @impl true
    def name, do: "/clear"

    @impl true
    def description, do: "Clear the current session history"

    @impl true
    def usage, do: "/clear"

    @impl true
    def execute(_args, context) do
      session_id = Map.get(context, :session_id) || Store.active_session()

      if session_id do
        :ok = Store.clear(session_id)
        {:ok, "Session #{session_id} cleared."}
      else
        {:error, "No active session to clear"}
      end
    end
  end

  defmodule Set do
    @moduledoc "/set command - Set a configuration value"
    @behaviour Behaviour

    @impl true
    def name, do: "/set"

    @impl true
    def description, do: "Set a configuration value"

    @impl true
    def usage, do: "/set <key> <value>"

    @impl true
    def execute([key, value], _context) do
      key_atom = String.to_atom(key)
      :ok = ConfigStore.put(key_atom, value)
      {:ok, "Set #{key} to #{value}"}
    end

    def execute(_args, _context) do
      {:error, "Usage: #{usage()}"}
    end
  end

  defmodule Show do
    @moduledoc "/show command - Show a configuration value"
    @behaviour Behaviour

    @impl true
    def name, do: "/show"

    @impl true
    def description, do: "Show a configuration value"

    @impl true
    def usage, do: "/show <key>"

    @impl true
    def execute([key], _context) do
      key_atom = String.to_atom(key)
      value = ConfigStore.get(key_atom, nil)

      if value == nil do
        {:ok, "#{key} is not set"}
      else
        {:ok, "#{key} = #{inspect(value)}"}
      end
    end

    def execute(_args, _context) do
      {:error, "Usage: #{usage()}"}
    end
  end

  defmodule Cd do
    @moduledoc "/cd command - Change working directory"
    @behaviour Behaviour

    @impl true
    def name, do: "/cd"

    @impl true
    def description, do: "Change the current working directory"

    @impl true
    def usage, do: "/cd <path>"

    @impl true
    def execute([path], _context) do
      expanded_path = Path.expand(path)

      case File.dir?(expanded_path) do
        true ->
          case File.cd(expanded_path) do
            :ok ->
              cwd = File.cwd!()
              {:ok, "Changed directory to: #{cwd}"}

            {:error, reason} ->
              {:error, "Cannot change directory: #{reason}"}
          end

        false ->
          {:error, "Not a directory: #{expanded_path}"}
      end
    end

    def execute([], _context) do
      cwd = File.cwd!()
      {:ok, "Current directory: #{cwd}"}
    end

    def execute(_args, _context) do
      {:error, "Usage: #{usage()}"}
    end
  end

  defmodule Sessions do
    @moduledoc "/sessions command - List all sessions"
    @behaviour Behaviour

    @impl true
    def name, do: "/sessions"

    @impl true
    def description, do: "List all available sessions"

    @impl true
    def usage, do: "/sessions"

    @impl true
    def execute(_args, _context) do
      sessions = Store.list_sessions()
      active = Store.active_session()

      if sessions == [] do
        {:ok, "No sessions available."}
      else
        lines = Enum.map(sessions, &format_session_line(&1, active))
        {:ok, ["Available sessions:" | lines] |> Enum.join("\n")}
      end
    end

    defp format_session_line(id, active) do
      marker = if id == active, do: " (active)", else: ""
      "  - #{id}#{marker}"
    end
  end

  defmodule Session do
    @moduledoc "/session command - Switch to or create a session"
    @behaviour Behaviour

    @impl true
    def name, do: "/session"

    @impl true
    def description, do: "Switch to a session or create a new one"

    @impl true
    def usage, do: "/session [id|new]"

    @impl true
    def execute([], _context) do
      active = Store.active_session()

      if active do
        {:ok, "Active session: #{active}"}
      else
        {:ok, "No active session. Use '/session new' to create one."}
      end
    end

    def execute(["new"], _context) do
      id = Store.create_session()
      {:ok, "Created new session: #{id}"}
    end

    def execute([session_id], _context) do
      # Check if session exists
      sessions = Store.list_sessions()

      if session_id in sessions do
        :ok = Store.set_active_session(session_id)
        {:ok, "Switched to session: #{session_id}"}
      else
        {:error, "Session not found: #{session_id}"}
      end
    end

    def execute(_args, _context) do
      {:error, "Usage: #{usage()}"}
    end
  end

  @doc """
  Registers all core commands with the registry.
  """
  @spec register_all() :: :ok
  def register_all do
    commands = [
      Help,
      Exit,
      Clear,
      Set,
      Show,
      Cd,
      Sessions,
      Session
    ]

    Enum.each(commands, fn module ->
      case Registry.register(module) do
        :ok -> :ok
        {:error, :already_registered} -> :ok
        error -> error
      end
    end)
  end
end
