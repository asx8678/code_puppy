defmodule Mana.TUI.Completion do
  @moduledoc """
  Tab completion system for the Mana TUI input loop.

  Provides completion for:
  - `/` prefix → command names from `Mana.Commands.Registry`
  - `@` prefix → agent names from `Mana.Agents.Registry`
  - File paths after `@` or when no prefix matches

  ## Usage

      iex> Mana.TUI.Completion.complete("/mod", %{})
      {["/model"], "/model"}

      iex> Mana.TUI.Completion.complete("@hus", %{})
      {["@husky"], "@husky"}

      iex> {completions, prefix} = Mana.TUI.Completion.complete("/m", %{})
      iex> {"/model", "/m"} in Enum.zip(completions, Stream.repeatedly("/m"))
      true

  ## Cycling

  When multiple completions are available, `cycle/2` advances through them:

      iex> Mana.TUI.Completion.cycle(0, ["/model", "/model"])
      {1, "/model"}
  """

  alias Mana.Agents.Registry, as: AgentRegistry
  alias Mana.Commands.Registry, as: CommandRegistry

  @type completion :: String.t()
  @type context :: map()

  @doc """
  Returns completions and their common prefix for the given partial input.

  The second argument is a context map (reserved for future use).

  ## Returns

  `{completions, common_prefix}` where:
  - `completions` — sorted list of matching completion strings
  - `common_prefix` — longest shared prefix across all completions (or `""` if none)
  """
  @spec complete(String.t(), context()) :: {[completion()], String.t()}
  def complete(partial_input, _context \\ %{})

  def complete("", _context) do
    {[], ""}
  end

  def complete("/" <> _ = input, context) do
    complete_command(input, context)
  end

  def complete("@" <> _ = input, context) do
    complete_at_reference(input, context)
  end

  def complete(input, context) do
    # Default: try file path completion
    complete_file_path(input, context)
  end

  @doc """
  Cycles to the next completion in the list.

  Given the current cycle index and a list of completions, returns
  `{next_index, completion}` where `next_index` wraps around.

  ## Examples

      iex> Mana.TUI.Completion.cycle(0, ["/model", "/model"])
      {1, "/model"}

      iex> Mana.TUI.Completion.cycle(2, ["a", "b", "c"])
      {0, "a"}
  """
  @spec cycle(non_neg_integer(), [completion()]) :: {non_neg_integer(), completion()}
  def cycle(_index, []) do
    {0, ""}
  end

  def cycle(index, completions) when is_list(completions) and length(completions) > 0 do
    count = length(completions)
    next = rem(index + 1, count)
    {next, Enum.at(completions, next)}
  end

  # ---------------------------------------------------------------------------
  # Command completion ( `/` prefix )
  # ---------------------------------------------------------------------------

  defp complete_command(input, _context) do
    # Check if there's a space — that means we're completing arguments
    parts = String.split(input, " ", parts: 2)

    case parts do
      [cmd] ->
        # Still typing the command name
        completions = match_commands(cmd)
        {completions, longest_common_prefix(completions, cmd)}

      [cmd, arg] ->
        # Command + argument — could dispatch to sub-completers
        completions = complete_command_arg(cmd, arg)
        replacement = cmd <> " " <> arg
        {completions, longest_common_prefix(completions, replacement)}

      _ ->
        {[], ""}
    end
  end

  defp match_commands(partial) do
    partial_lower = String.downcase(partial)

    CommandRegistry.list_commands()
    |> Enum.filter(fn cmd ->
      String.downcase(cmd) |> String.starts_with?(partial_lower)
    end)
    |> Enum.sort()
  end

  defp complete_command_arg("/model", arg) do
    match_agents(arg)
  end

  defp complete_command_arg("/agent", arg) do
    match_agents(arg)
  end

  defp complete_command_arg("/cd", arg) do
    complete_dir_path(arg)
  end

  defp complete_command_arg(_cmd, _arg) do
    []
  end

  # ---------------------------------------------------------------------------
  # Agent name completion ( `@` prefix )
  # ---------------------------------------------------------------------------

  defp complete_at_reference("@" <> rest, _context) do
    completions = match_agents(rest)

    # Re-add the @ prefix to all completions
    prefixed = Enum.map(completions, &("@" <> &1))
    {prefixed, longest_common_prefix(prefixed, "@" <> rest)}
  end

  defp match_agents(partial) do
    partial_lower = String.downcase(partial)

    case safe_list_agents() do
      nil ->
        []

      agents ->
        agents
        |> Enum.filter(fn agent ->
          name = agent.name
          String.downcase(name) |> String.starts_with?(partial_lower)
        end)
        |> Enum.map(fn agent -> agent.name end)
        |> Enum.sort()
    end
  end

  defp safe_list_agents do
    try do
      AgentRegistry.list_agents()
    rescue
      _ -> nil
    catch
      _, _ -> nil
    end
  end

  # ---------------------------------------------------------------------------
  # File path completion
  # ---------------------------------------------------------------------------

  defp complete_file_path(input, _context) do
    completions = complete_dir_path(input)
    {completions, longest_common_prefix(completions, input)}
  end

  defp complete_dir_path(partial) do
    expanded =
      if String.starts_with?(partial, "~/") do
        Path.expand(partial)
      else
        partial
      end

    {dir, prefix} =
      if expanded == "" or File.dir?(expanded) do
        {if(expanded == "", do: ".", else: expanded), ""}
      else
        {Path.dirname(expanded), Path.basename(expanded)}
      end

    case File.ls(dir) do
      {:ok, entries} ->
        prefix_lower = String.downcase(prefix)

        entries
        |> Enum.filter(fn entry ->
          String.downcase(entry) |> String.starts_with?(prefix_lower)
        end)
        |> Enum.sort()
        |> Enum.map(fn entry ->
          full = Path.join(dir, entry)

          if File.dir?(full) do
            # Preserve the original ~ prefix if present
            if String.starts_with?(partial, "~/") do
              "~/" <> String.trim_leading(full, Path.expand("~") <> "/") <> "/"
            else
              if dir == "." do
                entry <> "/"
              else
                full <> "/"
              end
            end
          else
            if dir == "." do
              entry
            else
              full
            end
          end
        end)
        |> Enum.take(50)

      {:error, _} ->
        []
    end
  end

  # ---------------------------------------------------------------------------
  # Helpers
  # ---------------------------------------------------------------------------

  @doc """
  Computes the longest common prefix shared by all strings in the list,
  bounded by the original input length (never shrinks below the input).

  Returns `""` if the list is empty.
  """
  @spec longest_common_prefix([String.t()], String.t()) :: String.t()
  def longest_common_prefix([], _original), do: ""

  def longest_common_prefix([single], _original), do: single

  def longest_common_prefix(completions, original) when is_list(completions) do
    prefix =
      completions
      |> Enum.reduce(fn a, b -> common_prefix_pair(a, b) end)

    # Ensure we always return something at least as long as the original
    if String.length(prefix) >= String.length(original) do
      prefix
    else
      original
    end
  end

  defp common_prefix_pair(a, b) do
    chars_a = String.graphemes(a)
    chars_b = String.graphemes(b)

    Enum.zip(chars_a, chars_b)
    |> Enum.take_while(fn {ca, cb} -> ca == cb end)
    |> Enum.map(fn {c, _} -> c end)
    |> Enum.join()
  end
end
