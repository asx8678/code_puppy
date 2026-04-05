defmodule Mana.TUI.Screens.Help do
  @moduledoc """
  Interactive help screen with auto-generated command reference.

  Displays all registered commands grouped by category with scrolling,
  filtering, and pagination support.

  ## Controls

    * `j` / `k` / Arrow keys – move selection down / up
    * `J` / `K`              – page down / page up
    * `/ <query>`            – filter commands by name or description
    * `q`                    – quit the help screen
    * `Enter`                – quit the help screen

  ## Usage

      Mana.TUI.ScreenRunner.run(Mana.TUI.Screens.Help)
  """

  @behaviour Mana.TUI.Screen

  alias Mana.Commands.Registry

  # Category ordering and display names
  @category_order [
    {"Core", "Core"},
    {"Session", "Session"},
    {"Agent", "Agent"},
    {"Model", "Model"},
    {"Pack", "Pack"},
    {"Config", "Config"},
    {"Diff", "Diff"},
    {"Stats", "Stats"},
    {"Hooks", "Hooks"},
    {"Colors", "Colors"},
    {"Other", "Other"}
  ]

  # Approximate visible rows (leaving room for header/footer)
  @page_size 18

  # ---------------------------------------------------------------------------
  # Screen callbacks
  # ---------------------------------------------------------------------------

  @impl true
  def init(_opts) do
    commands = load_commands()
    grouped = group_by_category(commands)
    flat_lines = build_flat_lines(grouped)

    {:ok,
     %{
       commands: commands,
       grouped: grouped,
       flat_lines: flat_lines,
       filtered_flat: flat_lines,
       filter: "",
       scroll_offset: 0,
       selected_index: 0
     }}
  end

  @impl true
  def render(state) do
    %{filtered_flat: lines, scroll_offset: offset, selected_index: idx, filter: filter} = state

    header =
      IO.ANSI.format([:bright, :cyan, "✦ Command Reference", :reset])
      |> to_string()

    separator =
      IO.ANSI.format([:faint, String.duplicate("─", 60), :reset])
      |> to_string()

    filter_line =
      if filter == "" do
        IO.ANSI.format([:faint, "  Filter: (press / to search)", :reset]) |> to_string()
      else
        IO.ANSI.format([:faint, "  Filter: ", :yellow, filter, :reset]) |> to_string()
      end

    # Compute visible window
    visible = Enum.slice(lines, offset, @page_size)
    total_lines = length(lines)

    # Highlight the selected line if it's in view
    rendered_lines =
      visible
      |> Enum.with_index(offset)
      |> Enum.map_join("\n", fn {line, i} ->
        if i == idx do
          # Highlight selected line
          IO.ANSI.format([:bright, :white, :reverse, pad_line(line.content, 58), :reset])
          |> to_string()
        else
          line.content
        end
      end)

    # Page indicator
    page_info =
      if total_lines > @page_size do
        max_page = max(1, ceil(total_lines / @page_size))
        current_page = div(offset, @page_size) + 1
        "  Page #{current_page}/#{max_page} • #{total_lines} items"
      else
        "  #{total_lines} commands"
      end

    footer =
      IO.ANSI.format(
        [:faint, "  j/k: scroll • J/K: page • /: filter • q: quit", :reset],
        []
      )
      |> to_string()

    "\n#{header}\n#{separator}\n\n#{filter_line}\n#{page_info}\n\n#{rendered_lines}\n\n#{footer}\n"
  end

  @impl true
  def handle_input("q", _state), do: :exit

  def handle_input("", _state), do: :exit

  # Scroll down
  def handle_input("j", state) do
    move_selection(state, 1)
  end

  def handle_input("\e[B", state) do
    # Arrow down
    move_selection(state, 1)
  end

  # Scroll up
  def handle_input("k", state) do
    move_selection(state, -1)
  end

  def handle_input("\e[A", state) do
    # Arrow up
    move_selection(state, -1)
  end

  # Page down
  def handle_input("J", state) do
    move_selection(state, @page_size)
  end

  # Page up
  def handle_input("K", state) do
    move_selection(state, -@page_size)
  end

  # Filter
  def handle_input("/" <> query, state) do
    filter = String.trim(query)

    filtered_flat =
      if filter == "" do
        state.flat_lines
      else
        apply_filter(state.flat_lines, filter)
      end

    {:ok,
     %{
       state
       | filter: filter,
         filtered_flat: filtered_flat,
         scroll_offset: 0,
         selected_index: 0
     }}
  end

  # Clear filter with backspace on empty
  def handle_input(_input, state) do
    {:ok, state}
  end

  # ---------------------------------------------------------------------------
  # Private helpers
  # ---------------------------------------------------------------------------

  defp load_commands do
    Registry.get_definitions()
  end

  defp group_by_category(commands) do
    grouped =
      commands
      |> Enum.group_by(fn cmd ->
        module_str = inspect(cmd.module)

        cond do
          String.contains?(module_str, "Commands.Core") -> "Core"
          String.contains?(module_str, "Commands.Session") -> "Session"
          String.contains?(module_str, "Commands.Agent") -> "Agent"
          String.contains?(module_str, "Commands.Model") -> "Model"
          String.contains?(module_str, "Commands.Pack") -> "Pack"
          String.contains?(module_str, "Commands.Config") -> "Config"
          String.contains?(module_str, "Commands.Diff") -> "Diff"
          String.contains?(module_str, "Commands.Stats") -> "Stats"
          String.contains?(module_str, "Commands.Hooks") -> "Hooks"
          String.contains?(module_str, "Commands.Colors") -> "Colors"
          true -> "Other"
        end
      end)

    # Build ordered groups, appending any unexpected categories at the end
    ordered =
      @category_order
      |> Enum.map(fn {key, label} -> {label, Map.get(grouped, key, [])} end)
      |> Enum.filter(fn {_label, cmds} -> cmds != [] end)

    # Add any categories not in the predefined order
    known_keys = Enum.map(@category_order, fn {k, _} -> k end)

    extra =
      grouped
      |> Enum.filter(fn {key, _} -> key not in known_keys end)
      |> Enum.map(fn {key, cmds} -> {key, cmds} end)
      |> Enum.sort_by(fn {key, _} -> key end)

    ordered ++ extra
  end

  defp build_flat_lines(grouped) do
    grouped
    |> Enum.flat_map(fn {category, commands} ->
      header_line = %{
        type: :category,
        content:
          IO.ANSI.format([:bright, :yellow, "  #{category}", :reset])
          |> to_string(),
        name: "",
        description: ""
      }

      cmd_lines =
        commands
        |> Enum.sort_by(& &1.name)
        |> Enum.map(fn cmd ->
          name = cmd.name
          desc = cmd.description || ""
          usage = cmd.usage || ""

          name_col =
            IO.ANSI.format([:bright, :cyan, "    #{pad_right(name, 16)}", :reset])
            |> to_string()

          desc_col =
            IO.ANSI.format([:faint, pad_right(desc, 30), :reset])
            |> to_string()

          usage_col =
            if usage != "" do
              IO.ANSI.format([:faint, :italic, usage, :reset]) |> to_string()
            else
              ""
            end

          %{
            type: :command,
            content: "#{name_col} #{desc_col} #{usage_col}",
            name: name,
            description: desc
          }
        end)

      [header_line | cmd_lines]
    end)
  end

  defp apply_filter(lines, query) do
    down_query = String.downcase(query)

    # Keep category headers that have matching commands below them
    lines
    |> Enum.chunk_while(
      {nil, []},
      fn
        %{type: :category} = line, {_, acc} ->
          # Emit previous group, start new accumulator
          entries =
            if acc != [] do
              acc
            else
              []
            end

          {:cont, entries, {line, []}}

        %{type: :command} = line, {header, acc} ->
          if String.contains?(String.downcase(line.name), down_query) or
               String.contains?(String.downcase(line.description), down_query) do
            {:cont, {header, acc ++ [line]}}
          else
            {:cont, {header, acc}}
          end
      end,
      fn
        {nil, []} -> {:cont, []}
        {header, acc} -> {:cont, if(acc != [], do: [header | acc], else: []), {nil, []}}
      end
    )
    |> List.flatten()
  end

  defp move_selection(state, delta) do
    max_idx = max(length(state.filtered_flat) - 1, 0)
    new_idx = state.selected_index + delta
    new_idx = new_idx |> max(0) |> min(max_idx)

    # Adjust scroll offset so selected line stays in view
    new_offset = adjust_scroll(state.scroll_offset, new_idx, length(state.filtered_flat))

    {:ok, %{state | selected_index: new_idx, scroll_offset: new_offset}}
  end

  defp adjust_scroll(offset, idx, total) do
    if total <= @page_size do
      0
    else
      cond do
        # Selected line is above the visible window
        idx < offset ->
          idx

        # Selected line is below the visible window
        idx >= offset + @page_size ->
          idx - @page_size + 1

        # Already visible
        true ->
          offset
      end
    end
  end

  defp pad_right(str, len) when byte_size(str) >= len, do: str
  defp pad_right(str, len), do: str <> String.duplicate(" ", len - byte_size(str))

  defp pad_line(str, len) do
    # Strip ANSI codes for length calculation
    plain = strip_ansi(str)
    padding = max(0, len - String.length(plain))
    str <> String.duplicate(" ", padding)
  end

  defp strip_ansi(str) do
    # Remove common ANSI escape sequences
    String.replace(str, ~r/\e\[[0-9;]*m/, "")
  end
end
