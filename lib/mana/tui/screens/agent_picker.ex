defmodule Mana.TUI.Screens.AgentPicker do
  @moduledoc """
  Interactive agent picker screen.

  Displays all available agents and lets the user navigate, filter,
  and select one for the current session.

  ## Controls

    * `j` / `k`      – move selection down / up
    * `s`            – select the highlighted agent
    * `/ <query>`    – filter agents by name or description
    * `<number>`     – jump to agent by index and select it
    * `<name>`       – select agent by exact name match
    * `q`            – quit without changing agent

  ## Usage

      Mana.TUI.ScreenRunner.run(Mana.TUI.Screens.AgentPicker, session_id: "my-session")
  """

  @behaviour Mana.TUI.Screen

  alias Mana.Agents.Registry, as: AgentsRegistry

  # ---------------------------------------------------------------------------
  # Screen callbacks
  # ---------------------------------------------------------------------------

  @impl true
  def init(opts) do
    session_id = Keyword.get(opts, :session_id, "default")
    agents = AgentsRegistry.list_agents()
    current = current_agent_name(session_id)

    {:ok,
     %{
       agents: agents,
       filtered: agents,
       selected_index: 0,
       filter: "",
       current_agent: current,
       session_id: session_id
     }}
  end

  @impl true
  def render(state) do
    %{filtered: agents, selected_index: idx, filter: filter, current_agent: current} = state

    header =
      IO.ANSI.format([:bright, :cyan, "✦ Agent Picker", :reset])
      |> to_string()

    separator =
      IO.ANSI.format([:faint, String.duplicate("─", 48), :reset])
      |> to_string()

    filter_line =
      if filter == "" do
        IO.ANSI.format([:faint, "  Filter: (none)", :reset]) |> to_string()
      else
        IO.ANSI.format([:faint, "  Filter: ", :yellow, filter, :reset]) |> to_string()
      end

    current_line =
      IO.ANSI.format([:faint, "  Current: ", :green, current, :reset]) |> to_string()

    agent_lines =
      agents
      |> Enum.with_index()
      |> Enum.map(fn {agent, i} ->
        render_agent_line(agent, i, idx, current)
      end)
      |> Enum.join("\n")

    empty_msg =
      if agents == [] do
        "\n" <> (IO.ANSI.format([:yellow, "  No agents match filter.", :reset]) |> to_string())
      else
        ""
      end

    footer =
      IO.ANSI.format(
        [:faint, "  j/k: navigate • s: select • /filter • q: quit", :reset],
        []
      )
      |> to_string()

    "\n#{header}\n#{separator}\n\n#{current_line}\n#{filter_line}\n\n#{agent_lines}#{empty_msg}\n\n#{footer}\n"
  end

  @impl true
  def handle_input("q", _state), do: :exit

  def handle_input("j", state) do
    max_idx = max(length(state.filtered) - 1, 0)
    new_idx = min(state.selected_index + 1, max_idx)
    {:ok, %{state | selected_index: new_idx}}
  end

  def handle_input("k", state) do
    new_idx = max(state.selected_index - 1, 0)
    {:ok, %{state | selected_index: new_idx}}
  end

  def handle_input("s", state) do
    select_current(state)
  end

  def handle_input("/" <> query, state) do
    filter = String.trim(query)
    filtered = apply_filter(state.agents, filter)

    {:ok,
     %{
       state
       | filter: filter,
         filtered: filtered,
         selected_index: 0
     }}
  end

  def handle_input(input, state) do
    cond do
      # Numeric selection: "1", "3", etc.
      Regex.match?(~r/^\d+$/, input) ->
        case Integer.parse(input) do
          {num, ""} ->
            select_by_index(state, num - 1)

          _ ->
            {:ok, state}
        end

      # Try exact name match
      true ->
        select_by_name(state, input)
    end
  end

  # ---------------------------------------------------------------------------
  # Private helpers
  # ---------------------------------------------------------------------------

  defp select_current(state) do
    case Enum.at(state.filtered, state.selected_index) do
      nil ->
        {:ok, state}

      agent ->
        do_select(state, agent)
    end
  end

  defp select_by_index(state, idx) when idx >= 0 do
    case Enum.at(state.filtered, idx) do
      nil ->
        {:ok, state}

      agent ->
        do_select(state, agent)
    end
  end

  defp select_by_index(state, _idx), do: {:ok, state}

  defp select_by_name(state, name) do
    case Enum.find(state.filtered, fn a ->
           String.downcase(to_string(a.name)) == String.downcase(name)
         end) do
      nil ->
        # Not found — treat as a filter
        filtered = apply_filter(state.agents, name)

        {:ok,
         %{
           state
           | filter: name,
             filtered: filtered,
             selected_index: 0
         }}

      agent ->
        do_select(state, agent)
    end
  end

  defp do_select(state, agent) do
    name = to_string(agent.name)

    case AgentsRegistry.set_agent(state.session_id, name) do
      :ok ->
        {:done, agent}

      {:error, reason} ->
        IO.puts(IO.ANSI.format([:red, "Error: #{reason}", :reset]) |> to_string())

        {:ok, state}
    end
  end

  defp apply_filter(agents, ""), do: agents

  defp apply_filter(agents, query) do
    down_query = String.downcase(query)

    Enum.filter(agents, fn agent ->
      name = agent.name |> to_string() |> String.downcase()
      desc = agent.description |> to_string() |> String.downcase()
      display = agent.display_name |> to_string() |> String.downcase()

      String.contains?(name, down_query) or
        String.contains?(desc, down_query) or
        String.contains?(display, down_query)
    end)
  end

  defp current_agent_name(session_id) do
    case AgentsRegistry.current_agent(session_id) do
      nil -> "assistant"
      agent -> Map.get(agent, "name") || Map.get(agent, :name, "assistant")
    end
  end

  defp render_agent_line(agent, index, selected_idx, current_name) do
    name = to_string(agent.name)
    display = to_string(agent.display_name)
    desc = to_string(agent.description)
    is_current = name == current_name
    is_selected = index == selected_idx

    marker =
      if is_selected,
        do: IO.ANSI.format([:bright, :green, " ❯", :reset]) |> to_string(),
        else: "  "

    label =
      cond do
        is_selected and is_current ->
          IO.ANSI.format([:bright, :green, :underline, display, :reset]) |> to_string()

        is_selected ->
          IO.ANSI.format([:bright, :white, display, :reset]) |> to_string()

        is_current ->
          IO.ANSI.format([:cyan, display, :reset]) |> to_string()

        true ->
          IO.ANSI.format([:faint, display, :reset]) |> to_string()
      end

    idx_label =
      IO.ANSI.format([:faint, "#{index + 1}.", :reset]) |> to_string()

    desc_part =
      IO.ANSI.format([:faint, " – #{truncate(desc, 40)}", :reset]) |> to_string()

    current_badge =
      if is_current,
        do: " " <> (IO.ANSI.format([:yellow, "(current)", :reset]) |> to_string()),
        else: ""

    "  #{marker} #{idx_label} #{label}#{desc_part}#{current_badge}"
  end

  defp truncate(str, max_len) when byte_size(str) > max_len do
    String.slice(str, 0, max_len - 1) <> "…"
  end

  defp truncate(str, _max_len), do: str
end
