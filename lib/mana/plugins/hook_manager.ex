defmodule Mana.Plugins.HookManager do
  @moduledoc """
  Plugin that provides `/hook` commands for inspecting registered callbacks.

  Allows users to introspect the callback system to see what hooks are
  registered, organized by phase.

  ## Commands

  - `/hook list` — Show all registered hooks grouped by phase
  - `/hook count` — Show callback counts per phase

  ## Hooks Registered

  - `:custom_command` — Handle `/hook` slash commands
  - `:custom_command_help` — Advertise in `/help` menu

  ## Example

      /hook list        # Show all hooks by phase
      /hook count       # Show counts per phase
  """

  @behaviour Mana.Plugin.Behaviour

  alias Mana.Callbacks.Registry, as: CallbacksRegistry
  alias Mana.Plugin.Hook

  @command_name "hook"
  @aliases ["hooks"]

  # ── Plugin Behaviour ──────────────────────────────────────────────────────

  @impl true
  def name, do: "hook_manager"

  @impl true
  def init(config) do
    {:ok, %{config: config}}
  end

  @impl true
  def hooks do
    [
      {:custom_command, &__MODULE__.handle_command/2},
      {:custom_command_help, &__MODULE__.command_help/0}
    ]
  end

  @impl true
  def terminate, do: :ok

  # ── Custom Command Help ───────────────────────────────────────────────────

  @doc """
  Returns help entries for the `/hook` command.
  """
  @spec command_help() :: [{String.t(), String.t()}]
  def command_help do
    [
      {"hook", "Manage callbacks – list or count registered hooks by phase"},
      {"hooks", "Alias for /hook"}
    ]
  end

  # ── Command Handler ───────────────────────────────────────────────────────

  @doc """
  Handles `/hook` and `/hooks` slash commands.

  Subcommands:
  - `list` — Show all registered hooks grouped by phase
  - `count` — Show callback counts per phase
  """
  @spec handle_command(String.t(), String.t()) :: true | nil
  def handle_command(command, name) when name in [@command_name | @aliases] do
    tokens = String.split(command, ~r/\s+/, trim: true)
    subcommand = if length(tokens) > 1, do: Enum.at(tokens, 1), else: ""

    result =
      case String.downcase(subcommand) do
        "list" -> handle_list()
        "count" -> handle_count()
        "" -> handle_default()
        other -> "Unknown sub-command: #{other}\nUsage: /hook [list|count]"
      end

    {:ok, result}
  end

  def handle_command(_command, _name), do: nil

  # ── Subcommand Handlers ───────────────────────────────────────────────────

  defp handle_list do
    all_phases = Hook.all_hooks()

    entries =
      all_phases
      |> Enum.map(fn phase ->
        callbacks = get_callbacks_safe(phase)
        {phase, callbacks}
      end)
      |> Enum.filter(fn {_phase, callbacks} -> callbacks != [] end)

    if entries == [] do
      "No hooks registered."
    else
      lines = ["🎣 Registered hooks (#{total_callbacks(entries)} total)\n"]

      lines =
        lines ++
          Enum.flat_map(entries, fn {phase, callbacks} ->
            sig = Hook.callback_signature(phase)
            async = if Hook.async?(phase), do: "async", else: "sync"

            [
              "  📌 #{phase} (#{length(callbacks)} callback#{if length(callbacks) == 1, do: "", else: "s"}, #{async})",
              "     Signature: #{sig}"
            ] ++
              Enum.map(callbacks, fn cb ->
                "     • #{format_callback(cb)}"
              end) ++
              [""]
          end)

      Enum.join(lines, "\n")
    end
  end

  defp handle_count do
    all_phases = Hook.all_hooks()

    entries =
      all_phases
      |> Enum.map(fn phase ->
        callbacks = get_callbacks_safe(phase)
        {phase, length(callbacks)}
      end)

    total = Enum.reduce(entries, 0, fn {_phase, count}, acc -> acc + count end)

    lines = ["📊 Callback counts (#{total} total)\n"]

    lines =
      lines ++
        Enum.map(entries, fn {phase, count} ->
          bar = String.duplicate("█", count) <> String.duplicate("░", max(0, 20 - count))
          "  #{String.pad_trailing(to_string(phase), 35)} #{bar} #{count}"
        end)

    Enum.join(lines, "\n")
  end

  defp handle_default do
    "Usage: /hook [list|count]\n\n" <>
      "  list  — Show all registered hooks grouped by phase\n" <>
      "  count — Show callback counts per phase"
  end

  # ── Helpers ───────────────────────────────────────────────────────────────

  defp get_callbacks_safe(phase) do
    try do
      CallbacksRegistry.get_callbacks(phase)
    rescue
      _ -> []
    catch
      :exit, _ -> []
    end
  end

  defp total_callbacks(entries) do
    Enum.reduce(entries, 0, fn {_phase, callbacks}, acc -> acc + length(callbacks) end)
  end

  defp format_callback(cb) when is_function(cb) do
    info = Function.info(cb)
    module = Keyword.get(info, :module)
    name = Keyword.get(info, :name)
    arity = Keyword.get(info, :arity)

    cond do
      module && name ->
        "#{inspect(module)}.#{name}/#{arity}"

      module ->
        "#{inspect(module)}/anonymous"

      true ->
        "anonymous function"
    end
  end

  defp format_callback(cb), do: inspect(cb, limit: 50)
end
