defmodule Mana.TelemetryHandler do
  @moduledoc """
  Telemetry handler that aggregates Mana event metrics into an ETS table.

  Tracks per-category (agents, tools, models) statistics:
  - Total runs/calls/requests
  - Total duration (native time units)
  - Error count
  - Per-tool and per-model breakdowns

  ## Usage

      Mana.TelemetryHandler.attach()   # call once at startup
      Mana.TelemetryHandler.get_stats()  # returns aggregated map
      Mana.TelemetryHandler.reset()      # clears all counters
  """

  @table :mana_telemetry_stats

  # Events we listen to — all `[:mana, *, *, :stop]` and `[:mana, *, *, :exception]`
  @agent_stop [:mana, :agent, :run, :stop]
  @agent_exception [:mana, :agent, :run, :exception]
  @tool_stop [:mana, :tool, :call, :stop]
  @tool_exception [:mana, :tool, :call, :exception]
  @model_stop [:mana, :model, :request, :stop]
  @model_exception [:mana, :model, :request, :exception]

  # Registry stat events (replacing GenServer.cast-based stats)
  @callbacks_dispatch [:mana, :callbacks, :registry, :dispatch]
  @tools_registry_call [:mana, :tools, :registry, :call]
  @tools_registry_error [:mana, :tools, :registry, :error]

  # ── Public API ────────────────────────────────────────────────

  @doc """
  Creates the ETS table (if not exists) and attaches telemetry handlers.
  Safe to call multiple times — attachments are idempotent by handler ID.
  """
  @spec attach() :: :ok
  def attach do
    ensure_table()

    # Use a constant handler ID so attach/0 is idempotent —
    # calling it again detaches the old handler and re-attaches.
    handler_id = {__MODULE__, :handler}

    # Detach first if already attached (safe even if not)
    :telemetry.detach(handler_id)

    :telemetry.attach_many(
      handler_id,
      [
        @agent_stop,
        @agent_exception,
        @tool_stop,
        @tool_exception,
        @model_stop,
        @model_exception,
        @callbacks_dispatch,
        @tools_registry_call,
        @tools_registry_error
      ],
      &__MODULE__.__handle_event__/4,
      nil
    )

    :ok
  end

  @doc """
  Returns all aggregated telemetry stats as a map.

      %{
        agents: %{count: N, total_duration: N, success_count: N, error_count: N},
        tools: %{count: N, total_duration: N, error_count: N, by_tool: %{"tool_name" => %{count: N, total_duration: N, error_count: N}}},
        models: %{count: N, total_duration: N, total_tokens_in: N, total_tokens_out: N, error_count: N, by_provider: %{"provider" => %{count: N, total_tokens_in: N, total_tokens_out: N, total_duration: N, error_count: N}}}
      }
  """
  @spec get_stats() :: map()
  def get_stats do
    %{
      agents: get_category(:agents),
      tools: get_category(:tools),
      models: get_category(:models)
    }
  end

  @doc """
  Clears all telemetry counters.
  """
  @spec reset() :: :ok
  def reset do
    if table_exists?(), do: :ets.delete_all_objects(@table)
    :ok
  end

  @doc """
  Returns a single counter value from telemetry aggregates.
  """
  @spec get_counter(atom(), atom()) :: non_neg_integer()
  def get_counter(category, field) do
    ensure_table()

    key = {category, field}

    case :ets.lookup(@table, key) do
      [{^key, value}] when is_integer(value) -> value
      [] -> 0
    end
  end

  # ── Telemetry handler callback ────────────────────────────────

  @doc false
  def __handle_event__(event_name, measurements, metadata, _config) do
    ensure_table()

    case event_name do
      [:mana, :agent, :run, :stop] ->
        handle_agent_stop(measurements, metadata)

      [:mana, :agent, :run, :exception] ->
        handle_agent_exception(measurements, metadata)

      [:mana, :tool, :call, :stop] ->
        handle_tool_stop(measurements, metadata)

      [:mana, :tool, :call, :exception] ->
        handle_tool_exception(measurements, metadata)

      [:mana, :model, :request, :stop] ->
        handle_model_stop(measurements, metadata)

      [:mana, :model, :request, :exception] ->
        handle_model_exception(measurements, metadata)

      [:mana, :callbacks, :registry, :dispatch] ->
        handle_callbacks_dispatch(measurements, metadata)

      [:mana, :tools, :registry, :call] ->
        handle_tools_registry_call(measurements, metadata)

      [:mana, :tools, :registry, :error] ->
        handle_tools_registry_error(measurements, metadata)

      _ ->
        :ok
    end
  end

  # ── Agent handling ────────────────────────────────────────────

  defp handle_agent_stop(measurements, metadata) do
    duration = Map.get(measurements, :duration, 0)
    success = Map.get(metadata, :success, true)

    increment(:agents, :count)
    increment(:agents, :total_duration, duration)

    if success do
      increment(:agents, :success_count)
    else
      increment(:agents, :error_count)
    end
  end

  defp handle_agent_exception(_measurements, _metadata) do
    increment(:agents, :count)
    increment(:agents, :error_count)
  end

  # ── Tool handling ─────────────────────────────────────────────

  defp handle_tool_stop(measurements, metadata) do
    duration = Map.get(measurements, :duration, 0)
    tool_name = Map.get(metadata, :tool_name, "unknown")
    has_error = Map.has_key?(metadata, :error)

    increment(:tools, :count)
    increment(:tools, :total_duration, duration)

    if has_error do
      increment(:tools, :error_count)
      increment_tool(tool_name, duration, true)
    else
      increment_tool(tool_name, duration, false)
    end
  end

  defp handle_tool_exception(measurements, metadata) do
    duration = Map.get(measurements, :duration, 0)
    tool_name = Map.get(metadata, :tool_name, "unknown")

    increment(:tools, :count)
    increment(:tools, :total_duration, duration)
    increment(:tools, :error_count)
    increment_tool(tool_name, duration, true)
  end

  defp increment_tool(tool_name, duration, is_error) do
    key = {:tool, tool_name}

    case :ets.lookup(@table, key) do
      [{^key, counts}] ->
        new_counts = %{
          count: counts.count + 1,
          total_duration: counts.total_duration + duration,
          error_count: counts.error_count + ((is_error && 1) || 0)
        }

        :ets.insert(@table, {key, new_counts})

      [] ->
        :ets.insert(
          @table,
          {key,
           %{
             count: 1,
             total_duration: duration,
             error_count: (is_error && 1) || 0
           }}
        )
    end
  end

  # ── Model handling ────────────────────────────────────────────

  defp handle_model_stop(measurements, metadata) do
    duration = Map.get(measurements, :duration, 0)
    provider = Map.get(metadata, :provider, "unknown")
    tokens_in = Map.get(metadata, :tokens_in, 0)
    tokens_out = Map.get(metadata, :tokens_out, 0)
    has_error = Map.has_key?(metadata, :error_type)

    increment(:models, :count)
    increment(:models, :total_duration, duration)
    increment(:models, :total_tokens_in, tokens_in)
    increment(:models, :total_tokens_out, tokens_out)

    if has_error do
      increment(:models, :error_count)
      increment_provider(provider, duration, tokens_in, tokens_out, true)
    else
      increment_provider(provider, duration, tokens_in, tokens_out, false)
    end
  end

  defp handle_model_exception(measurements, metadata) do
    duration = Map.get(measurements, :duration, 0)
    provider = Map.get(metadata, :provider, "unknown")

    increment(:models, :count)
    increment(:models, :total_duration, duration)
    increment(:models, :error_count)
    increment_provider(provider, duration, 0, 0, true)
  end

  defp increment_provider(provider, duration, tokens_in, tokens_out, is_error) do
    key = {:provider, provider}

    case :ets.lookup(@table, key) do
      [{^key, counts}] ->
        new_counts = %{
          count: counts.count + 1,
          total_tokens_in: counts.total_tokens_in + tokens_in,
          total_tokens_out: counts.total_tokens_out + tokens_out,
          total_duration: counts.total_duration + duration,
          error_count: counts.error_count + ((is_error && 1) || 0)
        }

        :ets.insert(@table, {key, new_counts})

      [] ->
        :ets.insert(
          @table,
          {key,
           %{
             count: 1,
             total_tokens_in: tokens_in,
             total_tokens_out: tokens_out,
             total_duration: duration,
             error_count: (is_error && 1) || 0
           }}
        )
    end
  end

  # ── Registry stat handling (replacing GenServer.cast-based stats) ───────────

  defp handle_callbacks_dispatch(measurements, _metadata) do
    count = Map.get(measurements, :count, 1)
    increment(:callbacks, :dispatches, count)
  end

  defp handle_tools_registry_call(_measurements, _metadata) do
    increment(:tools_registry, :calls)
  end

  defp handle_tools_registry_error(_measurements, _metadata) do
    increment(:tools_registry, :errors)
  end

  # ── ETS helpers ───────────────────────────────────────────────

  defp ensure_table do
    unless table_exists?() do
      :ets.new(@table, [:named_table, :public, :set])
    end
  end

  defp table_exists? do
    :ets.whereis(@table) != :undefined
  end

  defp increment(category, field, amount \\ 1) do
    key = {category, field}

    try do
      :ets.update_counter(@table, key, amount)
    rescue
      ArgumentError ->
        # Key doesn't exist yet — insert it
        :ets.insert(@table, {key, amount})
    end
  end

  defp get_category(category) do
    defaults = default_category_fields(category)

    Enum.reduce(defaults, %{}, fn field, acc ->
      value = get_counter(category, field)
      Map.put(acc, field, value)
    end)
    |> add_sub_category(category)
  end

  defp default_category_fields(:agents), do: [:count, :total_duration, :success_count, :error_count]
  defp default_category_fields(:tools), do: [:count, :total_duration, :error_count]

  defp default_category_fields(:models),
    do: [:count, :total_duration, :total_tokens_in, :total_tokens_out, :error_count]

  defp add_sub_category(base, :tools) do
    Map.put(base, :by_tool, get_all_tools())
  end

  defp add_sub_category(base, :models) do
    Map.put(base, :by_provider, get_all_providers())
  end

  defp add_sub_category(base, _), do: base

  defp get_all_tools do
    match_spec = [
      {{{:tool, :"$1"}, :"$2"}, [], [{{:"$1", :"$2"}}]}
    ]

    :ets.select(@table, match_spec)
    |> Map.new()
  end

  defp get_all_providers do
    match_spec = [
      {{{:provider, :"$1"}, :"$2"}, [], [{{:"$1", :"$2"}}]}
    ]

    :ets.select(@table, match_spec)
    |> Map.new()
  end
end
