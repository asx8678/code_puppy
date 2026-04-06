defmodule Mana.Commands.Hooks do
  @moduledoc """
  Hook management commands for the callbacks system.

  Provides commands for listing, enabling, disabling, and managing
  callbacks registered with the Mana callback registry.

  ## Commands

  - `/hooks` - Show hook usage information
  - `/hooks list` - List all registered callbacks by phase
  - `/hooks status` - Show summary counts per phase
  - `/hooks phases` - List all available hook phases

  ## Examples

      /hooks list
      # Shows all callbacks grouped by phase

      /hooks status
      # Shows: startup: 2, invoke_agent: 1, agent_run_end: 3

      /hooks phases
      # Lists all available hook phases like :startup, :invoke_agent, etc.
  """

  @behaviour Mana.Commands.Behaviour

  alias Mana.Callbacks.Registry, as: CallbacksRegistry
  alias Mana.Plugin.Hook

  @impl true
  def name, do: "/hooks"

  @impl true
  def description, do: "List and manage TTSR/callback hooks"

  @impl true
  def usage, do: "/hooks [list|status|phases]"

  @impl true
  def execute([], _context) do
    show_usage()
  end

  def execute(["list"], _context) do
    list_hooks()
  end

  def execute(["status"], _context) do
    show_status()
  end

  def execute(["phases"], _context) do
    list_phases()
  end

  def execute([unknown | _], _context) do
    {:error, "Unknown subcommand: #{unknown}. #{usage()}"}
  end

  # Implementation

  defp show_usage do
    text = """
    Hook management commands.

    #{usage()}

    Commands:
      list    - List all registered callbacks by phase
      status  - Show summary counts per phase
      phases  - List all available hook phases

    Hooks are registered callback functions that execute during
    various phases of the application lifecycle (startup, agent run,
    tool calls, etc.).
    """

    {:ok, String.trim(text)}
  end

  defp list_hooks do
    phases = Hook.all_hooks()

    lines =
      Enum.flat_map(phases, fn phase ->
        callbacks = CallbacksRegistry.get_callbacks(phase)

        if callbacks == [] do
          []
        else
          [
            "  #{phase} (#{length(callbacks)} callback(s)):"
            | Enum.map(callbacks, &format_callback/1)
          ]
        end
      end)

    if lines == [] do
      {:ok, "No callbacks registered.\n\nPlugins register callbacks during startup."}
    else
      header = "Registered callbacks:\n\n"
      {:ok, header <> Enum.join(lines, "\n")}
    end
  end

  defp show_status do
    phases = Hook.all_hooks()
    stats = CallbacksRegistry.get_stats()

    # Count callbacks per phase
    phase_counts =
      Enum.map(phases, fn phase ->
        count = CallbacksRegistry.get_callbacks(phase) |> length()
        {phase, count}
      end)
      |> Enum.reject(fn {_, count} -> count == 0 end)

    if phase_counts == [] do
      {:ok, "No callbacks registered.\n\nTotal dispatches: #{stats.dispatches}, errors: #{stats.errors}"}
    else
      lines =
        Enum.map(phase_counts, fn {phase, count} ->
          bar = String.duplicate("█", count)
          "  #{phase}: #{bar} #{count}"
        end)

      header = "Callback status:\n\n"
      footer = "\n\nTotal dispatches: #{stats.dispatches}, errors: #{stats.errors}"

      {:ok, header <> Enum.join(lines, "\n") <> footer}
    end
  end

  defp list_phases do
    phases = Hook.all_hooks()

    lines =
      Enum.map(phases, fn phase ->
        arity = Hook.hooks_metadata()[phase][:arity] || 0
        desc = Hook.callback_signature(phase)
        "  • #{phase} (#{arity} args)\n    #{desc}"
      end)

    header = "Available hook phases:\n\n"

    footer = """

    Hooks can be registered for any phase. When the phase is triggered,
    all registered callbacks are executed in registration order.

    Example: register a startup hook with:
      Mana.Callbacks.register(:startup, &MyMod.on_startup/0)
    """

    {:ok, header <> Enum.join(lines, "\n\n") <> footer}
  end

  # Format a callback for display
  defp format_callback(callback) when is_function(callback) do
    info = Function.info(callback)
    name = info[:name] || "anonymous"
    arity = info[:arity] || "?"

    "    - #{name}/#{arity}"
  end

  defp format_callback(callback) do
    "    - #{inspect(callback)}"
  end
end
