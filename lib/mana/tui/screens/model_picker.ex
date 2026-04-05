defmodule Mana.TUI.Screens.ModelPicker do
  @moduledoc """
  Interactive model picker screen.

  Displays all registered models grouped by provider and lets the user
  navigate, filter, and select one for the current session.

  ## Controls

    * `j` / `k`      – move selection down / up
    * `s` / Enter    – select the highlighted model
    * `/ <query>`    – filter models by name or provider
    * `<number>`     – jump to model by index and select it
    * `<name>`       – select model by exact name match
    * `q`            – quit without changing model

  ## Usage

      Mana.TUI.ScreenRunner.run(Mana.TUI.Screens.ModelPicker)
  """

  @behaviour Mana.TUI.Screen

  alias Mana.Config.Store, as: ConfigStore
  alias Mana.Models.Registry, as: ModelsRegistry

  # Provider display order and labels
  @provider_order ~w(anthropic openai ollama)
  @provider_labels %{
    "anthropic" => "Anthropic",
    "openai" => "OpenAI",
    "ollama" => "Ollama"
  }

  # ---------------------------------------------------------------------------
  # Screen callbacks
  # ---------------------------------------------------------------------------

  @impl true
  def init(_opts) do
    models = ModelsRegistry.list_models()
    current = ConfigStore.get(:current_model) || "claude-opus-4-6"
    entries = build_entries(models)

    {:ok,
     %{
       entries: entries,
       filtered: entries,
       selected_index: 0,
       filter: "",
       current_model: current
     }}
  end

  @impl true
  def render(state) do
    %{filtered: entries, selected_index: idx, filter: filter, current_model: current} = state

    header =
      IO.ANSI.format([:bright, :cyan, "✦ Model Picker", :reset])
      |> to_string()

    separator =
      IO.ANSI.format([:faint, String.duplicate("─", 58), :reset])
      |> to_string()

    filter_line =
      if filter == "" do
        IO.ANSI.format([:faint, "  Filter: (none)", :reset]) |> to_string()
      else
        IO.ANSI.format([:faint, "  Filter: ", :yellow, filter, :reset]) |> to_string()
      end

    current_line =
      IO.ANSI.format([:faint, "  Current: ", :green, current, :reset]) |> to_string()

    model_lines =
      entries
      |> Enum.with_index()
      |> Enum.map(fn {entry, i} ->
        render_model_line(entry, i, idx, current)
      end)
      |> Enum.join("\n")

    empty_msg =
      if entries == [] do
        "\n" <> (IO.ANSI.format([:yellow, "  No models match filter.", :reset]) |> to_string())
      else
        ""
      end

    footer =
      IO.ANSI.format(
        [:faint, "  j/k: navigate • s/Enter: select • /filter • q: quit", :reset],
        []
      )
      |> to_string()

    "\n#{header}\n#{separator}\n\n#{current_line}\n#{filter_line}\n\n#{model_lines}#{empty_msg}\n\n#{footer}\n"
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

  def handle_input("s", state), do: select_current(state)

  def handle_input("", state), do: select_current(state)

  def handle_input("/" <> query, state) do
    filter = String.trim(query)
    filtered = apply_filter(state.entries, filter)

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
  # Entry building
  # ---------------------------------------------------------------------------

  defp build_entries(models) do
    models
    |> Enum.map(fn {name, config} ->
      %{
        name: name,
        provider: get_in(config, ["provider"]) || get_in(config, [:provider]) || "other",
        max_tokens: get_in(config, ["max_tokens"]) || get_in(config, [:max_tokens]) || 4096,
        supports_tools: get_in(config, ["supports_tools"]) || get_in(config, [:supports_tools]) || false,
        supports_vision: get_in(config, ["supports_vision"]) || get_in(config, [:supports_vision]) || false
      }
    end)
    |> sort_by_provider()
  end

  defp sort_by_provider(entries) do
    Enum.sort_by(entries, fn entry ->
      idx = Enum.find_index(@provider_order, &(&1 == entry.provider)) || 999
      {idx, entry.name}
    end)
  end

  # ---------------------------------------------------------------------------
  # Selection helpers
  # ---------------------------------------------------------------------------

  defp select_current(state) do
    case Enum.at(state.filtered, state.selected_index) do
      nil ->
        {:ok, state}

      entry ->
        do_select(state, entry)
    end
  end

  defp select_by_index(state, idx) when idx >= 0 do
    case Enum.at(state.filtered, idx) do
      nil -> {:ok, state}
      entry -> do_select(state, entry)
    end
  end

  defp select_by_index(state, _idx), do: {:ok, state}

  defp select_by_name(state, name) do
    case Enum.find(state.filtered, fn e ->
           String.downcase(e.name) == String.downcase(name)
         end) do
      nil ->
        # Not found — treat as a filter
        filtered = apply_filter(state.entries, name)

        {:ok,
         %{
           state
           | filter: name,
             filtered: filtered,
             selected_index: 0
         }}

      entry ->
        do_select(state, entry)
    end
  end

  defp do_select(_state, entry) do
    ConfigStore.put(:current_model, entry.name)
    {:done, entry.name}
  end

  # ---------------------------------------------------------------------------
  # Filter
  # ---------------------------------------------------------------------------

  defp apply_filter(entries, ""), do: entries

  defp apply_filter(entries, query) do
    down_query = String.downcase(query)

    Enum.filter(entries, fn entry ->
      name = String.downcase(entry.name)
      provider = String.downcase(entry.provider)
      label = @provider_labels[entry.provider] |> to_string() |> String.downcase()

      String.contains?(name, down_query) or
        String.contains?(provider, down_query) or
        String.contains?(label, down_query)
    end)
  end

  # ---------------------------------------------------------------------------
  # Rendering
  # ---------------------------------------------------------------------------

  defp render_model_line(entry, index, selected_idx, current_model) do
    is_current = entry.name == current_model
    is_selected = index == selected_idx

    marker =
      if is_selected,
        do: IO.ANSI.format([:bright, :green, " ❯", :reset]) |> to_string(),
        else: "  "

    idx_label =
      IO.ANSI.format([:faint, "#{index + 1}.", :reset]) |> to_string()

    label =
      cond do
        is_selected and is_current ->
          IO.ANSI.format([:bright, :green, :underline, entry.name, :reset]) |> to_string()

        is_selected ->
          IO.ANSI.format([:bright, :white, entry.name, :reset]) |> to_string()

        is_current ->
          IO.ANSI.format([:cyan, entry.name, :reset]) |> to_string()

        true ->
          IO.ANSI.format([:faint, entry.name, :reset]) |> to_string()
      end

    capabilities = render_capabilities(entry)
    max_tok = render_max_tokens(entry)
    provider_tag = render_provider_tag(entry)

    current_badge =
      if is_current,
        do: " " <> (IO.ANSI.format([:yellow, "(current)", :reset]) |> to_string()),
        else: ""

    "  #{marker} #{idx_label} #{label} #{capabilities} #{max_tok} #{provider_tag}#{current_badge}"
  end

  defp render_capabilities(entry) do
    tools =
      if entry.supports_tools,
        do: IO.ANSI.format([:faint, "🔧", :reset]) |> to_string(),
        else: " "

    vision =
      if entry.supports_vision,
        do: IO.ANSI.format([:faint, "👁", :reset]) |> to_string(),
        else: " "

    "#{tools}#{vision}"
  end

  defp render_max_tokens(entry) do
    IO.ANSI.format([:faint, format_tokens(entry.max_tokens), :reset]) |> to_string()
  end

  defp render_provider_tag(entry) do
    label = Map.get(@provider_labels, entry.provider, "Other")
    IO.ANSI.format([:faint, "[", :blue, label, :faint, "]", :reset]) |> to_string()
  end

  defp format_tokens(n) when n >= 1_000_000, do: "#{div(n, 1_000)}k"
  defp format_tokens(n) when n >= 1_000, do: "#{div(n, 1_000)}k"
  defp format_tokens(n), do: "#{n}"
end
