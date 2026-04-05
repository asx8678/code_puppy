defmodule Mana.Tools.Terminal.Tools do
  @moduledoc """
  Plugin module that registers all terminal tools via the `register_tools` hook.

  This module implements `Mana.Plugin.Behaviour` so that terminal tools are
  automatically discovered and registered when the plugin system starts.

  ## Registered Tools

  - `terminal_open` — Open a new PTY session
  - `terminal_run_command` — Execute a command in a session
  - `terminal_send_keys` — Send raw keystrokes
  - `terminal_read_output` — Read current terminal buffer
  - `terminal_close` — Close a session and clean up
  - `terminal_screenshot_analyze` — Capture terminal state as text for analysis

  ## Architecture

  The actual tool logic lives in the individual Behaviour modules under
  `Mana.Tools.Terminal.*`. This plugin acts as the registration glue,
  ensuring the terminal tools are available both via the Tools Registry
  (for agent execution) and via the plugin hook system (for discovery).

  ## Tool Modules

  Each tool module implements `Mana.Tools.Behaviour` and is also listed
  in `Mana.Tools.Registry`'s `@expected_tools` so that it participates
  in the ETS-backed fast lookup path.
  """

  @behaviour Mana.Plugin.Behaviour

  require Logger

  @tool_modules [
    Mana.Tools.Terminal.Open,
    Mana.Tools.Terminal.RunCommand,
    Mana.Tools.Terminal.SendKeys,
    Mana.Tools.Terminal.ReadOutput,
    Mana.Tools.Terminal.Close,
    Mana.Tools.Terminal.Screenshot
  ]

  # ---------------------------------------------------------------------------
  # Plugin.Behaviour callbacks
  # ---------------------------------------------------------------------------

  @impl true
  def name, do: "terminal_tools"

  @impl true
  def init(_config) do
    Logger.info("[#{__MODULE__}] Terminal tools plugin initialized (#{length(@tool_modules)} tools)")
    {:ok, %{tools: @tool_modules}}
  end

  @impl true
  def hooks do
    [
      {:register_tools, &__MODULE__.on_register_tools/0},
      {:startup, &__MODULE__.on_startup/0}
    ]
  end

  @impl true
  def terminate do
    # Close all open terminal sessions on shutdown
    try do
      sessions = Mana.Tools.Terminal.PtyManager.list_sessions()

      Enum.each(sessions, fn session_id ->
        Mana.Tools.Terminal.PtyManager.close_session(session_id)
      end)
    rescue
      _ -> :ok
    end

    :ok
  end

  # ---------------------------------------------------------------------------
  # Hook handlers
  # ---------------------------------------------------------------------------

  @doc false
  def on_startup do
    Enum.each(@tool_modules, fn module ->
      case Mana.Tools.Registry.register(module) do
        :ok ->
          :ok

        {:error, :already_registered} ->
          :ok

        {:error, reason} ->
          Logger.warning("[#{__MODULE__}] Failed to register #{inspect(module)}: #{inspect(reason)}")
      end
    end)

    :ok
  end

  @doc false
  def on_register_tools do
    Enum.map(@tool_modules, fn module ->
      %{
        name: module.name(),
        description: module.description(),
        parameters: module.parameters(),
        execute: &module.execute/1
      }
    end)
  end

  # ---------------------------------------------------------------------------
  # Public API
  # ---------------------------------------------------------------------------

  @doc """
  Returns the list of all terminal tool module names.
  """
  @spec tool_modules() :: [module()]
  def tool_modules, do: @tool_modules

  @doc """
  Returns the list of terminal tool names as strings.
  """
  @spec tool_names() :: [String.t()]
  def tool_names do
    Enum.map(@tool_modules, & &1.name())
  end
end
