defmodule CodePuppyControl.CLI.SlashCommands.Commands.Session do
  @moduledoc """
  Session slash commands: /compact, /truncate.

  These commands manage conversation history. Both are currently stubs
  that depend on the agent summarization port, which is a future ticket.
  """

  # TODO(bd-163-follow-up): Wire /compact and /truncate to agent message history
  # once the summarization port is implemented.

  @doc """
  Handles `/compact` — compacts conversation history (stub).

  The full implementation depends on `CurrentAgent.summarize_messages`,
  which is not yet wired. Prints a visible warning rather than silently
  no-oping.
  """
  @spec handle_compact(String.t(), any()) :: {:continue, any()}
  def handle_compact(_line, state) do
    IO.puts(
      IO.ANSI.yellow() <>
        "⚠️  /compact not yet implemented — depends on agent summarization port" <>
        IO.ANSI.reset()
    )

    {:continue, state}
  end

  @doc """
  Handles `/truncate <N>` — truncates conversation to last N messages (stub).

  The full implementation depends on the agent message history port.
  Currently prints a visible warning. If N cannot be parsed, prints an
  error message.
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
            # TODO(bd-163-follow-up): Wire to agent message history
            # Agent history trimming is not yet fully wired.
            IO.puts(
              IO.ANSI.yellow() <>
                "⚠️  /truncate not yet implemented — depends on agent message history port" <>
                IO.ANSI.reset()
            )

            {:continue, state}

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

  # ── Helpers ──────────────────────────────────────────────────────────────

  @spec extract_args(String.t()) :: String.t()
  defp extract_args("/" <> rest) do
    case String.split(rest, " ", parts: 2) do
      [_name] -> ""
      [_name, args] -> args
    end
  end

  defp extract_args(_line), do: ""
end
