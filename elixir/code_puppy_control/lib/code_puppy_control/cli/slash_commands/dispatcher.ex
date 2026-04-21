defmodule CodePuppyControl.CLI.SlashCommands.Dispatcher do
  @moduledoc """
  Pure, stateless dispatch logic for slash commands.

  Given a raw input line and REPL state, dispatches to the appropriate
  command handler via the Registry. Does not own any process state.
  """

  alias CodePuppyControl.CLI.SlashCommands.Registry

  @doc """
  Dispatches a slash command line to the registered handler.

  Returns `{:ok, handler_result}` on success, or an error tuple for
  non-slash input or unknown commands. Handler exceptions propagate —
  the REPL loop wraps this in try/rescue if needed.
  """
  @spec dispatch(String.t(), repl_state :: any()) ::
          {:ok, result :: any()} | {:error, :not_a_slash_command | :unknown_command}
  def dispatch(line, repl_state) when is_binary(line) do
    if not is_slash_command?(line) do
      {:error, :not_a_slash_command}
    else
      # Strip leading "/"
      stripped = String.slice(line, 1..-1//1)

      # Split on whitespace; first token is command name
      name =
        stripped
        |> String.split(" ", parts: 2)
        |> hd()

      if name == "" do
        {:error, :unknown_command}
      else
        case Registry.get(name) do
          {:ok, cmd_info} ->
            result = cmd_info.handler.(line, repl_state)
            {:ok, result}

          {:error, :not_found} ->
            {:error, :unknown_command}
        end
      end
    end
  end

  @doc """
  Returns true if the input line starts with `/` (slash command).
  """
  @spec is_slash_command?(String.t()) :: boolean()
  def is_slash_command?("/" <> _), do: true
  def is_slash_command?(_), do: false
end
