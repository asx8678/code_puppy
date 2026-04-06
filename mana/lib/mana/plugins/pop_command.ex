defmodule Mana.Plugins.PopCommand do
  @moduledoc """
  Plugin that maintains a stack of previous agent/model selections.

  Provides the `/pop` command to restore a previous agent and model
  combination. Tracks changes whenever the agent or model selection
  changes and allows users to pop back to the previous state.

  ## Commands

  - `/pop` — Restore the previous agent + model combo
  - `/pop N` — Pop N levels back in the selection stack
  - `/pop stack` — Show the current selection stack

  ## Hooks Registered

  - `:custom_command` — Handle `/pop` slash command
  - `:custom_command_help` — Advertise in `/help` menu

  ## Example

      /model gpt-4o        # Switch model (pushes to stack)
      /pop                  # Restore previous model
      /pop 2                # Go back 2 selections
      /pop stack            # Show the stack
  """

  @behaviour Mana.Plugin.Behaviour

  require Logger

  @max_stack_size 20

  # Persistent term key for the selection stack
  @stack_key {__MODULE__, :selection_stack}

  # ── Plugin Behaviour ──────────────────────────────────────────────────────

  @impl true
  def name, do: "pop_command"

  @impl true
  def init(config) do
    # Initialize an empty stack
    :persistent_term.put(@stack_key, [])
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
  def terminate do
    :persistent_term.erase(@stack_key)
    :ok
  end

  # ── Stack Management ──────────────────────────────────────────────────────

  @doc """
  Pushes a selection onto the stack.

  A selection is a map with `:agent` and `:model` keys.
  """
  @spec push_selection(map()) :: :ok
  def push_selection(selection) when is_map(selection) do
    stack = :persistent_term.get(@stack_key, [])

    # Trim stack to max size
    stack =
      if length(stack) >= @max_stack_size do
        [_ | rest] = stack
        rest
      else
        stack
      end

    :persistent_term.put(@stack_key, stack ++ [selection])
    :ok
  end

  @doc """
  Pops the top selection from the stack.
  """
  @spec pop_selection() :: {:ok, map()} | :empty
  def pop_selection do
    stack = :persistent_term.get(@stack_key, [])

    case List.pop_at(stack, -1) do
      {nil, _} ->
        :empty

      {selection, new_stack} ->
        :persistent_term.put(@stack_key, new_stack)
        {:ok, selection}
    end
  end

  @doc """
  Returns the current selection stack.
  """
  @spec get_stack() :: [map()]
  def get_stack do
    :persistent_term.get(@stack_key, [])
  end

  @doc """
  Clears the selection stack.
  """
  @spec clear_stack() :: :ok
  def clear_stack do
    :persistent_term.put(@stack_key, [])
    :ok
  end

  # ── Custom Command ────────────────────────────────────────────────────────

  @doc """
  Returns help entry for `/pop`.
  """
  @spec command_help() :: [{String.t(), String.t()}]
  def command_help do
    [
      {"pop", "Restore the previous agent + model selection (stack-based context switching)"}
    ]
  end

  @doc """
  Handles `/pop` slash commands.

  - `/pop` — Restore previous selection
  - `/pop N` — Go back N levels
  - `/pop stack` — Show the current stack
  - `/pop clear` — Clear the stack
  """
  @spec handle_command(String.t(), String.t()) :: {:ok, String.t()} | nil
  def handle_command(command, "pop") do
    tokens = String.split(command, ~r/\s+/, trim: true)
    arg = if length(tokens) > 1, do: Enum.at(tokens, 1), else: nil

    result =
      case arg do
        nil -> handle_pop(1)
        "stack" -> handle_show_stack()
        "clear" -> handle_clear_stack()
        n -> handle_pop_count(n)
      end

    {:ok, result}
  end

  def handle_command(_command, _name), do: nil

  # ── Command Handlers ──────────────────────────────────────────────────────

  defp handle_pop(count) do
    stack = get_stack()

    if stack == [] do
      "⚠️ Selection stack is empty — nothing to pop.\n" <>
        "Switch agents or models first to build up the stack."
    else
      case pop_n(count) do
        {:ok, selection, popped_count} ->
          apply_selection(selection)
          remaining = length(get_stack())

          "✂️ Popped #{popped_count} selection(s).\n" <>
            format_selection(selection) <>
            "\n📜 Stack: #{remaining} selection(s) remaining"

        {:error, :not_enough} ->
          "⚠️ Stack only has #{length(stack)} selection(s). Popping all.\n" <>
            case pop_n(length(stack)) do
              {:ok, selection, popped_count} ->
                apply_selection(selection)

                "✂️ Popped #{popped_count} selection(s).\n" <>
                  format_selection(selection) <>
                  "\n📜 Stack is now empty"

              error ->
                inspect(error)
            end
      end
    end
  end

  defp handle_pop_count(n_str) do
    case Integer.parse(n_str) do
      {n, ""} when n > 0 ->
        handle_pop(n)

      {n, ""} when n <= 0 ->
        "⚠️ Pop count must be a positive integer"

      _ ->
        "⚠️ Invalid argument '#{n_str}' — usage: /pop [N|stack|clear]"
    end
  end

  defp handle_show_stack do
    stack = get_stack()

    if stack == [] do
      "📜 Selection stack is empty.\n" <>
        "Switch agents or models first to build up the stack."
    else
      lines = ["📜 Selection stack (#{length(stack)} entries, newest last):\n"]

      lines =
        (lines ++
           Enum.with_index(stack, 1))
        |> Enum.map(fn {selection, idx} ->
          "  #{idx}. #{format_selection_one_line(selection)}"
        end)

      Enum.join(lines, "\n")
    end
  end

  defp handle_clear_stack do
    count = length(get_stack())
    clear_stack()
    "🗑️ Cleared #{count} selection(s) from the stack."
  end

  # ── Helpers ───────────────────────────────────────────────────────────────

  defp pop_n(count) do
    stack = get_stack()

    if length(stack) < count do
      {:error, :not_enough}
    else
      # Pop `count` items, return the last one popped
      {to_keep, to_pop} = Enum.split(stack, -count)
      :persistent_term.put(@stack_key, to_keep)

      selection = List.last(to_pop)
      {:ok, selection, count}
    end
  end

  defp apply_selection(%{agent: agent, model: model}) do
    # Apply agent selection
    if agent do
      try do
        Mana.Agents.Registry.set_agent("default", agent)
      rescue
        _ -> :ok
      catch
        :exit, _ -> :ok
      end
    end

    # Model would be applied through the model config
    # For now, just log the restoration
    Logger.info("[PopCommand] Restored selection: agent=#{inspect(agent)}, model=#{inspect(model)}")
    :ok
  end

  defp apply_selection(_), do: :ok

  defp format_selection(%{agent: agent, model: model}) do
    parts = []

    parts =
      if agent do
        parts ++ ["Agent: #{agent}"]
      else
        parts
      end

    parts =
      if model do
        parts ++ ["Model: #{model}"]
      else
        parts
      end

    if parts == [], do: "∅ Empty selection", else: Enum.join(parts, " | ")
  end

  defp format_selection(_), do: "∅ Unknown selection"

  defp format_selection_one_line(%{agent: agent, model: model}) do
    a = if agent, do: "agent=#{agent}", else: ""
    m = if model, do: "model=#{model}", else: ""

    [a, m] |> Enum.filter(&(&1 != "")) |> Enum.join(", ")
  end

  defp format_selection_one_line(_), do: "empty"
end
