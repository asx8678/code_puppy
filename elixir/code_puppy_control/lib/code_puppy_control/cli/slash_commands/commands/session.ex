defmodule CodePuppyControl.CLI.SlashCommands.Commands.Session do
  @moduledoc """
  Session slash commands: /compact, /truncate.

  These commands manage conversation history via Agent.State
  and the Compaction pipeline.
  """

  alias CodePuppyControl.Agent.State, as: AgentState
  alias CodePuppyControl.Compaction

  @doc """
  Handles `/compact` — compacts conversation history.

  Runs the Compaction pipeline (filter → truncate tool args → split)
  on the current session's message history and writes the result back
  via `Agent.State.set_messages/3`.

  Prints a warning if no history exists, or a success summary with
  before/after message counts and compaction stats.
  """
  @spec handle_compact(String.t(), any()) :: {:continue, any()}
  def handle_compact(_line, state) do
    session_id = get_session_id(state)
    agent_name = get_agent_name(state)

    if is_nil(session_id) do
      IO.puts(
        IO.ANSI.red() <>
          "No active session — cannot compact." <>
          IO.ANSI.reset()
      )

      {:continue, state}
    else
      messages = AgentState.get_messages(session_id, agent_name)

      if messages == [] do
        IO.puts(
          IO.ANSI.yellow() <>
            "⚠️  No history to compact yet. Ask me something first!" <>
            IO.ANSI.reset()
        )

        {:continue, state}
      else
        do_compact(session_id, agent_name, messages, state)
      end
    end
  end

  @doc """
  Handles `/truncate <N>` — truncates conversation to last N messages.

  Preserves the first message (system message) and keeps the N-1 most
  recent messages after it. Writes the truncated history back via
  `Agent.State.set_messages/3`.

  Mirrors Python's `/truncate` behavior from session_commands.py.
  """
  @spec handle_truncate(String.t(), any()) :: {:continue, any()}
  def handle_truncate(line, state) do
    args = extract_args(line)

    cond do
      args == "" ->
        IO.puts(
          IO.ANSI.red() <>
            "Usage: /truncate <N>" <>
            IO.ANSI.reset()
        )

        {:continue, state}

      true ->
        case Integer.parse(String.trim(args)) do
          {n, ""} when n > 0 ->
            do_truncate(state, n)

          _ ->
            IO.puts(
              IO.ANSI.red() <>
                "Invalid number: #{args}. Usage: /truncate <N>" <>
                IO.ANSI.reset()
            )

            {:continue, state}
        end
    end
  end

  # ── Private: compact implementation ───────────────────────────────────

  defp do_compact(session_id, agent_name, messages, state) do
    before_count = length(messages)

    case Compaction.compact(messages) do
      {:ok, compacted, stats} ->
        AgentState.set_messages(session_id, agent_name, compacted)
        after_count = length(compacted)

        IO.puts(
          IO.ANSI.green() <>
            "✨ Compacted: #{before_count} → #{after_count} messages " <>
            "(dropped=#{stats.dropped_by_filter}, " <>
            "truncated=#{stats.truncated_count}, " <>
            "summarize_candidates=#{stats.summarize_count})" <>
            IO.ANSI.reset()
        )

        {:continue, state}

      error ->
        IO.puts(
          IO.ANSI.red() <>
            "Compaction failed: #{inspect(error)}" <>
            IO.ANSI.reset()
        )

        {:continue, state}
    end
  end

  # ── Private: truncate implementation ──────────────────────────────────

  defp do_truncate(state, n) do
    session_id = get_session_id(state)
    agent_name = get_agent_name(state)

    if is_nil(session_id) do
      IO.puts(
        IO.ANSI.red() <>
          "No active session — cannot truncate." <>
          IO.ANSI.reset()
      )

      {:continue, state}
    else
      messages = AgentState.get_messages(session_id, agent_name)

      if messages == [] do
        IO.puts(
          IO.ANSI.yellow() <>
            "⚠️  No history to truncate yet. Ask me something first!" <>
            IO.ANSI.reset()
        )

        {:continue, state}
      else
        current_count = length(messages)

        if current_count <= n do
          IO.puts(
            IO.ANSI.yellow() <>
              "History already has #{current_count} messages, " <>
              "which is ≤ #{n}. Nothing to truncate." <>
              IO.ANSI.reset()
          )

          {:continue, state}
        else
          # Keep first message (system) + last (n-1) messages
          truncated =
            if n > 1 do
              [hd(messages)] ++ Enum.take(messages, -(n - 1))
            else
              [hd(messages)]
            end

          AgentState.set_messages(session_id, agent_name, truncated)

          IO.puts(
            IO.ANSI.green() <>
              "✂️  Truncated: #{current_count} → #{length(truncated)} messages " <>
              "(keeping system message and #{n - 1} most recent)" <>
              IO.ANSI.reset()
          )

          {:continue, state}
        end
      end
    end
  end

  # ── Helpers ──────────────────────────────────────────────────────────────

  @spec extract_args(String.t()) :: String.t()
  defp extract_args("/" <> rest) do
    case String.split(rest, " ", parts: 2) do
      [_name] -> ""
      [_name, args] -> args
    end
  end

  defp extract_args(_line), do: ""

  @spec get_session_id(any()) :: String.t() | nil
  defp get_session_id(state) when is_map(state), do: Map.get(state, :session_id)
  defp get_session_id(_), do: nil

  @spec get_agent_name(any()) :: String.t()
  defp get_agent_name(state) when is_map(state) do
    Map.get(state, :agent, "code-puppy")
  end

  defp get_agent_name(_), do: "code-puppy"
end
