defmodule CodePuppyControl.CLI.SlashCommands.Commands.Core do
  @moduledoc """
  Core slash commands: /help, /quit, /exit, /clear, /history, /cd.

  Each handler follows the contract:
  `(raw_line :: String.t(), repl_state) :: {:continue, state} | {:halt, state}`
  """

  alias CodePuppyControl.CLI.SlashCommands.Registry
  alias CodePuppyControl.REPL.History

  @doc """
  Handles `/help` — prints a table of all registered commands.
  """
  @spec handle_help(String.t(), any()) :: {:continue, any()}
  def handle_help(_line, state) do
    commands = Registry.list_all()

    if commands == [] do
      IO.puts("(no commands registered)")
    else
      # Compute column widths
      max_name = commands |> Enum.map(&String.length(&1.name)) |> Enum.max()
      max_usage = commands |> Enum.map(&String.length(&1.usage || "")) |> Enum.max()

      IO.puts("")

      IO.puts(IO.ANSI.bright() <> "    Available commands:" <> IO.ANSI.reset())

      IO.puts("")

      commands
      |> Enum.sort_by(& &1.name)
      |> Enum.each(fn cmd ->
        name_pad = String.duplicate(" ", max_name - String.length(cmd.name) + 2)
        usage = cmd.usage || "/#{cmd.name}"
        usage_pad = String.duplicate(" ", max_usage - String.length(usage) + 2)

        aliases_str =
          if cmd.aliases != [] do
            " (aliases: #{Enum.join(cmd.aliases, ", ")})"
          else
            ""
          end

        IO.puts(
          "    #{IO.ANSI.cyan()}#{cmd.name}#{IO.ANSI.reset()}#{name_pad}" <>
            "#{IO.ANSI.faint()}#{usage}#{IO.ANSI.reset()}#{usage_pad}" <>
            "#{cmd.description}#{aliases_str}"
        )
      end)

      IO.puts("")

      IO.puts("    Tips:")
      IO.puts("      - Use Ctrl+D to exit")
      IO.puts("      - Phase 2 will add tab completion and arrow-key navigation")
      IO.puts("")
    end

    {:continue, state}
  end

  @doc """
  Handles `/quit` and `/exit` — saves history and halts the REPL.
  """
  @spec handle_quit(String.t(), any()) :: {:halt, any()}
  def handle_quit(_line, state) do
    try do
      History.save()
    catch
      :exit, _ -> :ok
    end

    IO.puts("👋 Bye!")
    {:halt, %{state | running: false}}
  end

  @doc """
  Handles `/clear` — clears the terminal screen.
  """
  @spec handle_clear(String.t(), any()) :: {:continue, any()}
  def handle_clear(_line, state) do
    IO.write("\e[2J\e[H")
    {:continue, state}
  end

  @doc """
  Handles `/history` — displays the command history.
  """
  @spec handle_history(String.t(), any()) :: {:continue, any()}
  def handle_history(_line, state) do
    entries =
      try do
        History.all()
      catch
        :exit, _ -> []
      end

    if entries == [] do
      IO.puts("(no history)")
    else
      entries
      |> Enum.reverse()
      |> Enum.with_index(1)
      |> Enum.each(fn {entry, idx} ->
        IO.puts("  #{idx}: #{entry}")
      end)
    end

    {:continue, state}
  end

  @doc """
  Handles `/cd [dir]` — changes the working directory.

  Without an argument, prints the current working directory.
  With an argument, changes to the specified directory.
  """
  @spec handle_cd(String.t(), any()) :: {:continue, any()}
  def handle_cd(line, state) do
    args = extract_args(line)

    if args == "" do
      # No argument — print current cwd
      cwd = File.cwd!()
      IO.puts(cwd)
      {:continue, state}
    else
      dir = String.trim(args)

      case File.cd(dir) do
        :ok ->
          new_cwd = File.cwd!()
          IO.puts("Changed directory to #{new_cwd}")
          {:continue, state}

        {:error, reason} ->
          IO.puts(
            IO.ANSI.red() <>
              "Failed to change directory to '#{dir}': #{inspect(reason)}" <>
              IO.ANSI.reset()
          )

          {:continue, state}
      end
    end
  end

  # ── Helpers ──────────────────────────────────────────────────────────────

  # Extracts the argument portion from a raw slash command line.
  # "/model gpt-4" → "gpt-4"
  # "/help" → ""
  @spec extract_args(String.t()) :: String.t()
  defp extract_args("/" <> rest) do
    case String.split(rest, " ", parts: 2) do
      [_name] -> ""
      [_name, args] -> args
    end
  end

  defp extract_args(_line), do: ""
end
